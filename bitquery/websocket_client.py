"""
Cliente WebSocket para BitQuery - Optimizado para Tiempo Real

Basado en lo usado en BITQUERY_WEBSOCKETS.ipynb con WebSocket real
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Dict, Callable, Optional
import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from .queries import BitQuerySubscriptions

logger = logging.getLogger(__name__)


class BitQueryWebSocketClient:
    """Cliente WebSocket real optimizado para tiempo real"""

    WS_URL = "wss://streaming.bitquery.io/eap"
    OAUTH_URL = "https://oauth2.bitquery.io/oauth2/token"

    def __init__(self, access_token: str = None, client_id: str = None, client_secret: str = None, debug: bool = False):
        """
        Inicializa el cliente WebSocket
        
        Args:
            access_token: Token OAuth de BitQuery
            client_id: Client ID para OAuth2
            client_secret: Client Secret para OAuth2
            debug: Activar modo debug
        """
        self.access_token = access_token or os.getenv("BITQUERY_ACCESS_TOKEN")
        self.client_id = client_id or os.getenv("BITQUERY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("BITQUERY_CLIENT_SECRET")
        self.debug = debug

        self.websocket = None
        self.active_subscriptions = {}
        self.subscription_counter = 0
        self.connection_id = None

        if not self.access_token and not (self.client_id and self.client_secret):
            raise ValueError("Se requiere access_token o credenciales OAuth2")

        if self.debug:
            print(f"🔍 DEBUG - Cliente WebSocket inicializado")
            print(f"   Access Token: {'✅' if self.access_token else '❌'}")
            print(f"   Client ID: {'✅' if self.client_id else '❌'}")
            print(f"   Client Secret: {'✅' if self.client_secret else '❌'}")
            print(f"   WebSocket URL: {self.WS_URL}")

    async def generate_token(self) -> str:
        """Genera un nuevo token OAuth2"""
        if not self.client_id or not self.client_secret:
            raise ValueError("Se requieren credenciales OAuth2")

        if self.debug:
            print(f"🔍 DEBUG - Generando token OAuth2...")

        payload = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'api'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.OAUTH_URL, data=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    self.access_token = result['access_token']
                    if self.debug:
                        print(f"✅ Token generado exitosamente")
                    return self.access_token
                else:
                    error_text = await response.text()
                    if self.debug:
                        print(f"❌ Error generando token: {response.status} - {error_text}")
                    raise Exception(f"Error generando token: {response.status}")

    async def __aenter__(self):
        """Context manager para conexión WebSocket"""
        await self.connect()
        return self

    async def __aexit__(self, *args, **kwargs):
        """Cierra la conexión WebSocket"""
        await self.close()
        print("🔌 Cliente WebSocket cerrado")

    async def connect(self):
        """Establece la conexión WebSocket"""
        if not self.access_token:
            await self.generate_token()

        if self.debug:
            print(f"🔌 Conectando a WebSocket: {self.WS_URL}")

        try:
            # Headers para autenticación
            headers = {
                'Authorization': f'Bearer {self.access_token}'
            }

            self.websocket = await websockets.connect(
                self.WS_URL,
                additional_headers=headers,
                subprotocols=['graphql-transport-ws'],
                ping_interval=30,
                ping_timeout=10,
                max_size=10*1024*1024  # 10MB max message size
            )

            if self.debug:
                print(f"✅ Conexión WebSocket establecida")

            # Inicializar protocolo GraphQL WebSocket
            await self._initialize_connection()

            # Iniciar el loop de mensajes
            asyncio.create_task(self._message_loop())

        except Exception as e:
            if self.debug:
                print(f"❌ Error conectando WebSocket: {e}")
            raise

    async def _initialize_connection(self):
        """Inicializa el protocolo GraphQL WebSocket"""
        if self.debug:
            print(f"🔄 Inicializando protocolo GraphQL WebSocket...")

        # Enviar mensaje de inicialización
        init_message = {
            "type": "connection_init",
            "payload": {}
        }

        await self.websocket.send(json.dumps(init_message))

        # Esperar ACK de conexión
        response = await self.websocket.recv()
        response_data = json.loads(response)

        if response_data.get("type") == "connection_ack":
            if self.debug:
                print(f"✅ Protocolo WebSocket inicializado correctamente")
            self.connection_id = response_data.get("payload", {}).get("connectionId")
        else:
            raise Exception(f"Error inicializando WebSocket: {response_data}")

    async def _message_loop(self):
        """Loop principal para recibir mensajes del WebSocket"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    if self.debug:
                        print(f"❌ Error parseando mensaje: {e}")
                        print(f"   Mensaje: {message[:200]}...")
                except Exception as e:
                    if self.debug:
                        print(f"❌ Error procesando mensaje: {e}")
                        import traceback
                        traceback.print_exc()
                        
        except ConnectionClosed:
            if self.debug:
                print(f"🔌 Conexión WebSocket cerrada")
        except Exception as e:
            if self.debug:
                print(f"❌ Error en loop de mensajes: {e}")
                import traceback
                traceback.print_exc()

    async def _handle_message(self, data: Dict):
        """Maneja los mensajes recibidos del WebSocket"""
        message_type = data.get("type")
        message_id = data.get("id")
        payload = data.get("payload", {})

        if self.debug and message_type != "ka":  # No mostrar keep-alive
            print(f"📨 Mensaje recibido: {message_type} (ID: {message_id})")

        if message_type == "next":
            # Datos de suscripción
            subscription_info = self.active_subscriptions.get(message_id)
            if subscription_info and subscription_info.get('callback'):
                await subscription_info['callback'](payload, message_id)

        elif message_type == "error":
            # Error en suscripción
            if self.debug:
                print(f"❌ Error en suscripción {message_id}: {payload}")

        elif message_type == "complete":
            # Suscripción completada
            if self.debug:
                print(f"✅ Suscripción {message_id} completada")
            if message_id in self.active_subscriptions:
                del self.active_subscriptions[message_id]

        elif message_type == "ka":
            # Keep-alive - no hacer nada
            pass

        elif message_type == "pong":
            # Respuesta a ping
            if self.debug:
                print(f"🏓 Pong recibido")

    async def _execute_subscription(self, subscription_query: str, callback: Callable = None) -> str:
        """
        Ejecuta una suscripción GraphQL via WebSocket
        
        Args:
            subscription_query: Query de suscripción GraphQL
            callback: Función callback para procesar los datos
            
        Returns:
            ID de la suscripción
        """
        if not self.websocket:
            await self.connect()

        subscription_id = str(uuid.uuid4())

        if self.debug:
            print(f"\n🔍 DEBUG - Ejecutando suscripción {subscription_id}")
            print(f"   Query length: {len(subscription_query)}")
            print(f"   Query preview: {subscription_query[:200]}...")

        # Mensaje de inicio de suscripción
        start_message = {
            "id": subscription_id,
            "type": "start",
            "payload": {
                "query": subscription_query
            }
        }

        try:
            await self.websocket.send(json.dumps(start_message))

            self.active_subscriptions[subscription_id] = {
                'callback': callback,
                'query': subscription_query,
                'active': True
            }

            logger.info(f"✅ Suscripción {subscription_id} iniciada")
            if self.debug:
                print(f"✅ Suscripción {subscription_id} iniciada exitosamente")
            
            return subscription_id

        except Exception as e:
            logger.error(f"❌ Error iniciando suscripción: {e}")
            if self.debug:
                print(f"❌ Error iniciando suscripción: {e}")
            raise



    # === MÉTODOS PÚBLICOS DE SUSCRIPCIÓN - USADOS EN NOTEBOOKS ===

    async def track_trader_realtime(self, trader_address: str, callback: Callable, duration_minutes: int = None) -> str:
        """
        Trackea un trader en tiempo real - USADO EN BITQUERY_WEBSOCKETS.ipynb ✅
        
        Args:
            trader_address: Dirección del trader
            callback: Función callback para procesar trades
            duration_minutes: Duración en minutos (opcional)
            
        Returns:
            ID de la suscripción
        """
        if self.debug:
            print(f"\n🎯 Iniciando tracking de trader: {trader_address}")

        query = BitQuerySubscriptions.track_trader_realtime(trader_address)

        if self.debug:
            print(f"📄 Query generada para trader:")
            print(f"   Longitud: {len(query)} caracteres")
            print(f"   Contiene trader address: {'✅' if trader_address in query else '❌'}")

        subscription_id = await self._execute_subscription(query, callback)

        # Programar cancelación automática si se especifica duración
        if duration_minutes:
            asyncio.create_task(self._auto_cancel_subscription(subscription_id, duration_minutes))

        return subscription_id

    async def track_pumpfun_realtime(self, min_amount_usd: float = 100, callback: Callable = None, duration_minutes: int = None) -> str:
        """
        Trackea trades en Pump.fun en tiempo real - USADO EN BITQUERY_WEBSOCKETS.ipynb ✅
        
        Args:
            min_amount_usd: Monto mínimo en USD
            callback: Función callback para procesar trades
            duration_minutes: Duración en minutos (opcional)
            
        Returns:
            ID de la suscripción
        """
        if self.debug:
            print(f"\n🎯 Iniciando tracking de Pump.fun: ${min_amount_usd}+")

        query = BitQuerySubscriptions.track_pumpfun_realtime(min_amount_usd)

        subscription_id = await self._execute_subscription(query, callback)

        if duration_minutes:
            asyncio.create_task(self._auto_cancel_subscription(subscription_id, duration_minutes))

        return subscription_id

    async def track_trader_filtered(self, trader_address: str, mint_address: str = None, dex_name: str = None, min_amount_usd: float = None, callback: Callable = None, duration_minutes: int = None) -> str:
        """
        Trackea un trader en tiempo real con filtros opcionales - USADO EN BITQUERY_WEBSOCKETS.ipynb ✅
        
        Args:
            trader_address: Dirección del trader
            mint_address: Dirección del mint (opcional)
            dex_name: Nombre del DEX (opcional)
            min_amount_usd: Monto mínimo en USD (opcional)
            callback: Función callback para procesar trades
            duration_minutes: Duración en minutos (opcional)
            
        Returns:
            ID de la suscripción
        """
        if self.debug:
            print(f"\n🎯 Iniciando tracking de trader con filtros:")
            print(f"   Trader: {trader_address}")
            print(f"   Mint: {mint_address}")
            print(f"   DEX: {dex_name}")
            print(f"   Monto mínimo: ${min_amount_usd}")
            
        query = BitQuerySubscriptions.track_trader_filtered(trader_address, mint_address, dex_name, min_amount_usd)

        subscription_id = await self._execute_subscription(query, callback)

        if duration_minutes:
            asyncio.create_task(self._auto_cancel_subscription(subscription_id, duration_minutes))

        return subscription_id

    # === MÉTODOS DE CONTROL ===

    async def cancel_subscription(self, subscription_id: str):
        """
        Cancela una suscripción específica
        
        Args:
            subscription_id: ID de la suscripción a cancelar
        """
        if subscription_id in self.active_subscriptions:
            # Enviar mensaje de stop
            stop_message = {
                "id": subscription_id,
                "type": "stop"
            }

            try:
                await self.websocket.send(json.dumps(stop_message))
                del self.active_subscriptions[subscription_id]

                logger.info(f"🛑 Suscripción {subscription_id} cancelada")
                if self.debug:
                    print(f"🛑 Suscripción {subscription_id} cancelada")
            except Exception as e:
                if self.debug:
                    print(f"❌ Error cancelando suscripción {subscription_id}: {e}")

    async def cancel_all_subscriptions(self):
        """Cancela todas las suscripciones activas"""
        for subscription_id in list(self.active_subscriptions.keys()):
            await self.cancel_subscription(subscription_id)
        logger.info("🛑 Todas las suscripciones canceladas")
        if self.debug:
            print("🛑 Todas las suscripciones canceladas")

    async def _auto_cancel_subscription(self, subscription_id: str, duration_minutes: int):
        """Cancela automáticamente una suscripción después de X minutos"""
        await asyncio.sleep(duration_minutes * 60)
        if subscription_id in self.active_subscriptions:
            await self.cancel_subscription(subscription_id)
            logger.info(f"⏰ Suscripción {subscription_id} cancelada automáticamente después de {duration_minutes} minutos")
            if self.debug:
                print(f"⏰ Suscripción {subscription_id} cancelada automáticamente después de {duration_minutes} minutos")

    async def close(self):
        """Cierra la conexión WebSocket"""
        await self.cancel_all_subscriptions()

        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        logger.info("🔌 Cliente WebSocket cerrado")
        if self.debug:
            print("🔌 Cliente WebSocket cerrado")

    def get_active_subscriptions(self) -> Dict[str, Dict]:
        """
        Obtiene información sobre las suscripciones activas
        
        Returns:
            Dict con información de suscripciones activas
        """
        return {
            sub_id: {
                'active': sub_info['active'],
                'query_length': len(sub_info['query'])
            }
            for sub_id, sub_info in self.active_subscriptions.items()
        }

    # === CALLBACKS POR DEFECTO - USADOS EN NOTEBOOKS ===

    @staticmethod
    async def default_trader_callback(data: Dict, subscription_id: str):
        """Callback por defecto para traders - USADO EN NOTEBOOKS ✅"""
        if not data or 'data' not in data:
            return

        trades = data.get('data', {}).get('Solana', {}).get('DEXTrades', [])

        for trade in trades:
            # Determinar si es compra o venta
            buy_data = trade.get('Trade', {}).get('Buy')
            sell_data = trade.get('Trade', {}).get('Sell')

            if buy_data and buy_data.get('Amount'):
                side = "🟢 COMPRA"
                amount_usd = float(buy_data.get('AmountInUSD', 0))
                currency = buy_data.get('Currency', {})
                account = buy_data.get('Account', {}).get('Address', '')
            elif sell_data and sell_data.get('Amount'):
                side = "🔴 VENTA"
                amount_usd = float(sell_data.get('AmountInUSD', 0))
                currency = sell_data.get('Currency', {})
                account = sell_data.get('Account', {}).get('Address', '')
            else:
                continue

            token_symbol = currency.get('Symbol', 'UNKNOWN')
            block_time = trade.get('Block', {}).get('Time', '')

            print(f"🎯 TRADE [{subscription_id}] - {side}")
            print(f"   Token: {token_symbol} | ${amount_usd:.2f} | {account[:8]}... | {block_time}")

    @staticmethod
    async def debug_trader_callback(data: Dict, subscription_id: str):
        """Callback de debug completo - USADO EN NOTEBOOKS PARA DEBUGGING ✅"""
        timestamp = asyncio.get_event_loop().time()
        print(f"\n🔍 DEBUG CALLBACK [{subscription_id}] - {timestamp}")
        print(f"📦 Datos recibidos: {json.dumps(data, indent=2)[:500]}...")

        if data and 'data' in data:
            solana_data = data['data'].get('Solana', {})
            trades = solana_data.get('DEXTrades', [])
            print(f"📊 Trades encontrados: {len(trades)}")

            for i, trade in enumerate(trades[:3]):  # Solo primeros 3
                print(f"   Trade {i+1}: {trade}")
        else:
            print("⚠️ Sin datos válidos")
