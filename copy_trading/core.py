# -*- coding: utf-8 -*-
"""
Sistema principal de Copy Trading
"""
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio

from pumpfun.api_client import PumpFunApiClient
from pumpfun.transactions import PumpFunTransactions
from pumpfun.subscriptions import PumpFunSubscriptions
from pumpfun.wallet_manager import PumpFunWalletStorage, WalletData, WalletImportException
from pumpfun.pumpfun_trade_analyzer import PumpFunTradeAnalyzer
from logging_system import AppLogger

from .config import CopyTradingConfig, TransactionType
from .validation import ValidationEngine
from .callbacks import TradeProcessorCallback
from .position_management import PositionQueueManager
from .position_management.models import PositionTraderTradeData
from .data_management import TokenTraderManager, TradingDataFetcher
from .notifications import (
    NotificationManager,
    TelegramStrategy,
    ConsoleStrategy
)


class CopyTrading:
    """Sistema principal de copy trading"""

    def __init__(self, config: CopyTradingConfig):
        """
        Inicializa el sistema de copy trading
        
        Args:
            config: Configuración del sistema
        """
        self.config = config

        # Inicializar componentes
        self._logger = AppLogger(self.__class__.__name__)
        self._logger.info("Inicializando sistema Copy Trading")

        self.trading_data_fetcher = TradingDataFetcher(rpc_url=config.rpc_url)
        self._logger.debug("TradingDataFetcher inicializado")

        # Inicializar TokenTraderManager
        self.token_trader_manager = TokenTraderManager(
            config=config,
            trading_data_fetcher=self.trading_data_fetcher
        )
        self._logger.debug("TokenTraderManager inicializado")

        # Inicializar notificaciones
        self.notification_manager = self._setup_notifications()
        if self.notification_manager:
            self._logger.debug("Sistema de notificaciones configurado")
        else:
            self._logger.debug("Sistema de notificaciones deshabilitado")

        self.queue_manager = PositionQueueManager(
            config=config,
            trader_analyzer=PumpFunTradeAnalyzer(rpc_url=config.rpc_url),
            trading_data_fetcher=self.trading_data_fetcher,
            token_trader_manager=self.token_trader_manager,
            notification_manager=self.notification_manager
        )
        self._logger.debug("PositionQueueManager inicializado")

        self.validation_engine = ValidationEngine(
            config=config,
            token_trader_manager=self.token_trader_manager
        )
        self._logger.debug("ValidationEngine inicializado")

        # Cliente API centralizado (se configurará en start())
        self.client: Optional[PumpFunApiClient] = None

        # Wallet data
        self.wallet_data: Optional[WalletData] = None

        self.subscriptions: Optional[PumpFunSubscriptions] = None
        self.transactions_manager: Optional[PumpFunTransactions] = None

        # Callback (se inicializará después de que las colas estén listas)
        self.trade_processor_callback: Optional[TradeProcessorCallback] = None

        # Estado
        self.is_running = False
        self.start_time: Optional[datetime] = None

        # Métricas
        self.metrics = {
            'trades_processed': 0,
            'trades_executed': 0,
            'total_volume_sol': 0.0,
            'total_pnl': 0.0,
            'average_latency_ms': 0.0,
            'uptime_seconds': 0
        }

        self._pending_task = None

        # Flag para indicar si el QueueManager ya fue detenido
        self._queue_manager_stopped: bool = False
        
        self._logger.debug("Sistema Copy Trading inicializado correctamente")

    async def __aenter__(self):
        """Context manager entry"""
        self._logger.debug("Entrando en context manager")
        # Inicializar QueueManager con context manager
        await self.queue_manager.start()
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self._logger.debug("Saliendo del context manager")
        try:
            await self.stop()
        except asyncio.TimeoutError:
            self._logger.warning("Timeout en self.stop(), continuando...")
        except Exception as e:
            self._logger.error(f"Error en self.stop(): {e}")
        finally:
            # Detener QueueManager solo si no se detuvo antes en stop()
            if not self._queue_manager_stopped:
                try:
                    await self.queue_manager.stop()
                except Exception as e:
                    self._logger.error(f"Error en queue_manager.stop() en __aexit__: {e}")

    def _setup_notifications(self) -> Optional[NotificationManager]:
        """Configura el sistema de notificaciones"""
        if not self.config.notifications_enabled:
            self._logger.debug("Notificaciones deshabilitadas en configuración")
            return None

        strategies = []

        # Añadir estrategia de Telegram si está configurada
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            telegram_strategy = TelegramStrategy(
                config={
                    'token': self.config.telegram_bot_token,
                    'chat_id': self.config.telegram_chat_id,
                    'messages_per_minute': self.config.telegram_messages_per_minute
                }
            )
            strategies.append(telegram_strategy)
            self._logger.debug("Estrategia de Telegram configurada")
        else:
            self._logger.debug("Telegram no configurado (faltan token o chat_id)")

        # Siempre incluir consola como fallback
        console_strategy = ConsoleStrategy(
            config={'colored': True}
        )
        strategies.append(console_strategy)
        self._logger.debug("Estrategia de consola configurada")

        return NotificationManager(strategies)

    async def start(self):
        """Inicia el sistema de copy trading"""
        if self.is_running:
            self._logger.warning("El sistema ya está ejecutándose")
            return

        try:
            self._logger.info("Iniciando sistema Copy Trading")
            self._logger.debug(f"Modo: {'DRY RUN' if self.config.dry_run else 'LIVE'}")
            self._logger.debug(f"Traders a seguir: {len(self.config.traders)}")
            self._logger.debug(f"Tipo de transacción: {self.config.transaction_type.value}")

            # Cargar datos completos de la wallet usando WalletManager
            try:
                self._logger.debug(f"Cargando wallet desde: {self.config.wallet_file}")
                self.wallet_data = await PumpFunWalletStorage.load_wallet_data_from_file(self.config.wallet_file)
                if not isinstance(self.wallet_data, WalletData):
                    raise WalletImportException("No se pudieron cargar los datos de la wallet", file_path=self.config.wallet_file)
                self._logger.debug("Wallet cargada correctamente")
            except WalletImportException as e:
                self._logger.error(f"Error cargando wallet: {e}")
                if self.notification_manager:
                    await self.notification_manager.notify_system(
                        f"Error cargando wallet: {e}",
                        "error"
                    )
                raise

            # Conectar cliente API
            self._logger.debug("Conectando cliente API...")
            self.client = PumpFunApiClient(api_key=self.wallet_data.api_key, enable_websocket=True, enable_http=True)
            await self.client.connect()
            self._logger.debug("Cliente API conectado")

            # Inicializar validation engine con el keypair y la conexión rpc
            self._logger.debug("Inicializando ValidationEngine...")
            await self.validation_engine.initialize(self.wallet_data.get_keypair())
            self._logger.debug("ValidationEngine inicializado")

            # Initialize transaction manager con el cliente centralizado
            self.transactions_manager = PumpFunTransactions(api_client=self.client)
            self._logger.debug("PumpFunTransactions inicializado")

            # Inicializar subscriptions con el cliente centralizado
            self.subscriptions = PumpFunSubscriptions(api_client=self.client)
            self._logger.debug("PumpFunSubscriptions inicializado")

            if not self.queue_manager.pending_queue:
                error_msg = "PendingPositionQueue no inicializado"
                self._logger.error(error_msg)
                raise ValueError(error_msg)

            # Inicializar callback después de que las colas estén listas
            self._logger.debug("Inicializando TradeProcessorCallback...")
            self.trade_processor_callback = TradeProcessorCallback(
                config=self.config,
                pending_position_queue=self.queue_manager.pending_queue,
                validation_engine=self.validation_engine
            )
            self._logger.debug("TradeProcessorCallback inicializado")

            # Suscribirse a trades de los traders
            trader_addresses = [trader.wallet_address for trader in self.config.traders]
            self._logger.debug(f"Suscribiendo a {len(trader_addresses)} traders: {[addr[:8] + '...' for addr in trader_addresses]}")
            await self.subscriptions.subscribe_account_trade(
                account_addresses=trader_addresses,
                callback=self.trade_processor_callback,
                use_api_key=True
            )

            self._logger.debug(f"Suscrito a {len(self.config.traders)} traders")

            # Inicializar TokenTraderManager
            self._logger.debug("Inicializando TokenTraderManager...")
            await self.token_trader_manager.initialize_system_trader_stats()
            self._logger.debug("TokenTraderManager inicializado")

            # Actualizar estado
            self.is_running = True
            self.start_time = datetime.now()

            self._logger.debug("Sistema iniciado correctamente")

            # Notificar inicio del sistema
            if self.notification_manager:
                await self.notification_manager.notify_system(
                    "Sistema iniciado correctamente",
                    "success"
                )

            # Lanzar el loop de procesamiento de posiciones pendientes
            if not self._pending_task:
                self._logger.debug("Iniciando loop de procesamiento de posiciones pendientes...")
                self._pending_task = asyncio.create_task(self._pending_positions_loop())
                self._logger.debug("Loop de posiciones pendientes iniciado")

        except Exception as e:
            self._logger.error(f"Error iniciando sistema: {str(e)}", exc_info=True)
            if self.notification_manager:
                await self.notification_manager.notify_system(
                    f"Error iniciando sistema: {str(e)}",
                    "error"
                )
            await self.stop()
            raise

    async def stop(self) -> None:
        """Detiene el sistema"""
        try:
            self._logger.info("Deteniendo sistema Copy Trading")
            self.is_running = False

            # Procesar posiciones pendientes
            pending_count = await self.queue_manager.pending_queue.get_pending_count() if self.queue_manager.pending_queue else 0
            if pending_count > 0:
                self._logger.info(f"Procesando {pending_count} posiciones pendientes...")

            # Detener QueueManager primero para que todas las tareas se cancelen
            if not self._queue_manager_stopped:
                try:
                    self._logger.debug("Deteniendo QueueManager...")
                    await self.queue_manager.stop()
                    self._queue_manager_stopped = True
                    self._logger.debug("QueueManager detenido")
                except Exception as e:
                    self._logger.error(f"Error deteniendo QueueManager: {e}")

            # Liberar recursos
            if self.validation_engine:
                self._logger.debug("Cerrando ValidationEngine...")
                await self.validation_engine.close()
                self._logger.info("Recursos de AccountInfo liberados en ValidationEngine")

            # Desconectar API
            if self.client:
                try:
                    self._logger.debug("Desconectando cliente API...")
                    await self.client.disconnect()
                    self._logger.debug("Cliente API desconectado")
                except Exception as e:
                    self._logger.error(f"Error desconectando PumpFunApiClient: {e}")

            # Liberar recursos del fetcher de datos de trading
            if self.trading_data_fetcher:
                self._logger.debug("Cerrando TradingDataFetcher...")
                await self.trading_data_fetcher.close()
                self._logger.debug("TradingDataFetcher cerrado")

            # Mostrar estadísticas finales
            stats = await self.get_metrics()
            self._log_final_stats(stats)

            self._logger.debug("Sistema detenido correctamente")

            # Enviar notificación de detención
            if self.notification_manager:
                stats_msg = (
                    f"Sistema detenido\n"
                    f"- Tiempo activo: ⏱️ {stats['system_metrics']['uptime_seconds']/3600:.1f}h\n"
                    f"- Trades ejecutados: ✅ {stats['system_metrics']['trades_executed']}\n"
                    f"- Volumen total: 💰 {stats['system_metrics']['total_volume_sol']:.6f} SOL"
                )
                await self.notification_manager.notify_system(stats_msg, "stopped")

            # Cancelar el loop de procesamiento de posiciones pendientes
            if self._pending_task:
                self._logger.debug("Cancelando loop de posiciones pendientes...")
                self._pending_task.cancel()
                try:
                    await self._pending_task
                except asyncio.CancelledError:
                    self._logger.debug("Loop de posiciones pendientes cancelado correctamente")
                except Exception as e:
                    self._logger.error(f"Error cancelando tarea de posiciones pendientes: {e}")
                finally:
                    self._pending_task = None

        except Exception as e:
            self._logger.error(f"Error deteniendo sistema: {e}")
            if self.notification_manager:
                error_msg = f"Error al detener sistema: {str(e)}"
                await self.notification_manager.notify_system(error_msg, "error")

    async def add_trader(self, trader_address: str):
        """
        Añade un nuevo trader a seguir
        
        Args:
            trader_address: Dirección del wallet del trader
        """
        self._logger.info(f"Añadiendo trader: {trader_address[:8]}...")
        
        trader_info = self.config.get_trader_info(trader_address)
        if not trader_info:
            trader_info = self.config.add_trader_by_wallet_address(trader_address)

            # Si el sistema está corriendo, actualizar suscripción
            if self.is_running and self.subscriptions:
                self._logger.debug("Actualizando suscripciones para incluir nuevo trader...")
                await self.subscriptions.unsubscribe_account_trade([trader.wallet_address for trader in self.config.traders[:-1]])
                await self.subscriptions.subscribe_account_trade(
                    account_addresses=[trader.wallet_address for trader in self.config.traders],
                    callback=self.trade_processor_callback,
                    use_api_key=True
                )
                self._logger.debug("Suscripciones actualizadas")

            self._logger.info(f"Trader añadido: {trader_address[:8]}...")
        else:
            self._logger.warning(f"Trader ya existe: {trader_address[:8]}...")

    async def remove_trader(self, trader_address: str):
        """
        Elimina un trader de la lista
        
        Args:
            trader_address: Dirección del wallet del trader
        """
        self._logger.info(f"Eliminando trader: {trader_address[:8]}...")
        
        trader_info = self.config.get_trader_info(trader_address)
        if trader_info:
            self.config.remove_trader_info(trader_info)

            # Si el sistema está corriendo, actualizar suscripción
            if self.is_running and self.subscriptions:
                self._logger.debug("Actualizando suscripciones para excluir trader...")
                await self.subscriptions.unsubscribe_account_trade([trader_address])
                if self.config.traders:  # Si quedan traders
                    await self.subscriptions.subscribe_account_trade(
                        account_addresses=[trader.wallet_address for trader in self.config.traders],
                        callback=self.trade_processor_callback,
                        use_api_key=True
                    )
                    self._logger.debug("Suscripciones actualizadas")
                else:
                    self._logger.debug("No quedan traders para suscribir")

            self._logger.info(f"Trader eliminado: {trader_address[:8]}...")
        else:
            self._logger.warning(f"Trader no encontrado: {trader_address[:8]}...")

    async def get_metrics(self) -> Dict[str, Any]:
        """Obtiene métricas del sistema"""
        # Actualizar uptime
        if self.start_time:
            self.metrics['uptime_seconds'] = (datetime.now() - self.start_time).total_seconds()

        if not self.trade_processor_callback:
            error_msg = "TradeProcessorCallback no inicializado"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        # Combinar con métricas del callback
        callback_stats = self.trade_processor_callback.get_stats()

        # Combinar con métricas de las colas
        queue_stats = await self.queue_manager.get_stats()

        # Obtener balance actual
        current_balance = 0.0
        if self.validation_engine and self.validation_engine.account_info and self.wallet_data:
            try:
                current_balance = await self.validation_engine.account_info.get_sol_balance(self.wallet_data.wallet_public_key)
                self._logger.debug(f"Balance actual obtenido: {current_balance} SOL")
            except Exception as e:
                # Error: registrar y continuar con balance 0
                if self._logger:
                    self._logger.warning(f"No se pudo obtener balance: {e}")

        # Obtener estado del cliente API centralizado
        client_status = self.client.get_status() if self.client else None

        return {
            'system_metrics': self.metrics,
            'callback_stats': callback_stats,
            'queue_stats': queue_stats,
            'client_status': client_status,
            'wallet_balance': current_balance,
            'is_running': self.is_running,
            'dry_run': self.config.dry_run,
            'traders_count': len(self.config.traders)
        }

    async def _notify_position_status_change(self, position_data: dict) -> None:
        """
        Callback para notificar cambios de estado de posiciones
        
        Args:
            position_data: Datos de la posición con el nuevo estado
        """
        if self.notification_manager:
            try:
                # Determinar el tipo de mensaje según el estado
                status = position_data.get('status', 'unknown')
                self._logger.debug(f"Notificando cambio de estado de posición: {status}")

                if status == 'open':
                    # Posición ejecutada exitosamente
                    await self.notification_manager.notify_trade({
                        'side': position_data['side'],
                        'token_address': position_data['token_address'],
                        'token_name': f"Token {position_data['token_address'][:8]}...",
                        'token_symbol': position_data.get('token_symbol', position_data['token_address'][:4].upper()),
                        'amount': position_data['amount'],
                        'status': 'executed',
                        'signature': position_data.get('execution_signature'),
                        'execution_price': position_data.get('execution_price', 0),
                        'amount_tokens': position_data.get('amount_tokens', 0),
                        'slippage': position_data.get('slippage', 0)
                    })

                elif status == 'closed':
                    # Posición cerrada
                    await self.notification_manager.notify_trade({
                        'side': position_data['side'],
                        'token_address': position_data['token_address'],
                        'token_name': f"Token {position_data['token_address'][:8]}...",
                        'token_symbol': position_data.get('token_symbol', position_data['token_address'][:4].upper()),
                        'amount': position_data['amount'],
                        'status': 'closed',
                        'signature': position_data.get('close_signature'),
                        'close_price': position_data.get('close_price', 0),
                        'close_amount_sol': position_data.get('close_amount_sol', 0),
                        'pnl': position_data.get('realized_pnl_sol', 0),
                        'pnl_usd': position_data.get('realized_pnl_usd', 0)
                    })

                elif status == 'failed':
                    # Posición falló
                    await self.notification_manager.notify_trade({
                        'side': position_data['side'],
                        'token_address': position_data['token_address'],
                        'token_name': f"Token {position_data['token_address'][:8]}...",
                        'token_symbol': position_data.get('token_symbol', position_data['token_address'][:4].upper()),
                        'amount': position_data['amount'],
                        'status': 'failed',
                        'error': position_data.get('error', 'Error desconocido')
                    })

                elif status == 'cancelled':
                    # Posición cancelada
                    await self.notification_manager.notify_trade({
                        'side': position_data['side'],
                        'token_address': position_data['token_address'],
                        'token_name': f"Token {position_data['token_address'][:8]}...",
                        'token_symbol': position_data.get('token_symbol', position_data['token_address'][:4].upper()),
                        'amount': position_data['amount'],
                        'status': 'cancelled'
                    })

            except Exception as e:
                self._logger.error(f"Error notificando cambio de estado de posición: {e}")

    async def _execute_trade(self, trade_data: PositionTraderTradeData) -> None:
        """
        Ejecuta un trade
        
        Args:
            position: Posición a ejecutar
        """
        try:
            self._logger.info(f"Ejecutando trade: {trade_data.side} {trade_data.token_address[:8]}... por {trade_data.copy_amount_sol} SOL")

            token_trading_info_task = asyncio.create_task(self.trading_data_fetcher.get_token_trading_info(trade_data.token_address))

            # Ejecutar trade usando execute_lightning_trade
            signature = None
            if self.config.transaction_type == TransactionType.LIGHTNING_TRADE:
                if not self.transactions_manager:
                    error_msg = "TransactionsManager no inicializado"
                    self._logger.error(error_msg)
                    raise ValueError(error_msg)

                self._logger.debug(f"Ejecutando lightning trade para {trade_data.token_address[:8]}...")
                result = await self.transactions_manager.execute_lightning_trade(
                    action=trade_data.side,  # "buy" o "sell"
                    mint=trade_data.token_address,
                    amount=trade_data.copy_amount_sol,
                    denominated_in_sol=True,
                    slippage=str(self.config.slippage_tolerance),
                    priority_fee=str(self.config.priority_fee_sol),
                    pool=trade_data.pool, # type: ignore
                    skip_preflight=True
                )
                signature = result.get('signature')
                self._logger.debug(f"Resultado lightning trade: {result}")

            elif self.config.transaction_type == TransactionType.LOCAL_TRADE:
                if not self.transactions_manager:
                    error_msg = "TransactionsManager no inicializado"
                    self._logger.error(error_msg)
                    raise ValueError(error_msg)
                if not self.wallet_data:
                    error_msg = "WalletData no inicializado"
                    self._logger.error(error_msg)
                    raise ValueError(error_msg)

                self._logger.debug(f"Ejecutando local trade para {trade_data.token_address[:8]}...")
                signature = await self.transactions_manager.create_and_send_local_trade(
                    keypair=self.wallet_data.get_keypair(),
                    action=trade_data.side,
                    mint=trade_data.token_address,
                    amount=trade_data.copy_amount_sol,
                    denominated_in_sol=True,
                    slippage=str(self.config.slippage_tolerance),
                    priority_fee=str(self.config.priority_fee_sol),
                    pool=trade_data.pool, # type: ignore
                    rpc_endpoint=self.config.rpc_url
                )
                self._logger.debug(f"Local trade completado, signature: {signature}")

            if signature:
                self._logger.info(f"Trade ejecutado exitosamente ({self.config.transaction_type.value}): {trade_data.signature}")

                # Incrementar métricas de ejecución
                self.metrics['trades_executed'] += 1
                self.metrics['total_volume_sol'] += float(trade_data.copy_amount_sol)
                self._logger.debug(f"Métricas actualizadas: trades_executed={self.metrics['trades_executed']}, total_volume={self.metrics['total_volume_sol']}")

                entry_price = ""
                token_trading_info = await token_trading_info_task
                if token_trading_info:
                    entry_price = token_trading_info['sol_per_token']
                    self._logger.debug(f"Precio de entrada obtenido: {entry_price}")
                else:
                    self._logger.warning(f"❌ No se pudo obtener el token trading info para {trade_data.token_address}")

                await self.queue_manager.process_executed_position(trade_data, signature, entry_price)

            else:
                error_msg = f"❌ Error ejecutando trade ({self.config.transaction_type.value})"
                if self.config.transaction_type == TransactionType.LIGHTNING_TRADE:
                    error_msg += f": {result.get('error', 'Unknown error')}"
                self._logger.error(error_msg)

        except Exception as e:
            self._logger.error(f"Error inesperado ejecutando trade ({self.config.transaction_type.value}): {e}", exc_info=True)

    async def _pending_positions_loop(self):
        """
        Loop asíncrono que procesa y ejecuta las posiciones pendientes
        """
        self._logger.debug("Iniciando loop de procesamiento de posiciones pendientes")
        while self.is_running:
            try:
                position = await self.queue_manager.get_next_pending()
                if position:
                    self._logger.debug(f"Procesando posición pendiente: {position.token_address[:8]}...")
                    await self._execute_trade(position)

                # Espera un poco entre ejecuciones para evitar rate limits
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                # Salir del bucle si la tarea es cancelada
                self._logger.debug("Loop de posiciones pendientes cancelado")
                break
            except Exception as e:
                self._logger.error(f"Error en el loop de ejecución de trades: {e}", exc_info=True)
                # Esperar antes de reintentar para no sobrecargar en caso de error continuo
                await asyncio.sleep(5)

    async def _process_pending_positions(self):
        """Procesa posiciones pendientes en la cola"""
        try:
            # Este método ya no es necesario ya que el procesamiento 
            # se maneja automáticamente en el loop de _pending_positions_loop
            self._logger.debug("_process_pending_positions llamado (método obsoleto)")
            pass

        except Exception as e:
            self._logger.error(f"Error procesando posiciones pendientes: {str(e)}")

    def _log_final_stats(self, stats: Dict[str, Any]):
        """Log de estadísticas finales"""
        if self.start_time:
            uptime = (datetime.now() - self.start_time).total_seconds()

            self._logger.info("📊 Estadísticas finales:")
            self._logger.info(f"  • Tiempo activo: {uptime/3600:.1f}h")
            self._logger.info(f"  • Trades procesados: {self.metrics['trades_processed']}")
            self._logger.info(f"  • Trades ejecutados: {self.metrics['trades_executed']}")
            vol = self.metrics['total_volume_sol']
            if vol < 1e-6 and vol > 0:
                self._logger.info(f"  • Volumen total: {vol:.12f} SOL")
            else:
                self._logger.info(f"  • Volumen total: {vol:.6f} SOL")

            # Estadísticas del cliente API
            if self.client:
                client_status = self.client.get_status()
                self._logger.info("📡 Estadísticas del cliente API:")
                self._logger.info(f"  • Peticiones HTTP: {client_status.get('request_count', 0)}")
                self._logger.info(f"  • Errores: {client_status.get('error_count', 0)}")
                self._logger.info(f"  • Mensajes WebSocket: {client_status.get('websocket_messages_received', 0)}")
                self._logger.info(f"  • Suscripciones activas: {client_status.get('active_subscriptions', 0)}")

    async def get_wallet_info(self) -> Dict[str, Any]:
        """Obtiene información de la wallet actual"""
        if not self.config.wallet_file:
            self._logger.warning("No hay archivo de wallet configurado")
            return {'error': 'No hay archivo de wallet configurado'}
        if not self.wallet_data:
            self._logger.warning("WalletData no inicializado")
            return {'error': 'WalletData no inicializado'}

        wallet_info = self.wallet_data.get_short_info()
        self._logger.debug("Información de wallet obtenida")

        # Añadir información del cliente API centralizado
        if self.client:
            wallet_info['client_status'] = self.client.get_status() # type: ignore
            self._logger.debug("Estado del cliente API añadido a la información de wallet")

        return wallet_info

    async def get_client_status(self) -> Dict[str, Any]:
        """
        Obtiene el estado del cliente API centralizado
        
        Returns:
            Estado del cliente API
        """
        if not self.client:
            self._logger.warning("Cliente API no inicializado")
            return {'error': 'Cliente API no inicializado'}

        status = self.client.get_status()
        self._logger.debug("Estado del cliente API obtenido")
        return status

    async def reset_client_metrics(self):
        """Resetea las métricas del cliente API centralizado"""
        if self.client:
            self.client.reset_metrics()
            self._logger.info("Métricas del cliente API reseteadas")
        else:
            self._logger.warning("No se pueden resetear métricas: cliente API no inicializado")
