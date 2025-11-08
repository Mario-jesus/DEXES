# -*- coding: utf-8 -*-
"""
Cliente Asíncrono para Moralis API - Obtención de Precios de Tokens

Permite obtener precios en USD y nativos de tokens en Solana usando la API de Moralis.
Optimizado para uso en notebooks y aplicaciones asíncronas.
"""
import asyncio, aiohttp, logging, os
from typing import Dict, Any, Optional
from decimal import getcontext, Decimal

# Configurar precisión para Decimal
getcontext().prec = 26

logger = logging.getLogger(__name__)


class MoralisApiError(Exception):
    """Excepción base para errores de la API de Moralis"""
    pass


class MoralisAuthError(MoralisApiError):
    """Error de autenticación con Moralis API"""
    pass


class MoralisNotFoundError(MoralisApiError):
    """Token no encontrado en Moralis API"""
    pass


class MoralisPriceClient:
    """Cliente HTTP asíncrono para obtener precios de tokens desde Moralis API"""

    BASE_URL = "https://solana-gateway.moralis.io"

    def __init__(self, api_key: Optional[str] = None, network: str = "mainnet"):
        """
        Inicializa el cliente de Moralis.

        Args:
            api_key: API key de Moralis. Si no se proporciona, se obtiene de MORALIS_API_KEY env var
            network: Red de Solana (mainnet o devnet). Por defecto: mainnet
        """
        self.api_key = api_key or os.getenv("MORALIS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Se requiere una API key de Moralis. "
                "Proporciona api_key o configura la variable de entorno MORALIS_API_KEY"
            )

        self.network = network
        self.session: Optional[aiohttp.ClientSession] = None
        logger.debug(f"Cliente Moralis inicializado para red: {network}")

    async def __aenter__(self):
        """Context manager para sesión aiohttp"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cierra la sesión aiohttp"""
        await self.stop()

    async def start(self):
        """Inicia la sesión aiohttp"""
        self.session = aiohttp.ClientSession()

    async def stop(self):
        """Cierra la sesión aiohttp"""
        if self.session:
            await self.session.close()

    def _get_headers(self) -> Dict[str, str]:
        """Construye los headers necesarios para las peticiones"""
        if not self.api_key:
            raise ValueError("API key no configurada")
        return {
            "Accept": "application/json",
            "X-API-Key": self.api_key
        }

    async def _make_request(self, endpoint: str) -> Dict[str, Any]:
        """
        Realiza una petición GET a la API de Moralis.

        Args:
            endpoint: Endpoint relativo de la API

        Returns:
            Respuesta JSON de la API

        Raises:
            MoralisAuthError: Si hay error de autenticación
            MoralisNotFoundError: Si el recurso no se encuentra
            MoralisApiError: Para otros errores de la API
        """
        url = f"{self.BASE_URL}{endpoint}"
        headers = self._get_headers()

        session = self.session or aiohttp.ClientSession()
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    error_text = await response.text()
                    logger.error(f"Error de autenticación con Moralis API: {error_text}")
                    raise MoralisAuthError(f"API key inválida o expirada: {error_text}")
                elif response.status == 404:
                    error_text = await response.text()
                    logger.warning(f"Recurso no encontrado en Moralis: {error_text}")
                    raise MoralisNotFoundError(f"Token no encontrado: {error_text}")
                else:
                    error_text = await response.text()
                    logger.error(f"Error en petición a Moralis: HTTP {response.status} - {error_text}")
                    raise MoralisApiError(f"HTTP {response.status}: {error_text}")
        finally:
            if not self.session:
                await session.close()

    async def get_token_price(self, token_address: str) -> Dict[str, Any]:
        """
        Obtiene el precio completo y metadatos de un token en la red de Solana.

        Args:
            token_address: Dirección del contrato del token en Solana

        Returns:
            Diccionario con información completa del token:
            {
                'token_address': str,
                'pair_address': str,
                'exchange_name': str,
                'exchange_address': str,
                'usd_price': str,              # Precio actual en USD
                'usd_price_24h': str,          # Precio hace 24h
                'usd_change_24h': str,         # Cambio en USD (24h)
                'percent_change_24h': str,     # Cambio porcentual (24h)
                'name': str,                   # Nombre del token
                'symbol': str,                 # Símbolo del token
                'logo': str,                   # URL del logo
                'is_verified': bool,           # Si el contrato está verificado
                'native_price': {              # Precio en moneda nativa
                    'value': str,
                    'symbol': str,
                    'name': str,
                    'decimals': int
                }
            }

        Raises:
            MoralisAuthError: Si hay error de autenticación
            MoralisNotFoundError: Si el token no existe o no tiene precio
            MoralisApiError: Para otros errores de la API
        """
        endpoint = f"/token/{self.network}/{token_address}/price"
        logger.debug(f"Obteniendo precio para token: {token_address}")

        try:
            data = await self._make_request(endpoint)

            # Extraer y formatear datos como strings para mantener precisión
            result = {
                'token_address': data.get('tokenAddress', token_address),
                'pair_address': data.get('pairAddress'),
                'exchange_name': data.get('exchangeName'),
                'exchange_address': data.get('exchangeAddress'),
                'usd_price': str(data.get('usdPrice', '0')),
                'usd_price_24h': str(data.get('usdPrice24h', '0')),
                'usd_change_24h': str(data.get('usdPrice24hrUsdChange', '0')),
                'percent_change_24h': str(data.get('usdPrice24hrPercentChange', '0')),
                'name': data.get('name', ''),
                'symbol': data.get('symbol', ''),
                'logo': data.get('logo', ''),
                'is_verified': data.get('isVerifiedContract', False),
                'native_price': None
            }

            # Procesar precio nativo si existe
            if 'nativePrice' in data and data['nativePrice']:
                native = data['nativePrice']
                result['native_price'] = {
                    'value': str(native.get('value', '0')),
                    'symbol': native.get('symbol'),
                    'name': native.get('name'),
                    'decimals': native.get('decimals', 9)
                }

            logger.info(
                f"Precio obtenido para {result['symbol']} ({token_address[:8]}...): "
                f"${result['usd_price']} USD ({result['percent_change_24h']}% 24h)"
            )
            return result

        except (MoralisAuthError, MoralisNotFoundError):
            raise
        except Exception as e:
            logger.error(f"Error inesperado al obtener precio de {token_address}: {e}")
            raise MoralisApiError(f"Error inesperado: {e}")

    async def get_token_price_usd(self, token_address: str) -> str:
        """
        Obtiene solo el precio en USD de un token.

        Args:
            token_address: Dirección del contrato del token en Solana

        Returns:
            Precio en USD como string

        Raises:
            MoralisAuthError: Si hay error de autenticación
            MoralisNotFoundError: Si el token no existe
            MoralisApiError: Para otros errores de la API
        """
        price_data = await self.get_token_price(token_address)
        return price_data['usd_price']

    async def get_token_metadata(self, token_address: str) -> Dict[str, Any]:
        """
        Obtiene los metadatos de un token (nombre, símbolo, logo, verificación).

        Args:
            token_address: Dirección del contrato del token en Solana

        Returns:
            Diccionario con metadatos:
            {
                'token_address': str,
                'name': str,
                'symbol': str,
                'logo': str,
                'is_verified': bool
            }

        Raises:
            MoralisAuthError: Si hay error de autenticación
            MoralisNotFoundError: Si el token no existe
            MoralisApiError: Para otros errores de la API
        """
        price_data = await self.get_token_price(token_address)
        return {
            'token_address': price_data['token_address'],
            'name': price_data['name'],
            'symbol': price_data['symbol'],
            'logo': price_data['logo'],
            'is_verified': price_data['is_verified']
        }

    async def get_price_change_24h(self, token_address: str) -> Dict[str, Any]:
        """
        Obtiene el cambio de precio en las últimas 24 horas.

        Args:
            token_address: Dirección del contrato del token en Solana

        Returns:
            Diccionario con cambios de precio:
            {
                'symbol': str,
                'current_price': str,          # Precio actual en USD
                'price_24h_ago': str,          # Precio hace 24h
                'change_usd': str,             # Cambio absoluto en USD
                'change_percent': str,         # Cambio porcentual
                'is_positive': bool            # True si subió, False si bajó
            }

        Raises:
            MoralisAuthError: Si hay error de autenticación
            MoralisNotFoundError: Si el token no existe
            MoralisApiError: Para otros errores de la API
        """
        price_data = await self.get_token_price(token_address)

        change_percent = Decimal(price_data['percent_change_24h'])

        return {
            'symbol': price_data['symbol'],
            'current_price': price_data['usd_price'],
            'price_24h_ago': price_data['usd_price_24h'],
            'change_usd': price_data['usd_change_24h'],
            'change_percent': price_data['percent_change_24h'],
            'is_positive': change_percent >= 0
        }

    async def get_token_summary(self, token_address: str) -> Dict[str, Any]:
        """
        Obtiene un resumen completo del token con toda la información relevante.

        Args:
            token_address: Dirección del contrato del token en Solana

        Returns:
            Diccionario con resumen completo del token incluyendo:
            - Información básica (nombre, símbolo, logo, verificado)
            - Precios actuales y históricos (24h)
            - Exchange donde se negocia
            - Precio nativo

        Raises:
            MoralisAuthError: Si hay error de autenticación
            MoralisNotFoundError: Si el token no existe
            MoralisApiError: Para otros errores de la API
        """
        return await self.get_token_price(token_address)

    async def get_multiple_token_prices(self, token_addresses: list[str]) -> Dict[str, Dict[str, Any]]:
        """
        Obtiene precios de múltiples tokens de forma concurrente.

        Args:
            token_addresses: Lista de direcciones de tokens

        Returns:
            Diccionario con token_address como clave y datos de precio como valor.
            Si un token falla, se incluye una entrada con error.

        Example:
            {
                'token1...': {'usd_price': '1.23', 'exchange_name': 'Raydium', ...},
                'token2...': {'error': 'Token no encontrado'}
            }
        """
        logger.debug(f"Obteniendo precios para {len(token_addresses)} tokens")

        async def fetch_with_error_handling(token_addr: str) -> tuple[str, Dict[str, Any]]:
            """Fetch con manejo de errores para mantener el batch completo"""
            try:
                price_data = await self.get_token_price(token_addr)
                return token_addr, price_data
            except MoralisNotFoundError:
                return token_addr, {'error': 'Token no encontrado'}
            except MoralisAuthError as e:
                return token_addr, {'error': f'Error de autenticación: {str(e)}'}
            except Exception as e:
                logger.warning(f"Error obteniendo precio de {token_addr}: {e}")
                return token_addr, {'error': str(e)}

        # Ejecutar todas las peticiones concurrentemente
        results = await asyncio.gather(
            *[fetch_with_error_handling(addr) for addr in token_addresses],
            return_exceptions=False
        )

        # Convertir lista de tuplas a diccionario
        return dict(results)

    async def get_price_changes_analysis(self, token_addresses: list[str]) -> Dict[str, Any]:
        """
        Analiza cambios de precio de múltiples tokens y proporciona estadísticas.

        Args:
            token_addresses: Lista de direcciones de tokens

        Returns:
            Diccionario con análisis:
            {
                'top_gainers': [{'symbol': str, 'change_percent': str, ...}, ...],
                'top_losers': [{'symbol': str, 'change_percent': str, ...}, ...],
                'total_tokens': int,
                'tokens_up': int,
                'tokens_down': int,
                'tokens_unchanged': int
            }
        """
        logger.debug(f"Analizando cambios de precio para {len(token_addresses)} tokens")
        prices = await self.get_multiple_token_prices(token_addresses)

        # Filtrar tokens con datos válidos
        valid_tokens = []
        for addr, data in prices.items():
            if 'error' not in data:
                change = Decimal(data.get('percent_change_24h', '0'))
                valid_tokens.append({
                    'token_address': addr,
                    'symbol': data.get('symbol', 'Unknown'),
                    'name': data.get('name', 'Unknown'),
                    'current_price': data.get('usd_price', '0'),
                    'change_percent': data.get('percent_change_24h', '0'),
                    'change_usd': data.get('usd_change_24h', '0'),
                    'change_value': change
                })

        # Ordenar por cambio porcentual
        sorted_tokens = sorted(valid_tokens, key=lambda x: x['change_value'], reverse=True)

        # Contar tokens por dirección de cambio
        tokens_up = sum(1 for t in valid_tokens if t['change_value'] > 0)
        tokens_down = sum(1 for t in valid_tokens if t['change_value'] < 0)
        tokens_unchanged = sum(1 for t in valid_tokens if t['change_value'] == 0)

        # Preparar resultado sin el campo auxiliar 'change_value'
        for token in sorted_tokens:
            del token['change_value']

        return {
            'top_gainers': sorted_tokens[:10],  # Top 10 que más subieron
            'top_losers': sorted_tokens[-10:],  # Top 10 que más bajaron
            'total_tokens': len(valid_tokens),
            'tokens_up': tokens_up,
            'tokens_down': tokens_down,
            'tokens_unchanged': tokens_unchanged
        }

    async def filter_verified_tokens(self, token_addresses: list[str]) -> list[Dict[str, Any]]:
        """
        Filtra y retorna solo los tokens verificados de una lista.

        Args:
            token_addresses: Lista de direcciones de tokens

        Returns:
            Lista de diccionarios con información de tokens verificados:
            [
                {
                    'token_address': str,
                    'name': str,
                    'symbol': str,
                    'usd_price': str,
                    'logo': str
                },
                ...
            ]
        """
        logger.debug(f"Filtrando tokens verificados de {len(token_addresses)} tokens")
        prices = await self.get_multiple_token_prices(token_addresses)

        verified_tokens = []
        for addr, data in prices.items():
            if 'error' not in data and data.get('is_verified', False):
                verified_tokens.append({
                    'token_address': addr,
                    'name': data.get('name', ''),
                    'symbol': data.get('symbol', ''),
                    'usd_price': data.get('usd_price', '0'),
                    'logo': data.get('logo', '')
                })

        logger.info(f"Encontrados {len(verified_tokens)} tokens verificados de {len(token_addresses)}")
        return verified_tokens

    async def get_tokens_by_exchange(self, token_addresses: list[str]) -> Dict[str, list]:
        """
        Agrupa tokens por el exchange donde se negocian.

        Args:
            token_addresses: Lista de direcciones de tokens

        Returns:
            Diccionario con exchanges como claves y listas de tokens como valores:
            {
                'Raydium': [{'symbol': 'SRM', 'token_address': '...', 'usd_price': '...'}, ...],
                'Meteora DLMM': [...],
                ...
            }
        """
        logger.debug(f"Agrupando {len(token_addresses)} tokens por exchange")
        prices = await self.get_multiple_token_prices(token_addresses)

        exchanges = {}
        for addr, data in prices.items():
            if 'error' not in data:
                exchange = data.get('exchange_name', 'Unknown')

                if exchange not in exchanges:
                    exchanges[exchange] = []

                exchanges[exchange].append({
                    'token_address': addr,
                    'symbol': data.get('symbol', 'Unknown'),
                    'name': data.get('name', 'Unknown'),
                    'usd_price': data.get('usd_price', '0'),
                    'pair_address': data.get('pair_address', '')
                })

        logger.info(f"Tokens encontrados en {len(exchanges)} exchanges diferentes")
        return exchanges

    def get_api_key_masked(self) -> str:
        """Retorna la API key parcialmente oculta para logging seguro"""
        if not self.api_key:
            return "None"
        return f"{self.api_key[:8]}...{self.api_key[-4:]}"
