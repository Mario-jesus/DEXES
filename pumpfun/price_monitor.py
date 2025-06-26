# -*- coding: utf-8 -*-
import asyncio
import websockets
import json
import threading
from typing import Dict, List, Callable, Optional, Any
from datetime import datetime
from collections import defaultdict, deque

class PumpFunPriceMonitor:
    """
    Monitor de precios en tiempo real para Pump.fun usando PumpPortal WebSocket
    Permite suscribirse a múltiples tokens y recibir updates de precios
    """
    
    def __init__(self):
        """Inicializa el monitor de precios"""
        self.websocket_url = "wss://pumpportal.fun/api/data"
        self.websocket = None
        self.is_connected = False
        self.is_running = False
        
        # Almacenamiento de datos
        self.subscribed_tokens = set()
        self.subscribed_accounts = set()
        self.token_prices = {}
        self.price_history = defaultdict(lambda: deque(maxlen=1000))
        
        # Callbacks
        self.on_new_token_callback = None
        self.on_token_trade_callback = None
        self.on_account_trade_callback = None
        self.on_migration_callback = None
        
        # Thread para WebSocket
        self.websocket_thread = None
        
        print("📊 PumpFun Price Monitor inicializado")

    def __del__(self):
        """Destructor para asegurar que el WebSocket se cierre"""
        try:
            # Simplemente marcar como desconectado, no intentar cerrar async
            self.is_connected = False
            self.is_running = False
            if hasattr(self, 'websocket') and self.websocket:
                try:
                    # Cerrar de forma síncrona si es posible
                    if hasattr(self.websocket, 'close') and not self.websocket.closed:
                        # No usar await aquí, solo marcar para cierre
                        pass
                except:
                    pass
        except:
            pass  # Ignorar todos los errores en destructor

    async def connect(self):
        """Conecta al WebSocket de PumpPortal"""
        try:
            print("🔗 Conectando a PumpPortal WebSocket...")
            self.websocket = await websockets.connect(self.websocket_url)
            self.is_connected = True
            print("✅ Conectado exitosamente")
            return True
        except Exception as e:
            print(f"❌ Error conectando: {e}")
            self.is_connected = False
            return False
    
    async def disconnect(self):
        """Desconecta del WebSocket"""
        try:
            self.is_connected = False
            self.is_running = False
            if self.websocket and not self.websocket.closed:
                await self.websocket.close()
                print("🔌 Desconectado de PumpPortal")
        except Exception as e:
            print(f"⚠️ Error al desconectar: {e}")
        finally:
            self.websocket = None
    
    async def subscribe_new_tokens(self):
        """Suscribe a eventos de creación de nuevos tokens"""
        if not self.is_connected:
            print("❌ No conectado al WebSocket")
            return False
        
        try:
            payload = {"method": "subscribeNewToken"}
            await self.websocket.send(json.dumps(payload))
            print("✅ Suscrito a nuevos tokens")
            return True
        except Exception as e:
            print(f"❌ Error suscribiendo a nuevos tokens: {e}")
            return False
    
    async def subscribe_token_trades(self, token_addresses: List[str]):
        """
        Suscribe a trades de tokens específicos
        
        Args:
            token_addresses: Lista de direcciones de tokens
        """
        if not self.is_connected:
            print("❌ No conectado al WebSocket")
            return False
        
        try:
            payload = {
                "method": "subscribeTokenTrade",
                "keys": token_addresses
            }
            await self.websocket.send(json.dumps(payload))
            self.subscribed_tokens.update(token_addresses)
            print(f"✅ Suscrito a trades de {len(token_addresses)} tokens")
            return True
        except Exception as e:
            print(f"❌ Error suscribiendo a trades de tokens: {e}")
            return False
    
    async def subscribe_account_trades(self, account_addresses: List[str]):
        """
        Suscribe a trades de cuentas específicas
        
        Args:
            account_addresses: Lista de direcciones de cuentas
        """
        if not self.is_connected:
            print("❌ No conectado al WebSocket")
            return False
        
        try:
            payload = {
                "method": "subscribeAccountTrade",
                "keys": account_addresses
            }
            await self.websocket.send(json.dumps(payload))
            self.subscribed_accounts.update(account_addresses)
            print(f"✅ Suscrito a trades de {len(account_addresses)} cuentas")
            return True
        except Exception as e:
            print(f"❌ Error suscribiendo a trades de cuentas: {e}")
            return False
    
    async def subscribe_migrations(self):
        """Suscribe a eventos de migración a Raydium"""
        if not self.is_connected:
            print("❌ No conectado al WebSocket")
            return False
        
        try:
            payload = {"method": "subscribeMigration"}
            await self.websocket.send(json.dumps(payload))
            print("✅ Suscrito a migraciones")
            return True
        except Exception as e:
            print(f"❌ Error suscribiendo a migraciones: {e}")
            return False
    
    async def unsubscribe_token_trades(self, token_addresses: List[str]):
        """Desuscribe de trades de tokens específicos"""
        if not self.is_connected:
            return False
        
        try:
            payload = {
                "method": "unsubscribeTokenTrade",
                "keys": token_addresses
            }
            await self.websocket.send(json.dumps(payload))
            self.subscribed_tokens.difference_update(token_addresses)
            print(f"✅ Desuscrito de {len(token_addresses)} tokens")
            return True
        except Exception as e:
            print(f"❌ Error desuscribiendo: {e}")
            return False
    
    def process_message(self, message_data: Dict[str, Any]):
        """
        Procesa mensajes recibidos del WebSocket
        
        Args:
            message_data: Datos del mensaje recibido
        """
        try:
            # Detectar tipo de mensaje
            if 'tokenTrade' in message_data:
                self._process_token_trade(message_data)
            elif 'newToken' in message_data:
                self._process_new_token(message_data)
            elif 'accountTrade' in message_data:
                self._process_account_trade(message_data)
            elif 'migration' in message_data:
                self._process_migration(message_data)
            elif 'txType' in message_data and message_data.get('txType') == 'create':
                # Evento de creación de token (nuevo formato)
                self._process_token_creation(message_data)
            else:
                print(f"📨 Mensaje desconocido: {message_data}")
                
        except Exception as e:
            print(f"❌ Error procesando mensaje: {e}")
    
    def _process_token_creation(self, data: Dict[str, Any]):
        """Procesa eventos de creación de nuevos tokens"""
        try:
            # Extraer datos del token recién creado
            token_data = {
                'mint': data.get('mint', ''),
                'name': data.get('name', ''),
                'symbol': data.get('symbol', ''),
                'uri': data.get('uri', ''),
                'signature': data.get('signature', ''),
                'traderPublicKey': data.get('traderPublicKey', ''),
                'initialBuy': data.get('initialBuy', 0),
                'solAmount': data.get('solAmount', 0),
                'marketCapSol': data.get('marketCapSol', 0),
                'bondingCurveKey': data.get('bondingCurveKey', ''),
                'vTokensInBondingCurve': data.get('vTokensInBondingCurve', 0),
                'vSolInBondingCurve': data.get('vSolInBondingCurve', 0),
                'pool': data.get('pool', 'pump'),
                'timestamp': datetime.now().isoformat()
            }
            
            # Mostrar información del nuevo token
            print(f"🆕 NUEVO TOKEN CREADO:")
            print(f"   🪙 {token_data['name']} ({token_data['symbol']})")
            print(f"   📍 Mint: {token_data['mint']}")
            print(f"   💰 Market Cap: {token_data['marketCapSol']:.2f} SOL")
            print(f"   🛒 Compra inicial: {token_data['solAmount']:.6f} SOL")
            print(f"   👤 Creador: {token_data['traderPublicKey']}")
            print("-" * 50)
            
            # Llamar callback si está configurado
            if self.on_new_token_callback:
                self.on_new_token_callback(token_data)
                
        except Exception as e:
            print(f"❌ Error procesando creación de token: {e}")
    
    def _process_token_trade(self, data: Dict[str, Any]):
        """Procesa trades de tokens"""
        try:
            trade_data = data.get('tokenTrade', {})
            token_address = trade_data.get('mint', '')
            
            # Extraer datos del trade
            tx_type = trade_data.get('txType', 'unknown')
            market_cap = trade_data.get('marketCapSol', 0)
            token_amount = trade_data.get('tokenAmount', 0)
            sol_amount = trade_data.get('solAmount', 0)
            
            # Calcular precio por token usando los datos del trade
            price_per_token = 0
            if token_amount > 0 and sol_amount > 0:
                price_per_token = sol_amount / token_amount
            
            # Usar el market cap para estimar precio si no hay datos directos
            elif market_cap > 0:
                # Estimación basada en market cap (asumiendo supply estándar de pump.fun)
                estimated_supply = 1_000_000_000  # Supply típico de pump.fun
                price_per_token = market_cap / estimated_supply
            
            timestamp = datetime.now()
            
            # Almacenar precio actual con más datos
            self.token_prices[token_address] = {
                'price': price_per_token,
                'market_cap': market_cap,
                'volume': sol_amount,
                'tx_type': tx_type,
                'token_amount': token_amount,
                'sol_amount': sol_amount,
                'timestamp': timestamp,
                'data': trade_data
            }
            
            # Agregar a historial
            self.price_history[token_address].append({
                'price': price_per_token,
                'market_cap': market_cap,
                'volume': sol_amount,
                'tx_type': tx_type,
                'timestamp': timestamp
            })
            
            # Mostrar información más detallada
            action_emoji = "🟢" if tx_type == "buy" else "🔴"
            print(f"{action_emoji} Trade - {token_address[:8]}... | {tx_type.upper()}")
            print(f"   💰 Market Cap: {market_cap:.2f} SOL")
            if price_per_token > 0:
                print(f"   📊 Precio: {price_per_token:.10f} SOL/token")
            if sol_amount > 0:
                print(f"   💎 Volumen: {sol_amount:.6f} SOL")
            
            # Llamar callback si existe
            if self.on_token_trade_callback:
                self.on_token_trade_callback(trade_data)
                
        except Exception as e:
            print(f"❌ Error procesando trade de token: {e}")
    
    def _process_new_token(self, data: Dict[str, Any]):
        """Procesa nuevos tokens creados"""
        try:
            token_data = data.get('newToken', {})
            print(f"🆕 Nuevo token creado: {token_data.get('mint', 'Unknown')}")
            
            if self.on_new_token_callback:
                self.on_new_token_callback(token_data)
                
        except Exception as e:
            print(f"❌ Error procesando nuevo token: {e}")
    
    def _process_account_trade(self, data: Dict[str, Any]):
        """Procesa trades de cuentas"""
        try:
            account_data = data.get('accountTrade', {})
            account = account_data.get('account', '')
            print(f"👤 Trade de cuenta: {account[:8]}...")
            
            if self.on_account_trade_callback:
                self.on_account_trade_callback(account_data)
                
        except Exception as e:
            print(f"❌ Error procesando trade de cuenta: {e}")
    
    def _process_migration(self, data: Dict[str, Any]):
        """Procesa migraciones a Raydium"""
        try:
            migration_data = data.get('migration', {})
            token = migration_data.get('mint', '')
            print(f"🚀 Migración a Raydium: {token[:8]}...")
            
            if self.on_migration_callback:
                self.on_migration_callback(migration_data)
                
        except Exception as e:
            print(f"❌ Error procesando migración: {e}")
    
    async def listen(self):
        """Loop principal para escuchar mensajes del WebSocket"""
        while self.is_running and self.is_connected:
            try:
                message = await self.websocket.recv()
                data = json.loads(message)
                self.process_message(data)
                
            except websockets.exceptions.ConnectionClosed:
                print("🔌 Conexión WebSocket cerrada")
                self.is_connected = False
                break
            except Exception as e:
                print(f"❌ Error en listen: {e}")
                await asyncio.sleep(1)
    
    def start_monitoring(self):
        """Inicia el monitoreo en un thread separado"""
        if self.is_running:
            print("⚠️  Monitor ya está corriendo")
            return
        
        self.is_running = True
        self.websocket_thread = threading.Thread(target=self._run_websocket_loop)
        self.websocket_thread.daemon = True
        self.websocket_thread.start()
        print("🚀 Monitor iniciado")
    
    def stop_monitoring(self):
        """Detiene el monitoreo"""
        try:
            self.is_running = False
            self.is_connected = False
            
            # Esperar que el thread termine
            if self.websocket_thread and self.websocket_thread.is_alive():
                self.websocket_thread.join(timeout=3)
                
            # Limpiar referencias
            self.websocket = None
            self.websocket_thread = None
            
            print("⏹️ Monitor detenido")
        except Exception as e:
            print(f"⚠️ Error deteniendo monitor: {e}")
    
    def _run_websocket_loop(self):
        """Ejecuta el loop de WebSocket en thread separado"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self._websocket_main())
        except Exception as e:
            print(f"❌ Error en WebSocket loop: {e}")
        finally:
            loop.close()
    
    async def _websocket_main(self):
        """Función principal del WebSocket"""
        while self.is_running:
            try:
                if await self.connect():
                    # Suscribirse automáticamente a nuevos tokens si está configurado
                    await self.subscribe_new_tokens()
                    
                    # Suscribirse automáticamente a migraciones
                    await self.subscribe_migrations()
                    
                    # Suscribirse a tokens que ya están en la lista
                    if self.subscribed_tokens:
                        await self.subscribe_token_trades(list(self.subscribed_tokens))
                    
                    await self.listen()
                else:
                    print("❌ No se pudo conectar, reintentando en 5 segundos...")
                    await asyncio.sleep(5)
            except Exception as e:
                print(f"❌ Error en WebSocket main: {e}")
                await asyncio.sleep(5)
    
    # Callbacks
    def set_new_token_callback(self, callback: Callable):
        """Establece callback para nuevos tokens"""
        self.on_new_token_callback = callback
    
    def set_token_trade_callback(self, callback: Callable):
        """Establece callback para trades de tokens"""
        self.on_token_trade_callback = callback
    
    def set_account_trade_callback(self, callback: Callable):
        """Establece callback para trades de cuentas"""
        self.on_account_trade_callback = callback
    
    def set_migration_callback(self, callback: Callable):
        """Establece callback para migraciones"""
        self.on_migration_callback = callback
    
    # Métodos de consulta
    def get_token_price(self, token_address: str) -> Optional[Dict[str, Any]]:
        """Obtiene el precio actual de un token"""
        return self.token_prices.get(token_address)
    
    def get_price_history(self, token_address: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Obtiene el historial de precios de un token"""
        history = list(self.price_history[token_address])
        return history[-limit:] if len(history) > limit else history
    
    def get_subscribed_tokens(self) -> List[str]:
        """Obtiene lista de tokens suscritos"""
        return list(self.subscribed_tokens)
    
    def get_subscribed_accounts(self) -> List[str]:
        """Obtiene lista de cuentas suscritas"""
        return list(self.subscribed_accounts)
    
    def get_status(self) -> Dict[str, Any]:
        """Obtiene estado del monitor"""
        return {
            "is_connected": self.is_connected,
            "is_running": self.is_running,
            "subscribed_tokens": len(self.subscribed_tokens),
            "subscribed_accounts": len(self.subscribed_accounts),
            "tracked_tokens": len(self.token_prices),
            "websocket_url": self.websocket_url
        }
    
    def monitor_token_price(self, token_address: str, duration_minutes: int = 5, 
                          show_trades: bool = True, price_alerts: Dict = None) -> Dict[str, Any]:
        """
        Monitorea el precio de un token específico en tiempo real
        
        Args:
            token_address: Dirección del token a monitorear
            duration_minutes: Duración del monitoreo en minutos
            show_trades: Si mostrar cada trade individual
            price_alerts: Dict con alertas {'above': precio, 'below': precio}
            
        Returns:
            Diccionario con estadísticas del monitoreo
        """
        import time
        from datetime import datetime
        
        print(f"🎯 MONITOR DE PRECIOS EN TIEMPO REAL")
        print("=" * 70)
        print(f"🔗 Token: {token_address}")
        print(f"⏰ Duración: {duration_minutes} minutos")
        
        if price_alerts:
            if price_alerts.get('above'):
                print(f"🔔 Alerta HIGH: {price_alerts['above']:.10f} SOL")
            if price_alerts.get('below'):
                print(f"🔔 Alerta LOW: {price_alerts['below']:.10f} SOL")
        
        print("-" * 70)
        
        # Estadísticas del monitoreo
        stats = {
            'token': token_address,
            'start_time': datetime.now(),
            'duration_minutes': duration_minutes,
            'trade_count': 0,
            'buy_count': 0,
            'sell_count': 0,
            'total_volume': 0.0,
            'price_history': [],
            'last_price': 0.0,
            'highest_price': 0.0,
            'lowest_price': float('inf'),
            'alerts_triggered': {'above': False, 'below': False}
        }
        
        # Configurar callback específico para este monitoreo
        def price_callback(trade_data):
            mint = trade_data.get('mint', '')
            if mint != token_address:
                return
                
            # Extraer datos del trade
            tx_type = trade_data.get('txType', 'unknown')
            market_cap = trade_data.get('marketCapSol', 0)
            token_amount = trade_data.get('tokenAmount', 0)
            sol_amount = trade_data.get('solAmount', 0)
            trader = trade_data.get('traderPublicKey', '')[:8]
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # Calcular precio por token
            price_per_token = 0
            if token_amount > 0 and sol_amount > 0:
                price_per_token = sol_amount / token_amount
                stats['last_price'] = price_per_token
                stats['price_history'].append(price_per_token)
                
                # Actualizar máximos y mínimos
                if price_per_token > stats['highest_price']:
                    stats['highest_price'] = price_per_token
                if price_per_token < stats['lowest_price']:
                    stats['lowest_price'] = price_per_token
            
            # Actualizar estadísticas
            stats['trade_count'] += 1
            stats['total_volume'] += sol_amount
            
            if tx_type == 'buy':
                stats['buy_count'] += 1
            elif tx_type == 'sell':
                stats['sell_count'] += 1
            
            # Verificar alertas
            if price_alerts and price_per_token > 0:
                if (price_alerts.get('above') and 
                    price_per_token >= price_alerts['above'] and 
                    not stats['alerts_triggered']['above']):
                    print(f"\n🚨🚨🚨 ALERTA HIGH ACTIVADA 🚨🚨🚨")
                    print(f"💰 Precio: {price_per_token:.10f} SOL")
                    print(f"🎯 Umbral: {price_alerts['above']:.10f} SOL")
                    stats['alerts_triggered']['above'] = True
                    print("-" * 70)
                
                if (price_alerts.get('below') and 
                    price_per_token <= price_alerts['below'] and 
                    not stats['alerts_triggered']['below']):
                    print(f"\n🚨🚨🚨 ALERTA LOW ACTIVADA 🚨🚨🚨")
                    print(f"💰 Precio: {price_per_token:.10f} SOL")
                    print(f"🎯 Umbral: {price_alerts['below']:.10f} SOL")
                    stats['alerts_triggered']['below'] = True
                    print("-" * 70)
            
            # Mostrar trade si está habilitado
            if show_trades:
                action_emoji = "🟢" if tx_type == "buy" else "🔴"
                print(f"{action_emoji} [{timestamp}] {tx_type.upper()}")
                print(f"   💰 Market Cap: {market_cap:.2f} SOL")
                print(f"   🪙 Cantidad: {token_amount:,.0f} tokens")
                print(f"   💎 SOL: {sol_amount:.6f}")
                if price_per_token > 0:
                    print(f"   📊 Precio/Token: {price_per_token:.10f} SOL")
                print(f"   👤 Trader: {trader}...")
                print("-" * 50)
        
        # Establecer callback
        original_callback = self.on_token_trade_callback
        self.set_token_trade_callback(price_callback)
        
        try:
            # Iniciar monitoreo si no está corriendo
            was_running = self.is_running
            if not was_running:
                self.start_monitoring()
                time.sleep(2)  # Esperar conexión
            
            # Suscribirse al token específico (esto requiere que el monitor esté corriendo)
            # En implementación real, esto se haría de forma async
            print(f"📡 Monitoreando trades del token: {token_address[:8]}...")
            print("👂 Escuchando precios en tiempo real...")
            print("-" * 70)
            
            # Simular suscripción (en implementación real sería async)
            if self.is_connected:
                self.subscribed_tokens.add(token_address)
            
            # Monitorear por el tiempo especificado
            start_time = time.time()
            timeout = duration_minutes * 60
            last_summary = start_time
            
            while (time.time() - start_time) < timeout:
                time.sleep(1)
                
                # Mostrar resumen cada 30 segundos
                current_time = time.time()
                if current_time - last_summary >= 30:
                    elapsed = (current_time - start_time) / 60
                    remaining = duration_minutes - elapsed
                    
                    print(f"\n📊 RESUMEN PARCIAL ({elapsed:.1f} min transcurridos)")
                    print(f"📈 Trades: {stats['trade_count']} | Compras: {stats['buy_count']} | Ventas: {stats['sell_count']}")
                    print(f"💰 Volumen: {stats['total_volume']:.4f} SOL")
                    if stats['last_price'] > 0:
                        print(f"💎 Último precio: {stats['last_price']:.10f} SOL")
                        print(f"📊 Máximo: {stats['highest_price']:.10f} | Mínimo: {stats['lowest_price']:.10f}")
                    print(f"⏱️  Tiempo restante: {remaining:.1f} minutos")
                    print("-" * 50)
                    
                    last_summary = current_time
            
            print("\n⏰ Tiempo de monitoreo completado")
            
        finally:
            # Restaurar callback original
            self.set_token_trade_callback(original_callback)
            
            # Si iniciamos el monitor, detenerlo
            if not was_running and self.is_running:
                self.stop_monitoring()
        
        # Generar resumen final
        self._print_monitoring_summary(stats)
        
        return stats
    
    def _print_monitoring_summary(self, stats: Dict[str, Any]):
        """Imprime resumen final del monitoreo"""
        print("\n" + "=" * 70)
        print("📊 RESUMEN DEL MONITOREO")
        print("=" * 70)
        
        duration = stats['duration_minutes']
        trade_count = stats['trade_count']
        
        print(f"🎯 Token: {stats['token']}")
        print(f"⏰ Duración: {duration} minutos")
        print(f"📈 Total de trades: {trade_count}")
        
        if trade_count > 0:
            buy_count = stats['buy_count']
            sell_count = stats['sell_count']
            total_volume = stats['total_volume']
            
            print(f"🟢 Compras: {buy_count} ({buy_count/trade_count*100:.1f}%)")
            print(f"🔴 Ventas: {sell_count} ({sell_count/trade_count*100:.1f}%)")
            print(f"💰 Volumen total: {total_volume:.6f} SOL")
            print(f"💰 Volumen promedio: {total_volume/trade_count:.6f} SOL/trade")
            
            if stats['price_history']:
                last_price = stats['last_price']
                highest_price = stats['highest_price']
                lowest_price = stats['lowest_price']
                avg_price = sum(stats['price_history']) / len(stats['price_history'])
                
                print()
                print(f"💎 Precio final: {last_price:.10f} SOL")
                print(f"📊 Precio promedio: {avg_price:.10f} SOL")
                print(f"⬆️  Precio máximo: {highest_price:.10f} SOL")
                print(f"⬇️  Precio mínimo: {lowest_price:.10f} SOL")
                
                # Calcular volatilidad
                if avg_price > 0:
                    volatility = (highest_price - lowest_price) / avg_price * 100
                    print(f"📊 Volatilidad: {volatility:.2f}%")
                
                # Cambio de precio
                if len(stats['price_history']) > 1:
                    first_price = stats['price_history'][0]
                    price_change = ((last_price - first_price) / first_price) * 100
                    change_emoji = "📈" if price_change > 0 else "📉" if price_change < 0 else "➡️"
                    print(f"{change_emoji} Cambio total: {price_change:+.2f}%")
        else:
            print("❌ No se detectaron trades durante el monitoreo")
            print("💡 El token podría no tener actividad o la dirección es incorrecta")
    
    def monitor_new_tokens(self, duration_minutes: int = 10, 
                          auto_subscribe: bool = False, max_tokens: int = 5) -> List[Dict[str, Any]]:
        """
        Monitorea nuevos tokens creados en Pump.fun
        
        Args:
            duration_minutes: Duración del monitoreo
            auto_subscribe: Si suscribirse automáticamente a trades de nuevos tokens
            max_tokens: Máximo número de tokens a trackear automáticamente
            
        Returns:
            Lista de nuevos tokens detectados
        """
        import time
        
        print(f"🆕 MONITOR DE NUEVOS TOKENS")
        print("=" * 70)
        print(f"⏰ Duración: {duration_minutes} minutos")
        if auto_subscribe:
            print(f"🔄 Auto-suscripción: SÍ (máx {max_tokens} tokens)")
        print("-" * 70)
        
        new_tokens = []
        tracked_tokens = set()
        
        def new_token_callback(token_data):
            mint = token_data.get('mint', 'Unknown')
            market_cap = token_data.get('marketCapSol', 0)
            initial_buy = token_data.get('initialBuy', 0)
            creator = token_data.get('traderPublicKey', '')[:8]
            
            token_info = {
                'mint': mint,
                'market_cap': market_cap,
                'initial_buy': initial_buy,
                'creator': creator,
                'timestamp': datetime.now()
            }
            
            new_tokens.append(token_info)
            
            print(f"🆕 NUEVO TOKEN: {mint[:8]}...")
            print(f"   💰 Market Cap inicial: {market_cap:.2f} SOL")
            print(f"   🛒 Compra inicial: {initial_buy:,.0f} tokens")
            print(f"   👤 Creador: {creator}...")
            print("-" * 50)
            
            # Auto-suscribirse si está habilitado
            if auto_subscribe and len(tracked_tokens) < max_tokens:
                tracked_tokens.add(mint)
                print(f"📡 Auto-suscrito a {mint[:8]}...")
        
        # Configurar callback
        original_callback = self.on_new_token_callback
        self.set_new_token_callback(new_token_callback)
        
        try:
            # Iniciar monitoreo
            was_running = self.is_running
            if not was_running:
                self.start_monitoring()
                time.sleep(2)
            
            # Monitorear por el tiempo especificado
            start_time = time.time()
            timeout = duration_minutes * 60
            
            while (time.time() - start_time) < timeout:
                elapsed = (time.time() - start_time) / 60
                remaining = duration_minutes - elapsed
                
                if int(elapsed) % 60 == 0 and elapsed > 0:  # Cada minuto
                    print(f"⏱️  {len(new_tokens)} tokens detectados | {remaining:.1f} min restantes")
                
                time.sleep(1)
            
            print(f"\n⏰ Monitoreo completado")
            
        finally:
            # Restaurar callback
            self.set_new_token_callback(original_callback)
            
            if not was_running and self.is_running:
                self.stop_monitoring()
        
        # Resumen final
        print(f"\n📊 RESUMEN: {len(new_tokens)} nuevos tokens detectados")
        if auto_subscribe:
            print(f"📡 Tokens auto-suscritos: {len(tracked_tokens)}")
        
        return new_tokens 