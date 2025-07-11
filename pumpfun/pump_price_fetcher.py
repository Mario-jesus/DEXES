# -*- coding: utf-8 -*-
"""
Pump.fun Price Fetcher - Obtiene precios directamente de la bonding curve
Basado en el método oficial de Pump.fun para calcular precios
"""
import struct
import aiohttp
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

from solders.pubkey import Pubkey as PublicKey
from solana.rpc.async_api import AsyncClient as SolanaAsyncClient


@dataclass
class PumpCurveState:
    """Estado de la bonding curve de Pump.fun"""
    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    token_total_supply: int
    complete: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            'virtual_token_reserves': self.virtual_token_reserves,
            'virtual_sol_reserves': self.virtual_sol_reserves,
            'real_token_reserves': self.real_token_reserves,
            'real_sol_reserves': self.real_sol_reserves,
            'token_total_supply': self.token_total_supply,
            'complete': self.complete
        }


@dataclass
class PumpTokenPrice:
    """Precio de token de Pump.fun"""
    token_address: str
    price_sol: float
    price_usd: float
    market_cap_usd: float
    bonding_progress: float
    curve_state: PumpCurveState
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            'token_address': self.token_address,
            'price_sol': self.price_sol,
            'price_usd': self.price_usd,
            'market_cap_usd': self.market_cap_usd,
            'bonding_progress': self.bonding_progress,
            'curve_state': self.curve_state.to_dict(),
            'timestamp': self.timestamp.isoformat()
        }


