# -*- coding: utf-8 -*-
import asyncio
import aiohttp
import struct
from typing import Dict, Any, Optional, TypedDict
from decimal import Decimal, getcontext
from solders.pubkey import Pubkey as PublicKey
from solana.rpc.async_api import AsyncClient as SolanaAsyncClient

from logging_system import AppLogger

# Configurar la precisión para los cálculos con Decimal
getcontext().prec = 26

class TokenTradingInfo(TypedDict):
    name: str
    symbol: str
    sol_per_token: str
    usd_per_token: str


class TradingDataFetcher:
    """
    Cliente asíncrono para obtener datos de trading de tokens de pump.fun.
    Compatible con async with y optimizado para copy trading.
    """
    DEXSCREENER_BASE_URL = "https://api.dexscreener.com/latest/dex"
    JUPITER_LITE_API = "https://lite-api.jup.ag/price/v2"
    SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"

    # Constantes para Pump.fun fallback
    PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    PUMP_CURVE_SEED = b"bonding-curve"
    PUMP_CURVE_TOKEN_DECIMALS = 6
    LAMPORTS_PER_SOL = 1_000_000_000
    PUMP_CURVE_STATE_SIGNATURE = bytes([0x17, 0xb7, 0xf8, 0x37, 0x60, 0xd8, 0xac, 0x60])
    CURVE_STATE_OFFSETS = {
        'VIRTUAL_TOKEN_RESERVES': 0x08,
        'VIRTUAL_SOL_RESERVES': 0x10,
        'REAL_TOKEN_RESERVES': 0x18,
        'REAL_SOL_RESERVES': 0x20,
        'TOKEN_TOTAL_SUPPLY': 0x28,
        'COMPLETE': 0x30,
    }

    def __init__(self, session: Optional[aiohttp.ClientSession] = None, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        """
        Inicializa el fetcher.

        Args:
            session (Optional[aiohttp.ClientSession], optional):
                Permite pasar una sesión de aiohttp existente para compartir conexiones.
                Si no se provee, se creará una nueva.
            rpc_url (str): URL del RPC de Solana para fallback de Pump.fun
        """
        try:
            self._session = session
            self._own_session = session is None
            if self._own_session:
                # Configurar timeout más agresivo para trading
                timeout = aiohttp.ClientTimeout(total=3, connect=1, sock_read=2)
                self.session = aiohttp.ClientSession(timeout=timeout)
            else:
                self.session = self._session

            # Para fallback de Pump.fun
            self.rpc_url = rpc_url
            self.rpc_client: Optional[SolanaAsyncClient] = None

            # Cache para precios
            self._sol_price_cache = None
            self._sol_price_cache_time = 0
            self._cache_duration = 30  # 30 segundos

            self._logger = AppLogger(self.__class__.__name__)
            self._logger.debug("TradingDataFetcher inicializado")
        except Exception as e:
            print(f"Error inicializando TradingDataFetcher: {e}")
            raise

    async def __aenter__(self):
        """Context manager entry"""
        try:
            self._logger.debug("Iniciando TradingDataFetcher con context manager")
            return self
        except Exception as e:
            self._logger.error(f"Error en context manager entry: {e}")
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        try:
            await self.close()
        except Exception as e:
            self._logger.error(f"Error en context manager exit: {e}")

    async def close(self):
        """
        Cierra la sesión de aiohttp si fue creada por esta instancia.
        """
        try:
            self._logger.debug("Iniciando cierre de TradingDataFetcher")
            if self._own_session and self.session and not self.session.closed:
                await self.session.close()
                self._logger.debug("Sesión de aiohttp cerrada")

            # Cerrar cliente RPC si existe
            if self.rpc_client:
                await self.rpc_client.close()
                self.rpc_client = None
                self._logger.debug("Cliente RPC de Solana cerrado")

            self._logger.debug("TradingDataFetcher cerrado")
        except Exception as e:
            self._logger.error(f"Error cerrando TradingDataFetcher: {e}")

    async def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        Realiza una petición GET a una URL con timeout agresivo.
        """
        try:
            if self.session is None:
                raise ValueError("Session is not initialized")

            async with self.session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                self._logger.debug(f"Petición GET exitosa a {url}")
                return data
        except Exception as e:
            self._logger.error(f"Error en petición GET a {url}: {e}")
            raise

    async def _init_rpc_client(self):
        """Inicializa el cliente RPC si no existe"""
        try:
            if not self.rpc_client:
                self.rpc_client = SolanaAsyncClient(self.rpc_url)
                self._logger.debug("Cliente RPC de Solana inicializado")
        except Exception as e:
            self._logger.error(f"Error inicializando cliente RPC: {e}")

    def _find_pump_curve_address(self, token_mint: str) -> Optional[str]:
        """Encuentra la dirección de la bonding curve para un token"""
        try:
            token_pubkey = PublicKey.from_string(token_mint)
            program_pubkey = PublicKey.from_string(self.PUMP_PROGRAM_ID)
            curve_address, _ = PublicKey.find_program_address(
                [self.PUMP_CURVE_SEED, bytes(token_pubkey)],
                program_pubkey
            )
            self._logger.debug(f"Dirección de bonding curve encontrada para {token_mint}")
            return str(curve_address)
        except Exception as e:
            self._logger.error(f"Error encontrando bonding curve para {token_mint}: {e}")
            return None

    async def _get_pump_curve_state(self, curve_address: str) -> Optional[Dict[str, Any]]:
        """Obtiene el estado de la bonding curve desde la blockchain"""
        try:
            if not self.rpc_client:
                await self._init_rpc_client()

            if not self.rpc_client:
                raise ValueError("RPC client not initialized")

            curve_pubkey = PublicKey.from_string(curve_address)
            response = await self.rpc_client.get_account_info(curve_pubkey)

            if not response.value or not response.value.data:
                self._logger.debug(f"No se encontró información de cuenta para {curve_address}")
                return None

            data = response.value.data
            if isinstance(data, list):
                data = bytes(data)
            elif isinstance(data, str):
                import base64
                data = base64.b64decode(data)

            if len(data) < len(self.PUMP_CURVE_STATE_SIGNATURE) + 0x31:
                self._logger.debug(f"Datos de cuenta insuficientes para {curve_address}")
                return None

            signature = data[:len(self.PUMP_CURVE_STATE_SIGNATURE)]
            if signature != self.PUMP_CURVE_STATE_SIGNATURE:
                self._logger.debug(f"Firma de bonding curve inválida para {curve_address}")
                return None

            def read_u64_le(offset: int) -> int:
                return struct.unpack('<Q', data[offset:offset + 8])[0]

            def read_bool(offset: int) -> bool:
                return data[offset] != 0

            curve_state = {
                'virtual_token_reserves': read_u64_le(self.CURVE_STATE_OFFSETS['VIRTUAL_TOKEN_RESERVES']),
                'virtual_sol_reserves': read_u64_le(self.CURVE_STATE_OFFSETS['VIRTUAL_SOL_RESERVES']),
                'real_token_reserves': read_u64_le(self.CURVE_STATE_OFFSETS['REAL_TOKEN_RESERVES']),
                'real_sol_reserves': read_u64_le(self.CURVE_STATE_OFFSETS['REAL_SOL_RESERVES']),
                'token_total_supply': read_u64_le(self.CURVE_STATE_OFFSETS['TOKEN_TOTAL_SUPPLY']),
                'complete': read_bool(self.CURVE_STATE_OFFSETS['COMPLETE'])
            }

            self._logger.debug(f"Estado de bonding curve obtenido para {curve_address}")
            return curve_state

        except Exception as e:
            self._logger.error(f"Error obteniendo estado de bonding curve para {curve_address}: {e}")
            return None

    def _calculate_pump_price(self, curve_state: Dict[str, Any]) -> Optional[str]:
        """Calcula el precio del token basado en el estado de la bonding curve"""
        try:
            virtual_token_reserves = curve_state['virtual_token_reserves']
            virtual_sol_reserves = curve_state['virtual_sol_reserves']

            # Usar Decimal para comparaciones consistentes con las preferencias del usuario
            if Decimal(str(virtual_token_reserves)) <= Decimal('0') or Decimal(str(virtual_sol_reserves)) <= Decimal('0'):
                self._logger.debug("Reservas virtuales inválidas para cálculo de precio")
                return None

            sol_reserves = Decimal(str(virtual_sol_reserves)) / Decimal(str(self.LAMPORTS_PER_SOL))
            token_reserves = Decimal(str(virtual_token_reserves)) / Decimal(str(10 ** self.PUMP_CURVE_TOKEN_DECIMALS))

            # Verificar que token_reserves no sea cero antes de dividir
            if token_reserves <= 0:
                self._logger.debug("Reservas de token inválidas para cálculo de precio")
                return None

            price = format(sol_reserves / token_reserves, 'f')
            self._logger.debug(f"Precio calculado: {price} SOL por token")
            return price
        except Exception as e:
            self._logger.error(f"Error calculando precio de bonding curve: {e}")
            return None

    async def get_pump_token_data(self, token_address: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene los datos completos de un token de pump.fun desde DexScreener.
        """
        try:
            url = f"{self.DEXSCREENER_BASE_URL}/tokens/{token_address}"
            self._logger.debug(f"Obteniendo datos de DexScreener para {token_address}")

            data = await self._get(url)
            if data and data.get("pairs"):
                self._logger.debug(f"Datos de DexScreener obtenidos para {token_address}")
                return data
            else:
                self._logger.debug(f"No se encontraron datos de DexScreener para {token_address}")
                return None
        except aiohttp.ClientResponseError as e:
            if e.status == 404 or "not found" in str(e).lower():
                self._logger.debug(f"Token {token_address} no encontrado en DexScreener")
                return None
            else:
                self._logger.error(f"Error de respuesta de DexScreener para {token_address}: {e}")
                return None
        except Exception as e:
            self._logger.error(f"Error obteniendo datos de DexScreener para {token_address}: {e}")
            return None

    async def get_sol_price_usd(self) -> Optional[str]:
        """
        Obtiene el precio actual de SOL en USD usando Jupiter Lite API.
        Incluye cache para evitar consultas repetitivas.

        Returns:
            Optional[str]: El precio de SOL como string, o None si no se puede obtener.
        """
        import time
        current_time = time.time()

        # Verificar cache
        if (self._sol_price_cache and 
            current_time - self._sol_price_cache_time < self._cache_duration):
            self._logger.debug("Precio de SOL obtenido del cache")
            return self._sol_price_cache

        try:
            url = f"{self.JUPITER_LITE_API}?ids={self.SOL_MINT_ADDRESS}"
            self._logger.debug("Obteniendo precio de SOL desde Jupiter Lite API")

            if self.session is None:
                raise ValueError("Session is not initialized")

            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    data = await response.json()
                    price = Decimal(str(data['data'][self.SOL_MINT_ADDRESS]['price']))
                    price_str = format(price, 'f')
                    # Actualizar cache
                    self._sol_price_cache = price_str
                    self._sol_price_cache_time = current_time
                    self._logger.debug(f"Precio de SOL actualizado: {price_str} USD")
                    return price_str
                else:
                    self._logger.error(f"Error obteniendo precio de SOL: status {response.status}")
                    return None
        except Exception as e:
            self._logger.error(f"Error obteniendo precio de SOL: {e}")
            return None

    async def get_token_trading_info(self, token_address: str) -> Optional[TokenTradingInfo]:
        """
        Obtiene la cotización de un token en términos de SOL.

        Args:
            token_address (str): La dirección del token.

        Returns:
            Optional[TokenTradingInfo]: Un diccionario con:
                - 'name': Nombre del token.
                - 'symbol': Símbolo del token.
                - 'sol_per_token': Precio del token en SOL.
                - 'usd_per_token': Precio del token en USD.
                O None si no se encuentran datos.
        """
        try:
            self._logger.debug(f"Obteniendo información de trading para {token_address}")

            # 1. Intentar con DexScreener
            data = await self.get_pump_token_data(token_address)

            if data and data.get("pairs"):
                pair = data["pairs"][0]

                base_token: Dict[str, str] = pair.get("baseToken", {})
                price_native_str: str = pair.get("priceNative")
                price_usd_str: str = pair.get("priceUsd")

                if all([base_token, price_native_str, price_usd_str]):
                    result: TokenTradingInfo = {
                        "name": base_token.get("name", ""),
                        "symbol": base_token.get("symbol", ""),
                        "sol_per_token": price_native_str,
                        "usd_per_token": price_usd_str
                    }
                    self._logger.debug(f"Información de trading obtenida desde DexScreener para {token_address}")
                    return result
                else:
                    self._logger.debug(f"Datos incompletos de DexScreener para {token_address}")
            else:
                self._logger.debug(f"No se encontraron datos de DexScreener para {token_address}")

            # 2. Fallback: usar Pump.fun bonding curve
            self._logger.debug(f"Intentando fallback con bonding curve para {token_address}")

            # Encontrar bonding curve
            curve_address = self._find_pump_curve_address(token_address)
            if not curve_address:
                self._logger.debug(f"No se pudo encontrar bonding curve para {token_address}")
                return None

            # Obtener estado de la curve
            curve_state = await self._get_pump_curve_state(curve_address)
            if not curve_state:
                self._logger.debug(f"No se pudo obtener estado de bonding curve para {token_address}")
                return None

            # Calcular precio en SOL
            price_sol = self._calculate_pump_price(curve_state)
            if price_sol is None or Decimal(price_sol) <= Decimal('0'):
                self._logger.debug(f"Precio calculado inválido para {token_address}")
                return None

            # Obtener precio de SOL en USD (usando cache)
            sol_price_usd = await self.get_sol_price_usd()
            if not sol_price_usd:
                self._logger.debug(f"No se pudo obtener precio de SOL para calcular USD de {token_address}")
                return None

            sol_price_decimal = Decimal(sol_price_usd)
            price_usd = Decimal(price_sol) * sol_price_decimal

            result_pump: TokenTradingInfo = {
                "name": "Unknown",  # No tenemos nombre desde bonding curve
                "symbol": "UNK",    # No tenemos símbolo desde bonding curve
                "sol_per_token": price_sol,
                "usd_per_token": str(price_usd)
            }
            self._logger.debug(f"Información de trading obtenida desde bonding curve para {token_address}")
            return result_pump

        except Exception as e:
            self._logger.error(f"Error obteniendo información de trading para {token_address}: {e}")
            return None


# Ejemplo de uso para verificar la funcionalidad
async def main():
    from time import time

    # Usar async with para gestión automática de recursos
    async with TradingDataFetcher() as fetcher:
        try:
            # 1. Obtener precio de SOL/USD
            start_time = time()
            sol_price = await fetcher.get_sol_price_usd()
            end_time = time()
            if sol_price:
                print(f"Precio de SOL: {sol_price} USD (en {end_time - start_time:.3f}s)")
            else:
                print("No se pudo obtener precio de SOL")

            # 2. Obtener datos de un token de pump.fun
            token_address = "6F6jjd71nbjwUZNi93wpXimbyH12CLkeMNJ6X1brpump"

            start_time = time()
            token_data = await fetcher.get_pump_token_data(token_address)
            end_time = time()
            if token_data:
                print(f"Datos de token obtenidos (en {end_time - start_time:.3f}s)")
            else:
                print("No se pudieron obtener datos del token")

            # 3. Obtener cotización del token en SOL
            quotes_in_sol = await fetcher.get_token_trading_info(token_address)
            if quotes_in_sol:
                print(f"Cotización: {quotes_in_sol}")
            else:
                print("No se pudo obtener cotización del token")

        except Exception as e:
            print(f"Error en main: {e}")


if __name__ == "__main__":
    asyncio.run(main())
