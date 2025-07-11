"""
Cliente HTTP Asíncrono para BitQuery - Optimizado para Notebooks

Solo contiene lo esencial que se usa en BITQUERY_TESTS.ipynb
Completamente asíncrono para mejor rendimiento
"""

from typing import Dict, Any, List
import aiohttp
import asyncio
import os
import logging

from .queries import BitQueryQueries

logger = logging.getLogger(__name__)


class BitQueryHTTPClient:
    """Cliente HTTP asíncrono - optimizado para notebooks"""

    EAP_URL = "https://streaming.bitquery.io/eap"
    OAUTH_URL = "https://oauth2.bitquery.io/oauth2/token"

    def __init__(self, access_token: str = None, client_id: str = None, client_secret: str = None):
        """Inicializa el cliente HTTP asíncrono"""
        self.access_token = access_token or os.getenv("BITQUERY_ACCESS_TOKEN")
        self.client_id = client_id or os.getenv("BITQUERY_CLIENT_ID") 
        self.client_secret = client_secret or os.getenv("BITQUERY_CLIENT_SECRET")
        self.session = None

        if not self.access_token and not (self.client_id and self.client_secret):
            raise ValueError("Se requiere access_token o credenciales OAuth2")

    async def __aenter__(self):
        """Context manager para sesión aiohttp"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cierra la sesión aiohttp"""
        if self.session:
            await self.session.close()

    async def generate_token(self) -> str:
        """Genera un nuevo token OAuth2 de forma asíncrona"""
        if not self.client_id or not self.client_secret:
            raise ValueError("Se requieren credenciales OAuth2")

        payload = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'api'
        }

        session = self.session or aiohttp.ClientSession()
        try:
            async with session.post(self.OAUTH_URL, data=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    self.access_token = result['access_token']
                    return self.access_token
                else:
                    error_text = await response.text()
                    raise Exception(f"Error generando token: {response.status} - {error_text}")
        finally:
            if not self.session:  # Solo cerrar si creamos la sesión aquí
                await session.close()

    async def execute_query(self, query: str) -> Dict[str, Any]:
        """Ejecuta una query GraphQL de forma asíncrona"""
        if not self.access_token:
            await self.generate_token()

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }

        payload = {"query": query}

        session = self.session or aiohttp.ClientSession()
        try:
            async with session.post(self.EAP_URL, json=payload, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    if "errors" in result:
                        logger.warning(f"GraphQL errors: {result['errors']}")
                    return result
                elif response.status == 401:
                    # Token expirado, regenerar
                    await self.generate_token()
                    headers['Authorization'] = f'Bearer {self.access_token}'
                    async with session.post(self.EAP_URL, json=payload, headers=headers) as retry_response:
                        return await retry_response.json()
                else:
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")
        finally:
            if not self.session:  # Solo cerrar si creamos la sesión aquí
                await session.close()

    # === MÉTODOS PRINCIPALES - USADOS EN NOTEBOOKS ===

    async def get_top_traders_for_token(self, token_mint: str, limit: int = 50) -> List[Dict]:
        """Top traders de un token específico"""
        query = BitQueryQueries.get_top_traders_for_token(token_mint, limit)
        result = await self.execute_query(query)
        return result.get("data", {}).get("Solana", {}).get("DEXTradeByTokens", [])

    async def get_pumpfun_top_traders_filtered(
        self, 
        limit: int = 5,
        time_from: str = None,
        time_to: str = None
    ) -> List[Dict]:
        """Top traders de Pump.fun con filtros - USADO EN BITQUERY_TESTS.ipynb ✅"""
        query = BitQueryQueries.get_pumpfun_top_traders_filtered(limit, time_from, time_to)
        result = await self.execute_query(query)
        return result.get("data", {}).get("Solana", {}).get("DEXTradeByTokens", [])

    async def get_trader_buys(self, trader_address: str, limit: int = 100) -> List[Dict]:
        """Compras de un trader específico"""
        query = BitQueryQueries.get_trader_buys(trader_address, limit)
        result = await self.execute_query(query)
        return result.get("data", {}).get("Solana", {}).get("DEXTrades", [])

    async def get_trader_sells(self, trader_address: str, limit: int = 100) -> List[Dict]:
        """Ventas de un trader específico"""
        query = BitQueryQueries.get_trader_sells(trader_address, limit)
        result = await self.execute_query(query)
        return result.get("data", {}).get("Solana", {}).get("DEXTrades", [])

    # === MÉTODOS DE ANÁLISIS - USADOS EN NOTEBOOKS ===

    async def analyze_trader_performance(self, trader_address: str, token_mint: str = None) -> Dict[str, Any]:
        """
        Análisis completo de performance de un trader - USADO EN NOTEBOOKS ✅
        """
        try:
            # Obtener compras y ventas de forma asíncrona
            buys, sells = await asyncio.gather(
                self.get_trader_buys(trader_address, 100),
                self.get_trader_sells(trader_address, 100)
            )

            # Si se especifica un token, filtrar
            if token_mint:
                buys = [b for b in buys if b["Trade"]["Buy"]["Currency"]["MintAddress"] == token_mint]
                sells = [s for s in sells if s["Trade"]["Sell"]["Currency"]["MintAddress"] == token_mint]

            # Calcular métricas
            total_buys = len(buys)
            total_sells = len(sells)

            buy_volume = sum(float(trade["Trade"]["Buy"]["AmountInUSD"] or 0) for trade in buys)
            sell_volume = sum(float(trade["Trade"]["Sell"]["AmountInUSD"] or 0) for trade in sells)

            return {
                "trader_address": trader_address,
                "total_trades": total_buys + total_sells,
                "total_buys": total_buys,
                "total_sells": total_sells,
                "buy_volume_usd": buy_volume,
                "sell_volume_usd": sell_volume,
                "net_balance": sell_volume - buy_volume,
                "buy_sell_ratio": total_buys / total_sells if total_sells > 0 else float('inf'),
                "recent_buys": buys[:5],
                "recent_sells": sells[:5]
            }

        except Exception as e:
            logger.error(f"Error analizando trader: {e}")
            return {"error": str(e)}

    async def analyze_token_activity(self, token_mint: str) -> Dict[str, Any]:
        """
        Análisis completo de actividad de un token - USADO EN NOTEBOOKS ✅
        """
        try:
            # Obtener traders del token
            traders = await self.get_top_traders_for_token(token_mint, 100)

            if not traders:
                return {"error": "No se encontraron datos para el token"}

            # Calcular métricas agregadas
            total_volume = sum(float(trader.get("volumeUsd", 0)) for trader in traders)
            total_trades = sum(int(trader.get("trades", 0)) for trader in traders)
            unique_traders = len(traders)

            # Calcular volúmenes de compra y venta
            buy_volume = sum(float(trader.get("buyVolumeUsd", 0)) for trader in traders)
            sell_volume = sum(float(trader.get("sellVolumeUsd", 0)) for trader in traders)

            return {
                "token_mint": token_mint,
                "total_volume_usd": total_volume,
                "buy_volume_usd": buy_volume,
                "sell_volume_usd": sell_volume,
                "net_volume": buy_volume - sell_volume,
                "unique_traders": unique_traders,
                "total_trades": total_trades,
                "avg_trade_size": total_volume / total_trades if total_trades > 0 else 0,
                "top_traders": traders[:10]  # Top 10 traders
            }

        except Exception as e:
            logger.error(f"Error analizando token: {e}")
            return {"error": str(e)}