class PumpFunPriceFetcher:
    """
    Fetcher de precios para tokens de Pump.fun
    Accede directamente a la bonding curve usando RPC de Solana
    """

    # Constantes de Pump.fun
    PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    PUMP_CURVE_SEED = b"bonding-curve"
    PUMP_CURVE_TOKEN_DECIMALS = 6
    LAMPORTS_PER_SOL = 1_000_000_000

    # Signature de la bonding curve (primeros 8 bytes de sha256("account:BondingCurve"))
    PUMP_CURVE_STATE_SIGNATURE = bytes([0x17, 0xb7, 0xf8, 0x37, 0x60, 0xd8, 0xac, 0x60])

    # Offsets para deserializar los datos de la curve
    CURVE_STATE_OFFSETS = {
        'VIRTUAL_TOKEN_RESERVES': 0x08,
        'VIRTUAL_SOL_RESERVES': 0x10,
        'REAL_TOKEN_RESERVES': 0x18,
        'REAL_SOL_RESERVES': 0x20,
        'TOKEN_TOTAL_SUPPLY': 0x28,
        'COMPLETE': 0x30,
    }

    # Reservas iniciales para calcular progreso de bonding curve
    INITIAL_REAL_TOKEN_RESERVES = 793_100_000_000_000

    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        """
        Inicializa el fetcher de precios de Pump.fun
        
        Args:
            rpc_url: URL del RPC de Solana
        """
        self.rpc_url = rpc_url
        self.rpc_client: Optional[SolanaAsyncClient] = None
        self.http_session: Optional[aiohttp.ClientSession] = None

        print("🎯 Pump.fun Price Fetcher inicializado")
        print(f"🌐 Configurado para conectar a {rpc_url}")

    async def __aenter__(self):
        """Context manager entry - inicializa conexiones"""
        print("🔌 Iniciando sesión de Pump.fun Price Fetcher...")

        # Inicializar cliente RPC asíncrono
        self.rpc_client = SolanaAsyncClient(self.rpc_url)

        # Inicializar sesión HTTP
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'PumpFunPriceFetcher/1.0'}
        )

        # Probar conexión
        await self.test_connection()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cierra conexiones"""
        print("🔌 Cerrando sesión de Pump.fun Price Fetcher...")

        # Cerrar cliente RPC
        if self.rpc_client:
            await self.rpc_client.close()
            self.rpc_client = None

        # Cerrar sesión HTTP
        if self.http_session:
            await self.http_session.close()
            self.http_session = None

        print("✅ Sesión de Pump.fun Price Fetcher cerrada correctamente")

    async def test_connection(self) -> bool:
        """
        Prueba la conexión al RPC de Solana
        
        Returns:
            True si la conexión es exitosa, False si no
        """
        try:
            if not self.rpc_client:
                print("❌ Cliente RPC no inicializado")
                return False

            # Obtener el slot actual como prueba de conexión
            response = await self.rpc_client.get_slot()
            if response.value:
                print(f"✅ Conexión RPC exitosa - Slot actual: {response.value}")
                return True
            else:
                print("❌ No se pudo obtener el slot actual")
                return False
        except Exception as e:
            print(f"❌ Error probando conexión RPC: {e}")
            return False

    async def get_rpc_status(self) -> Dict[str, Any]:
        """
        Obtiene el estado de la conexión RPC
        
        Returns:
            Diccionario con información del estado RPC
        """
        try:
            if not self.rpc_client:
                return {
                    'connected': False,
                    'rpc_url': self.rpc_url,
                    'current_slot': None,
                    'version': None,
                    'error': "Cliente RPC no inicializado"
                }

            slot_response = await self.rpc_client.get_slot()
            version_response = await self.rpc_client.get_version()

            return {
                'connected': True,
                'rpc_url': self.rpc_url,
                'current_slot': slot_response.value if slot_response.value else None,
                'version': version_response.value if version_response.value else None,
                'error': None
            }
        except Exception as e:
            return {
                'connected': False,
                'rpc_url': self.rpc_url,
                'current_slot': None,
                'version': None,
                'error': str(e)
            }

    def find_pump_curve_address(self, token_mint: str) -> str:
        """
        Encuentra la dirección de la bonding curve para un token
        
        Args:
            token_mint: Dirección del token mint
            
        Returns:
            Dirección de la bonding curve
        """
        try:
            token_pubkey = PublicKey.from_string(token_mint)
            program_pubkey = PublicKey.from_string(self.PUMP_PROGRAM_ID)

            # Encontrar PDA (Program Derived Address)
            curve_address, _ = PublicKey.find_program_address(
                [self.PUMP_CURVE_SEED, bytes(token_pubkey)],
                program_pubkey
            )

            return str(curve_address)

        except Exception as e:
            print(f"❌ Error encontrando curve address: {e}")
            return None

    async def get_pump_curve_state(self, curve_address: str) -> Optional[PumpCurveState]:
        """
        Obtiene el estado de la bonding curve desde la blockchain
        
        Args:
            curve_address: Dirección de la bonding curve
            
        Returns:
            Estado de la curve o None si hay error
        """
        try:
            if not self.rpc_client:
                print("❌ Cliente RPC no inicializado")
                return None

            curve_pubkey = PublicKey.from_string(curve_address)

            # Obtener datos de la cuenta usando el cliente RPC asíncrono
            response = await self.rpc_client.get_account_info(curve_pubkey)

            # Verificar si la respuesta es exitosa
            if not response.value:
                print(f"❌ No se encontró la cuenta de la bonding curve")
                return None

            # Obtener los datos de la cuenta
            account_data = response.value.data

            # Verificar que hay datos
            if not account_data:
                print(f"❌ No se encontraron datos de la curve")
                return None

            # Convertir los datos a bytes si es necesario
            if isinstance(account_data, list):
                data = bytes(account_data)
            elif isinstance(account_data, str):
                # Si es base64, decodificar
                import base64
                data = base64.b64decode(account_data)
            else:
                data = account_data

            # Verificar que hay suficientes datos
            min_required_length = len(self.PUMP_CURVE_STATE_SIGNATURE) + 0x31
            if len(data) < min_required_length:
                print(f"❌ Datos de curve incompletos (esperado: {min_required_length}, obtenido: {len(data)})")
                return None

            # Verificar signature
            signature = data[:len(self.PUMP_CURVE_STATE_SIGNATURE)]
            if signature != self.PUMP_CURVE_STATE_SIGNATURE:
                print(f"❌ Signature de curve inválida")
                print(f"   Esperado: {self.PUMP_CURVE_STATE_SIGNATURE.hex()}")
                print(f"   Obtenido: {signature.hex()}")
                return None

            # Extraer datos usando offsets
            def read_u64_le(offset: int) -> int:
                """Lee un uint64 little-endian desde el offset especificado"""
                if offset + 8 > len(data):
                    raise ValueError(f"Offset {offset} fuera de rango")
                return struct.unpack('<Q', data[offset:offset + 8])[0]

            def read_bool(offset: int) -> bool:
                """Lee un boolean desde el offset especificado"""
                if offset >= len(data):
                    raise ValueError(f"Offset {offset} fuera de rango")
                return data[offset] != 0

            # Crear el estado de la curve
            curve_state = PumpCurveState(
                virtual_token_reserves=read_u64_le(self.CURVE_STATE_OFFSETS['VIRTUAL_TOKEN_RESERVES']),
                virtual_sol_reserves=read_u64_le(self.CURVE_STATE_OFFSETS['VIRTUAL_SOL_RESERVES']),
                real_token_reserves=read_u64_le(self.CURVE_STATE_OFFSETS['REAL_TOKEN_RESERVES']),
                real_sol_reserves=read_u64_le(self.CURVE_STATE_OFFSETS['REAL_SOL_RESERVES']),
                token_total_supply=read_u64_le(self.CURVE_STATE_OFFSETS['TOKEN_TOTAL_SUPPLY']),
                complete=read_bool(self.CURVE_STATE_OFFSETS['COMPLETE'])
            )

            print(f"✅ Curve state obtenido exitosamente")
            print(f"   📊 Virtual Token Reserves: {curve_state.virtual_token_reserves:,}")
            print(f"   💰 Virtual SOL Reserves: {curve_state.virtual_sol_reserves:,}")
            print(f"   📈 Real Token Reserves: {curve_state.real_token_reserves:,}")
            print(f"   💎 Real SOL Reserves: {curve_state.real_sol_reserves:,}")
            print(f"   🎯 Total Supply: {curve_state.token_total_supply:,}")
            print(f"   ✅ Complete: {curve_state.complete}")

            return curve_state

        except ValueError as e:
            print(f"❌ Error de formato en datos de curve: {e}")
            return None
        except Exception as e:
            print(f"❌ Error obteniendo curve state: {e}")
            return None

    def calculate_pump_curve_price(self, curve_state: PumpCurveState) -> float:
        """
        Calcula el precio del token basado en el estado de la bonding curve
        Usa la fórmula oficial de Pump.fun
        
        Args:
            curve_state: Estado de la bonding curve
            
        Returns:
            Precio del token en SOL
        """
        try:
            if (curve_state.virtual_token_reserves <= 0 or 
                curve_state.virtual_sol_reserves <= 0):
                print(f"❌ Reservas inválidas en la curve")
                return 0.0

            # Fórmula oficial de Pump.fun:
            # price = (virtual_sol_reserves / LAMPORTS_PER_SOL) / (virtual_token_reserves / 10^decimals)

            sol_reserves = curve_state.virtual_sol_reserves / self.LAMPORTS_PER_SOL
            token_reserves = curve_state.virtual_token_reserves / (10 ** self.PUMP_CURVE_TOKEN_DECIMALS)

            price_sol = sol_reserves / token_reserves

            return price_sol

        except Exception as e:
            print(f"❌ Error calculando precio: {e}")
            return 0.0

    def calculate_bonding_progress(self, curve_state: PumpCurveState) -> float:
        """
        Calcula el progreso de la bonding curve (0-100%)
        
        Args:
            curve_state: Estado de la bonding curve
            
        Returns:
            Progreso en porcentaje (0.0 - 100.0)
        """
        try:
            if curve_state.real_token_reserves >= self.INITIAL_REAL_TOKEN_RESERVES:
                return 0.0

            progress = (1 - (curve_state.real_token_reserves / self.INITIAL_REAL_TOKEN_RESERVES)) * 100

            return max(0.0, min(100.0, progress))

        except Exception as e:
            print(f"❌ Error calculando progreso: {e}")
            return 0.0

    async def get_sol_price_usd(self) -> float:
        """
        Obtiene el precio de SOL en USD usando Jupiter
        
        Returns:
            Precio de SOL en USD
        """
        try:
            if not self.http_session:
                print("❌ Sesión HTTP no inicializada")
                return 140.0

            url = "https://lite-api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112"

            async with self.http_session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    price = float(data['data']['So11111111111111111111111111111111111111112']['price'])
                    return price
                else:
                    print(f"⚠️ Error HTTP {response.status} obteniendo precio SOL")
                    return 140.0  # Precio de fallback

        except Exception as e:
            print(f"⚠️ Error obteniendo precio SOL: {e}")
            return 140.0  # Precio de emergencia

    def validate_token_address(self, token_address: str) -> bool:
        """
        Valida que una dirección de token sea válida
        
        Args:
            token_address: Dirección del token a validar
            
        Returns:
            True si es válida, False si no
        """
        try:
            # Verificar que sea una dirección válida de Solana
            PublicKey.from_string(token_address)

            # Verificar que tenga la longitud correcta (32 bytes = 44 caracteres en base58)
            if len(token_address) != 44:
                print(f"❌ Longitud de dirección inválida: {len(token_address)} (esperado: 44)")
                return False

            return True

        except Exception as e:
            print(f"❌ Dirección de token inválida: {e}")
            return False

    async def get_token_price(self, token_address: str) -> Optional[PumpTokenPrice]:
        """
        Obtiene el precio completo de un token de Pump.fun
        
        Args:
            token_address: Dirección del token
            
        Returns:
            Información completa del precio o None si hay error
        """
        try:
            print(f"🎯 Obteniendo precio de Pump.fun para: {token_address[:8]}...")

            # 0. Validar dirección del token
            if not self.validate_token_address(token_address):
                print(f"❌ Dirección de token inválida")
                return None

            # 1. Encontrar dirección de la bonding curve
            curve_address = self.find_pump_curve_address(token_address)
            if not curve_address:
                print(f"❌ No se pudo encontrar bonding curve")
                return None

            print(f"📍 Curve address: {curve_address[:8]}...")

            # 2. Obtener estado de la curve
            curve_state = await self.get_pump_curve_state(curve_address)
            if not curve_state:
                print(f"❌ No se pudo obtener estado de la curve")
                return None

            # 3. Calcular precio en SOL
            price_sol = self.calculate_pump_curve_price(curve_state)
            if price_sol <= 0:
                print(f"❌ Precio calculado inválido")
                return None

            # 4. Obtener precio de SOL en USD
            sol_price_usd = await self.get_sol_price_usd()
            price_usd = price_sol * sol_price_usd

            # 5. Calcular market cap (asumiendo 1B tokens)
            market_cap_usd = price_usd * 1_000_000_000

            # 6. Calcular progreso de bonding curve
            bonding_progress = self.calculate_bonding_progress(curve_state)

            # 7. Crear resultado
            token_price = PumpTokenPrice(
                token_address=token_address,
                price_sol=price_sol,
                price_usd=price_usd,
                market_cap_usd=market_cap_usd,
                bonding_progress=bonding_progress,
                curve_state=curve_state,
                timestamp=datetime.now()
            )

            print(f"✅ Precio obtenido desde Pump.fun!")
            print(f"   💰 Precio: {price_sol:.12f} SOL (${price_usd:.12f})")
            print(f"   📊 Market Cap: ${market_cap_usd:,.2f}")
            print(f"   📈 Progreso Bonding: {bonding_progress:.2f}%")

            return token_price

        except Exception as e:
            print(f"❌ Error obteniendo precio de Pump.fun: {e}")
            return None

    async def is_token_on_pump_curve(self, token_address: str) -> bool:
        """
        Verifica si un token está en una bonding curve de Pump.fun
        
        Args:
            token_address: Dirección del token
            
        Returns:
            True si está en bonding curve, False si no
        """
        try:
            curve_address = self.find_pump_curve_address(token_address)
            if not curve_address:
                return False

            curve_state = await self.get_pump_curve_state(curve_address)
            return curve_state is not None

        except Exception:
            return False

    async def get_curve_info(self, token_address: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene información detallada de la bonding curve
        
        Args:
            token_address: Dirección del token
            
        Returns:
            Información de la curve o None
        """
        try:
            curve_address = self.find_pump_curve_address(token_address)
            if not curve_address:
                return None

            curve_state = await self.get_pump_curve_state(curve_address)
            if not curve_state:
                return None

            price_sol = self.calculate_pump_curve_price(curve_state)
            bonding_progress = self.calculate_bonding_progress(curve_state)

            return {
                'curve_address': curve_address,
                'price_sol': price_sol,
                'bonding_progress': bonding_progress,
                'curve_complete': curve_state.complete,
                'virtual_reserves': {
                    'token': curve_state.virtual_token_reserves,
                    'sol': curve_state.virtual_sol_reserves
                },
                'real_reserves': {
                    'token': curve_state.real_token_reserves,
                    'sol': curve_state.real_sol_reserves
                },
                'total_supply': curve_state.token_total_supply
            }

        except Exception as e:
            print(f"❌ Error obteniendo info de curve: {e}")
            return None

    async def get_debug_info(self, token_address: str) -> Dict[str, Any]:
        """
        Obtiene información de debug detallada para un token
        
        Args:
            token_address: Dirección del token
            
        Returns:
            Información de debug completa
        """
        debug_info = {
            'token_address': token_address,
            'token_valid': False,
            'curve_address': None,
            'curve_exists': False,
            'curve_state': None,
            'price_calculation': None,
            'rpc_status': await self.get_rpc_status(),
            'errors': []
        }

        try:
            # 1. Validar token
            debug_info['token_valid'] = self.validate_token_address(token_address)
            if not debug_info['token_valid']:
                debug_info['errors'].append("Token address inválida")
                return debug_info

            # 2. Encontrar curve address
            curve_address = self.find_pump_curve_address(token_address)
            debug_info['curve_address'] = curve_address

            if not curve_address:
                debug_info['errors'].append("No se pudo encontrar bonding curve")
                return debug_info

            # 3. Verificar si la curve existe
            try:
                if not self.rpc_client:
                    debug_info['errors'].append("Cliente RPC no inicializado")
                    return debug_info

                curve_pubkey = PublicKey.from_string(curve_address)
                response = await self.rpc_client.get_account_info(curve_pubkey)
                debug_info['curve_exists'] = response.value is not None

                if not debug_info['curve_exists']:
                    debug_info['errors'].append("Bonding curve no existe en blockchain")
                    return debug_info

            except Exception as e:
                debug_info['errors'].append(f"Error verificando curve: {e}")
                return debug_info

            # 4. Obtener curve state
            curve_state = await self.get_pump_curve_state(curve_address)
            debug_info['curve_state'] = curve_state.to_dict() if curve_state else None

            if not curve_state:
                debug_info['errors'].append("No se pudo obtener estado de la curve")
                return debug_info

            # 5. Calcular precio
            price_sol = self.calculate_pump_curve_price(curve_state)
            sol_price_usd = await self.get_sol_price_usd()
            price_usd = price_sol * sol_price_usd

            debug_info['price_calculation'] = {
                'price_sol': price_sol,
                'sol_price_usd': sol_price_usd,
                'price_usd': price_usd,
                'bonding_progress': self.calculate_bonding_progress(curve_state)
            }

        except Exception as e:
            debug_info['errors'].append(f"Error inesperado: {e}")

        return debug_info

    def calculate_dynamic_curve_data(self, 
                                   bonding_curve_key: str,
                                   v_tokens_in_bonding_curve: float,
                                   v_sol_in_bonding_curve: float,
                                   market_cap_sol: float,
                                   token_decimals: int = 6) -> Dict[str, Any]:
        """
        Calcula datos dinámicamente a partir de parámetros específicos de bonding curve
        
        Args:
            bonding_curve_key: Dirección de la bonding curve
            v_tokens_in_bonding_curve: Tokens virtuales en la bonding curve
            v_sol_in_bonding_curve: SOL virtual en la bonding curve
            market_cap_sol: Market cap en SOL
            token_decimals: Decimales del token (default: 6 para Pump.fun)
            
        Returns:
            Diccionario con todos los cálculos dinámicos
        """
        try:
            print(f"🧮 Calculando datos dinámicos para curve: {bonding_curve_key[:8]}...")
            
            # Validar parámetros de entrada
            if v_tokens_in_bonding_curve <= 0 or v_sol_in_bonding_curve <= 0:
                raise ValueError("Los valores de tokens y SOL deben ser positivos")
            
            if market_cap_sol <= 0:
                raise ValueError("El market cap debe ser positivo")
            
            # 1. Calcular precio actual del token en SOL
            price_sol = v_sol_in_bonding_curve / v_tokens_in_bonding_curve
            
            # 2. Calcular supply total estimado
            # Market Cap = Price * Total Supply
            # Total Supply = Market Cap / Price
            total_supply_estimate = market_cap_sol / price_sol
            
            # 3. Calcular tokens en circulación (supply real)
            # Asumiendo que los tokens virtuales representan el supply en circulación
            circulating_supply = v_tokens_in_bonding_curve
            
            # 4. Calcular porcentaje de tokens en circulación
            circulation_percentage = (circulating_supply / total_supply_estimate) * 100
            
            # 5. Calcular progreso de bonding curve
            # Basado en la relación entre tokens virtuales y total supply
            bonding_progress = min(100.0, (circulating_supply / total_supply_estimate) * 100)
            
            # 6. Calcular valor de mercado en USD (asumiendo precio SOL = 140 USD)
            sol_price_usd = 140.0  # Valor por defecto, se puede actualizar dinámicamente
            market_cap_usd = market_cap_sol * sol_price_usd
            price_usd = price_sol * sol_price_usd
            
            # 7. Calcular métricas adicionales
            # Liquidez total en SOL
            total_liquidity_sol = v_sol_in_bonding_curve
            
            # Ratio de liquidez (SOL por token)
            liquidity_ratio = v_sol_in_bonding_curve / v_tokens_in_bonding_curve
            
            # Volatilidad estimada (basada en la relación de reservas)
            volatility_estimate = (v_sol_in_bonding_curve / v_tokens_in_bonding_curve) * 100
            
            # 8. Crear estado de curve simulado
            simulated_curve_state = PumpCurveState(
                virtual_token_reserves=int(v_tokens_in_bonding_curve * (10 ** token_decimals)),
                virtual_sol_reserves=int(v_sol_in_bonding_curve * self.LAMPORTS_PER_SOL),
                real_token_reserves=int(v_tokens_in_bonding_curve * (10 ** token_decimals)),
                real_sol_reserves=int(v_sol_in_bonding_curve * self.LAMPORTS_PER_SOL),
                token_total_supply=int(total_supply_estimate * (10 ** token_decimals)),
                complete=bonding_progress >= 100.0
            )
            
            # 9. Calcular proyecciones
            # Precio si se duplica la liquidez
            price_if_double_liquidity = (v_sol_in_bonding_curve * 2) / v_tokens_in_bonding_curve
            
            # Precio si se reduce la liquidez a la mitad
            price_if_half_liquidity = (v_sol_in_bonding_curve * 0.5) / v_tokens_in_bonding_curve
            
            # 10. Crear resultado completo
            result = {
                'bonding_curve_key': bonding_curve_key,
                'current_state': {
                    'virtual_tokens': v_tokens_in_bonding_curve,
                    'virtual_sol': v_sol_in_bonding_curve,
                    'price_sol': price_sol,
                    'price_usd': price_usd,
                    'market_cap_sol': market_cap_sol,
                    'market_cap_usd': market_cap_usd,
                    'total_supply_estimate': total_supply_estimate,
                    'circulating_supply': circulating_supply,
                    'circulation_percentage': circulation_percentage,
                    'bonding_progress': bonding_progress,
                    'liquidity_ratio': liquidity_ratio,
                    'volatility_estimate': volatility_estimate
                },
                'projections': {
                    'price_if_double_liquidity': price_if_double_liquidity,
                    'price_if_half_liquidity': price_if_half_liquidity,
                    'market_cap_if_double_liquidity': price_if_double_liquidity * total_supply_estimate,
                    'market_cap_if_half_liquidity': price_if_half_liquidity * total_supply_estimate
                },
                'simulated_curve_state': simulated_curve_state.to_dict(),
                'metrics': {
                    'price_change_if_double': ((price_if_double_liquidity - price_sol) / price_sol) * 100,
                    'price_change_if_half': ((price_if_half_liquidity - price_sol) / price_sol) * 100,
                    'liquidity_depth': total_liquidity_sol / price_sol,  # Cuántos tokens se pueden comprar/vender sin impacto significativo
                    'bonding_curve_efficiency': bonding_progress / 100.0  # Eficiencia de la bonding curve (0-1)
                },
                'timestamp': datetime.now().isoformat()
            }
            
            print(f"✅ Datos dinámicos calculados exitosamente!")
            print(f"   💰 Precio actual: {price_sol:.12f} SOL (${price_usd:.12f})")
            print(f"   📊 Market Cap: {market_cap_sol:.2f} SOL (${market_cap_usd:,.2f})")
            print(f"   📈 Bonding Progress: {bonding_progress:.2f}%")
            print(f"   🔄 Circulación: {circulation_percentage:.2f}%")
            print(f"   💧 Liquidez: {total_liquidity_sol:.4f} SOL")
            
            return result
            
        except Exception as e:
            print(f"❌ Error calculando datos dinámicos: {e}")
            return {
                'error': str(e),
                'bonding_curve_key': bonding_curve_key,
                'timestamp': datetime.now().isoformat()
            }

    async def calculate_dynamic_curve_data_with_sol_price(self,
                                                         bonding_curve_key: str,
                                                         v_tokens_in_bonding_curve: float,
                                                         v_sol_in_bonding_curve: float,
                                                         market_cap_sol: float,
                                                         token_decimals: int = 6) -> Dict[str, Any]:
        """
        Calcula datos dinámicos con precio actual de SOL desde Jupiter
        
        Args:
            bonding_curve_key: Dirección de la bonding curve
            v_tokens_in_bonding_curve: Tokens virtuales en la bonding curve
            v_sol_in_bonding_curve: SOL virtual en la bonding curve
            market_cap_sol: Market cap en SOL
            token_decimals: Decimales del token (default: 6 para Pump.fun)
            
        Returns:
            Diccionario con todos los cálculos dinámicos usando precio real de SOL
        """
        try:
            # Obtener precio actual de SOL
            sol_price_usd = await self.get_sol_price_usd()
            
            # Calcular datos base
            base_data = self.calculate_dynamic_curve_data(
                bonding_curve_key,
                v_tokens_in_bonding_curve,
                v_sol_in_bonding_curve,
                market_cap_sol,
                token_decimals
            )
            
            if 'error' in base_data:
                return base_data
            
            # Actualizar cálculos con precio real de SOL
            price_sol = base_data['current_state']['price_sol']
            price_usd = price_sol * sol_price_usd
            market_cap_usd = market_cap_sol * sol_price_usd
            
            # Actualizar valores en el resultado
            base_data['current_state']['price_usd'] = price_usd
            base_data['current_state']['market_cap_usd'] = market_cap_usd
            base_data['sol_price_usd'] = sol_price_usd
            
            # Recalcular proyecciones con precio real de SOL
            base_data['projections']['market_cap_usd_if_double_liquidity'] = (
                base_data['projections']['market_cap_if_double_liquidity'] * sol_price_usd
            )
            base_data['projections']['market_cap_usd_if_half_liquidity'] = (
                base_data['projections']['market_cap_if_half_liquidity'] * sol_price_usd
            )
            
            print(f"💎 Precio SOL actual: ${sol_price_usd:.2f}")
            print(f"💰 Market Cap USD actualizado: ${market_cap_usd:,.2f}")
            
            return base_data
            
        except Exception as e:
            print(f"❌ Error calculando datos dinámicos con precio SOL: {e}")
            return {
                'error': str(e),
                'bonding_curve_key': bonding_curve_key,
                'timestamp': datetime.now().isoformat()
            }

    async def get_token_price_sol_fast(self, 
                                     v_tokens_in_bonding_curve: float,
                                     v_sol_in_bonding_curve: float) -> Optional[float]:
        """
        Método ultra-rápido para calcular solo el precio del token en SOL
        Optimizado para copy trading - sin validaciones innecesarias
        
        Args:
            v_tokens_in_bonding_curve: Tokens virtuales en la bonding curve
            v_sol_in_bonding_curve: SOL virtual en la bonding curve
            
        Returns:
            Precio del token en SOL o None si hay error
        """
        try:
            # Validación mínima para evitar división por cero
            if v_tokens_in_bonding_curve <= 0 or v_sol_in_bonding_curve <= 0:
                return None
            
            # Cálculo directo del precio: SOL / Tokens
            price_sol = v_sol_in_bonding_curve / v_tokens_in_bonding_curve
            
            return price_sol
            
        except Exception:
            return None

    async def get_token_price_sol_with_cache(self,
                                           bonding_curve_key: str,
                                           v_tokens_in_bonding_curve: float,
                                           v_sol_in_bonding_curve: float,
                                           cache_duration_seconds: int = 5) -> Optional[float]:
        """
        Método optimizado con cache para evitar cálculos repetitivos
        Ideal para copy trading donde se consulta el mismo token frecuentemente
        
        Args:
            bonding_curve_key: Dirección de la bonding curve (para cache)
            v_tokens_in_bonding_curve: Tokens virtuales en la bonding curve
            v_sol_in_bonding_curve: SOL virtual en la bonding curve
            cache_duration_seconds: Duración del cache en segundos (default: 5s)
            
        Returns:
            Precio del token en SOL o None si hay error
        """
        try:
            # Cache simple en memoria
            if not hasattr(self, '_price_cache'):
                self._price_cache = {}
            
            current_time = datetime.now()
            cache_key = f"{bonding_curve_key}_{v_tokens_in_bonding_curve}_{v_sol_in_bonding_curve}"
            
            # Verificar cache
            if cache_key in self._price_cache:
                cached_data = self._price_cache[cache_key]
                time_diff = (current_time - cached_data['timestamp']).total_seconds()
                
                if time_diff < cache_duration_seconds:
                    return cached_data['price']
            
            # Calcular precio
            price_sol = await self.get_token_price_sol_fast(
                v_tokens_in_bonding_curve,
                v_sol_in_bonding_curve
            )
            
            if price_sol is not None:
                # Guardar en cache
                self._price_cache[cache_key] = {
                    'price': price_sol,
                    'timestamp': current_time
                }
                
                # Limpiar cache antiguo (más de 1 minuto)
                self._cleanup_price_cache()
            
            return price_sol
            
        except Exception:
            return None

    def _cleanup_price_cache(self):
        """Limpia el cache de precios eliminando entradas antiguas"""
        try:
            if not hasattr(self, '_price_cache'):
                return
            
            current_time = datetime.now()
            keys_to_remove = []
            
            for key, data in self._price_cache.items():
                time_diff = (current_time - data['timestamp']).total_seconds()
                if time_diff > 60:  # Eliminar entradas de más de 1 minuto
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self._price_cache[key]
                
        except Exception:
            pass  # Ignorar errores de limpieza

    async def get_multiple_token_prices_fast(self, 
                                           curve_data_list: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
        """
        Obtiene precios de múltiples tokens de forma ultra-rápida
        Optimizado para copy trading con múltiples tokens
        
        Args:
            curve_data_list: Lista de diccionarios con datos de curve
                           [{'bonding_curve_key': str, 'v_tokens': float, 'v_sol': float}, ...]
            
        Returns:
            Diccionario con precios: {bonding_curve_key: price_sol}
        """
        results = {}
        
        try:
            # Procesar todos los tokens de forma concurrente
            tasks = []
            for curve_data in curve_data_list:
                task = asyncio.create_task(
                    self.get_token_price_sol_with_cache(
                        bonding_curve_key=curve_data['bonding_curve_key'],
                        v_tokens_in_bonding_curve=curve_data['v_tokens'],
                        v_sol_in_bonding_curve=curve_data['v_sol']
                    )
                )
                tasks.append((curve_data['bonding_curve_key'], task))
            
            # Esperar todos los resultados
            for curve_key, task in tasks:
                try:
                    price = await task
                    results[curve_key] = price
                except Exception:
                    results[curve_key] = None
            
            return results
            
        except Exception:
            # Fallback: procesar secuencialmente si hay error
            for curve_data in curve_data_list:
                try:
                    price = await self.get_token_price_sol_fast(
                        curve_data['v_tokens'],
                        curve_data['v_sol']
                    )
                    results[curve_data['bonding_curve_key']] = price
                except Exception:
                    results[curve_data['bonding_curve_key']] = None
            
            return results

    async def get_multiple_token_prices(self, token_addresses: list[str]) -> Dict[str, Optional[PumpTokenPrice]]:
        """
        Obtiene precios de múltiples tokens de forma concurrente
        
        Args:
            token_addresses: Lista de direcciones de tokens
            
        Returns:
            Diccionario con precios de tokens
        """
        results = {}

        # Crear tareas para obtener precios concurrentemente
        tasks = []
        for token_address in token_addresses:
            task = asyncio.create_task(self.get_token_price(token_address))
            tasks.append((token_address, task))

        # Ejecutar todas las tareas
        for token_address, task in tasks:
            try:
                price = await task
                results[token_address] = price
            except Exception as e:
                print(f"❌ Error obteniendo precio para {token_address}: {e}")
                results[token_address] = None

        return results


# ============================================================================
# EJEMPLO DE USO ASÍNCRONO
# ============================================================================

async def example_usage():
    """
    Ejemplo de uso del PumpFunPriceFetcher asíncrono
    """
    # Lista de tokens de ejemplo (reemplazar con tokens reales)
    example_tokens = [
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
        "So11111111111111111111111111111111111111112",   # SOL
    ]

    print("🚀 Ejemplo de uso del PumpFunPriceFetcher Asíncrono")
    print("=" * 60)

    # Usar async with para gestión automática de conexiones
    async with PumpFunPriceFetcher() as fetcher:

        # 1. Verificar estado de conexión
        print("\n📡 Verificando conexión RPC...")
        status = await fetcher.get_rpc_status()
        if status['connected']:
            print(f"✅ Conectado al slot {status['current_slot']}")
        else:
            print(f"❌ Error de conexión: {status['error']}")
            return

        # 2. Obtener precio de un token individual
        print("\n💰 Obteniendo precio de un token...")
        token_address = example_tokens[0]
        price = await fetcher.get_token_price(token_address)

        if price:
            print(f"✅ Precio obtenido:")
            print(f"   Token: {price.token_address[:8]}...")
            print(f"   Precio: {price.price_sol:.12f} SOL")
            print(f"   USD: ${price.price_usd:.12f}")
            print(f"   Market Cap: ${price.market_cap_usd:,.2f}")
            print(f"   Bonding Progress: {price.bonding_progress:.2f}%")
        else:
            print(f"❌ No se pudo obtener precio para {token_address}")

        # 3. Obtener precios de múltiples tokens concurrentemente
        print("\n🔄 Obteniendo precios de múltiples tokens...")
        prices = await fetcher.get_multiple_token_prices(example_tokens)

        for token_address, price in prices.items():
            if price:
                print(f"✅ {token_address[:8]}...: {price.price_sol:.12f} SOL")
            else:
                print(f"❌ {token_address[:8]}...: Error")

        # 4. Obtener información de debug
        print("\n🔍 Información de debug...")
        debug_info = await fetcher.get_debug_info(token_address)

        print(f"Token válido: {debug_info['token_valid']}")
        print(f"Curve existe: {debug_info['curve_exists']}")
        if debug_info['errors']:
            print(f"Errores: {debug_info['errors']}")

        # 5. Verificar si tokens están en bonding curve
        print("\n🔗 Verificando bonding curves...")
        for token_address in example_tokens:
            is_on_curve = await fetcher.is_token_on_pump_curve(token_address)
            print(f"{token_address[:8]}...: {'✅ En curve' if is_on_curve else '❌ No en curve'}")


async def example_dynamic_calculation():
    """
    Ejemplo de uso de los métodos de cálculo dinámico
    """
    print("\n" + "=" * 60)
    print("🧮 EJEMPLO DE CÁLCULO DINÁMICO")
    print("=" * 60)

    # Datos de ejemplo proporcionados por el usuario
    example_data = {
        'bonding_curve_key': 'FWvHNjLaPUf9UKkz57RuLAEyhHtf9QhnyoVfvCZvTs4B',
        'v_tokens_in_bonding_curve': 1072964234.525516,
        'v_sol_in_bonding_curve': 30.000999999999994,
        'market_cap_sol': 27.960857440198808
    }

    # Crear instancia del fetcher
    fetcher = PumpFunPriceFetcher()

    # 1. Cálculo dinámico básico (sin conexión RPC)
    print("\n📊 Cálculo dinámico básico...")
    basic_result = fetcher.calculate_dynamic_curve_data(
        bonding_curve_key=example_data['bonding_curve_key'],
        v_tokens_in_bonding_curve=example_data['v_tokens_in_bonding_curve'],
        v_sol_in_bonding_curve=example_data['v_sol_in_bonding_curve'],
        market_cap_sol=example_data['market_cap_sol']
    )

    if 'error' not in basic_result:
        current_state = basic_result['current_state']
        print(f"✅ Resultados básicos:")
        print(f"   💰 Precio: {current_state['price_sol']:.12f} SOL")
        print(f"   📊 Market Cap: {current_state['market_cap_sol']:.2f} SOL")
        print(f"   📈 Bonding Progress: {current_state['bonding_progress']:.2f}%")
        print(f"   🔄 Circulación: {current_state['circulation_percentage']:.2f}%")
        print(f"   💧 Liquidez: {current_state['liquidity_ratio']:.8f} SOL/token")

        # Mostrar proyecciones
        projections = basic_result['projections']
        print(f"\n🔮 Proyecciones:")
        print(f"   📈 Precio si 2x liquidez: {projections['price_if_double_liquidity']:.12f} SOL")
        print(f"   📉 Precio si 0.5x liquidez: {projections['price_if_half_liquidity']:.12f} SOL")
        print(f"   💹 Cambio % si 2x: {basic_result['metrics']['price_change_if_double']:.2f}%")
        print(f"   📉 Cambio % si 0.5x: {basic_result['metrics']['price_change_if_half']:.2f}%")

    # 2. Cálculo dinámico con precio real de SOL
    print("\n💎 Cálculo dinámico con precio real de SOL...")
    async with PumpFunPriceFetcher() as fetcher:
        real_sol_result = await fetcher.calculate_dynamic_curve_data_with_sol_price(
            bonding_curve_key=example_data['bonding_curve_key'],
            v_tokens_in_bonding_curve=example_data['v_tokens_in_bonding_curve'],
            v_sol_in_bonding_curve=example_data['v_sol_in_bonding_curve'],
            market_cap_sol=example_data['market_cap_sol']
        )

        if 'error' not in real_sol_result:
            current_state = real_sol_result['current_state']
            print(f"✅ Resultados con precio real de SOL:")
            print(f"   💰 Precio: {current_state['price_sol']:.12f} SOL (${current_state['price_usd']:.12f})")
            print(f"   📊 Market Cap: {current_state['market_cap_sol']:.2f} SOL (${current_state['market_cap_usd']:,.2f})")
            print(f"   💎 Precio SOL: ${real_sol_result['sol_price_usd']:.2f}")

    # 3. Análisis de métricas avanzadas
    if 'error' not in basic_result:
        metrics = basic_result['metrics']
        print(f"\n📊 Métricas avanzadas:")
        print(f"   🎯 Eficiencia bonding curve: {metrics['bonding_curve_efficiency']:.2%}")
        print(f"   💧 Profundidad de liquidez: {metrics['liquidity_depth']:,.0f} tokens")
        print(f"   📈 Volatilidad estimada: {basic_result['current_state']['volatility_estimate']:.2f}%")

    # 4. Simulación de diferentes escenarios
    print(f"\n🎲 Simulación de escenarios...")
    scenarios = [
        {'name': 'Liquidez +50%', 'multiplier': 1.5},
        {'name': 'Liquidez +100%', 'multiplier': 2.0},
        {'name': 'Liquidez -25%', 'multiplier': 0.75},
        {'name': 'Liquidez -50%', 'multiplier': 0.5}
    ]

    for scenario in scenarios:
        new_sol = example_data['v_sol_in_bonding_curve'] * scenario['multiplier']
        new_price = new_sol / example_data['v_tokens_in_bonding_curve']
        price_change = ((new_price - basic_result['current_state']['price_sol']) / basic_result['current_state']['price_sol']) * 100
        
        print(f"   {scenario['name']}: {new_price:.12f} SOL ({price_change:+.2f}%)")


async def example_copy_trading_optimized():
    """
    Ejemplo de uso optimizado para copy trading
    """
    print("\n" + "=" * 60)
    print("⚡ EJEMPLO OPTIMIZADO PARA COPY TRADING")
    print("=" * 60)

    # Datos de ejemplo para múltiples tokens (simulando datos de copy trading)
    tokens_data = [
        {
            'bonding_curve_key': 'FWvHNjLaPUf9UKkz57RuLAEyhHtf9QhnyoVfvCZvTs4B',
            'v_tokens': 1072964234.525516,
            'v_sol': 30.000999999999994
        },
        {
            'bonding_curve_key': 'ABC1234567890DEF4567890GHI7890123456789012',
            'v_tokens': 500000000.0,
            'v_sol': 15.5
        },
        {
            'bonding_curve_key': 'XYZ9876543210ABC123456789DEF4567890123456',
            'v_tokens': 2000000000.0,
            'v_sol': 45.25
        }
    ]

    print("\n🚀 Iniciando cálculos optimizados para copy trading...")

    # 1. Cálculo ultra-rápido individual
    print("\n⚡ Cálculo ultra-rápido individual...")
    fetcher = PumpFunPriceFetcher()
    
    start_time = datetime.now()
    for token_data in tokens_data:
        price = await fetcher.get_token_price_sol_fast(
            token_data['v_tokens'],
            token_data['v_sol']
        )
        print(f"   {token_data['bonding_curve_key'][:8]}...: {price:.12f} SOL")
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() * 1000
    print(f"   ⏱️ Tiempo total: {duration:.2f}ms")

    # 2. Cálculo con cache (simulando múltiples consultas)
    print("\n💾 Cálculo con cache (simulando consultas repetitivas)...")
    
    start_time = datetime.now()
    for _ in range(3):  # Simular 3 consultas del mismo token
        for token_data in tokens_data:
            price = await fetcher.get_token_price_sol_with_cache(
                bonding_curve_key=token_data['bonding_curve_key'],
                v_tokens_in_bonding_curve=token_data['v_tokens'],
                v_sol_in_bonding_curve=token_data['v_sol']
            )
            print(f"   {token_data['bonding_curve_key'][:8]}...: {price:.12f} SOL (cached)")
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() * 1000
    print(f"   ⏱️ Tiempo total con cache: {duration:.2f}ms")

    # 3. Cálculo concurrente de múltiples tokens
    print("\n🔄 Cálculo concurrente de múltiples tokens...")
    
    start_time = datetime.now()
    prices = await fetcher.get_multiple_token_prices_fast(tokens_data)
    
    for curve_key, price in prices.items():
        if price is not None:
            print(f"   {curve_key[:8]}...: {price:.12f} SOL")
        else:
            print(f"   {curve_key[:8]}...: Error")
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() * 1000
    print(f"   ⏱️ Tiempo total concurrente: {duration:.2f}ms")

    # 4. Benchmark de rendimiento
    print("\n📊 Benchmark de rendimiento...")
    
    # Test de velocidad con 100 cálculos
    iterations = 100
    start_time = datetime.now()
    
    for _ in range(iterations):
        await fetcher.get_token_price_sol_fast(
            tokens_data[0]['v_tokens'],
            tokens_data[0]['v_sol']
        )
    
    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds() * 1000
    avg_duration = total_duration / iterations
    
    print(f"   🔥 {iterations} cálculos en {total_duration:.2f}ms")
    print(f"   ⚡ Promedio por cálculo: {avg_duration:.4f}ms")
    print(f"   🚀 Velocidad: {iterations / (total_duration / 1000):.0f} cálculos/segundo")

    # 5. Información del cache
    if hasattr(fetcher, '_price_cache'):
        cache_size = len(fetcher._price_cache)
        print(f"\n💾 Estado del cache:")
        print(f"   📦 Entradas en cache: {cache_size}")
        print(f"   🗑️ Limpiando cache...")
        fetcher._cleanup_price_cache()
        print(f"   📦 Entradas después de limpieza: {len(fetcher._price_cache)}")


if __name__ == "__main__":
    # Ejecutar ejemplos
    asyncio.run(example_usage())
    asyncio.run(example_dynamic_calculation())
    asyncio.run(example_copy_trading_optimized())
