# -*- coding: utf-8 -*-
"""
Sistema principal de Copy Trading
"""
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio

from pumpfun.api_client import PumpFunHttpApiClient, PumpFunWebSocketApiClient
from pumpfun.transactions import PumpFunTransactions
from pumpfun.subscriptions import PumpFunSubscriptions
from pumpfun.wallet_manager import PumpFunWalletStorage, WalletData, WalletImportException
from logging_system import AppLogger

from .config import CopyTradingConfig
from .validation import ValidationEngine
from .balance_management import BalanceManager
from .callbacks import TradeProcessorCallback
from .position_management import PositionQueueManager
from .position_management.models import PositionTraderTradeData
from .events import PositionEventBus, PositionExecutionFailedEvent
from .data_management import (
    TokenTraderManager, 
    TradingDataFetcher, 
    SolanaTxAnalyzer, 
    SolanaWebsocketManager,
    TradingDataStore
)
from .notifications import (
    NotificationManager,
    TelegramStrategy,
    ConsoleStrategy
)
from .transactions_management import TransactionExecutor, CopyAmountCalculator, Liquidations


class CopyTrading:
    """Sistema principal de copy trading"""

    def __init__(self, config: CopyTradingConfig):
        """
        Inicializa el sistema de copy trading
        
        Args:
            config: Configuración del sistema
        """
        self.config = config

        # Inicializar logger
        self._logger = AppLogger(self.__class__.__name__)
        self._logger.info("Inicializando sistema Copy Trading")

        # Inicializar PositionEventBus
        self.position_event_bus = PositionEventBus()
        self._logger.debug("PositionEventBus inicializado")

        # Inicializar TradingDataFetcher
        self.trading_data_fetcher = TradingDataFetcher(rpc_url=config.rpc_url)
        self._logger.debug("TradingDataFetcher inicializado")

        # Inicializar TradingDataStore
        self.trading_data_store = TradingDataStore()
        self._logger.debug("TradingDataStore inicializado")

        # Inicializar TokenTraderManager
        self.token_trader_manager = TokenTraderManager(
            config=config,
            trading_data_fetcher=self.trading_data_fetcher,
            trading_data_store=self.trading_data_store
        )
        self._logger.debug("TokenTraderManager inicializado")

        # Inicializar notificaciones
        self.notification_manager = self._setup_notifications()
        if self.notification_manager:
            self._logger.debug("Sistema de notificaciones configurado")
        else:
            self._logger.debug("Sistema de notificaciones deshabilitado")

        # Inicializar SolanaTxAnalyzer
        self.solana_analyzer = SolanaTxAnalyzer(endpoint=config.rpc_url)
        self.solana_websocket = SolanaWebsocketManager(ws_url=config.websocket_url)

        # Balance manager centralizado (antes de crear colas/managers para inyectarlo)
        self.balance_manager = BalanceManager(
            config=config,
            solana_analyzer=self.solana_analyzer,
            position_event_bus=self.position_event_bus
        )

        self.queue_manager = PositionQueueManager(
            config=config,
            solana_analyzer=self.solana_analyzer,
            solana_websocket=self.solana_websocket,
            trading_data_fetcher=self.trading_data_fetcher,
            token_trader_manager=self.token_trader_manager,
            balance_manager=self.balance_manager,
            position_event_bus=self.position_event_bus,
            notification_manager=self.notification_manager
        )
        self._logger.debug("PositionQueueManager inicializado")

        self.validation_engine = ValidationEngine(
            config=config,
            token_trader_manager=self.token_trader_manager,
            balance_manager=self.balance_manager
        )
        self._logger.debug("ValidationEngine inicializado")

        self.amount_calculator = CopyAmountCalculator(
            config=config,
            position_event_bus=self.position_event_bus
        )
        self._logger.debug("CopyAmountCalculator inicializado")

        # Cliente API centralizado (se configurará en start())
        self.http_client: Optional[PumpFunHttpApiClient] = None
        self.ws_client: Optional[PumpFunWebSocketApiClient] = None

        # Wallet data
        self.wallet_data: Optional[WalletData] = None

        self.subscriptions: Optional[PumpFunSubscriptions] = None
        self.transactions_manager: Optional[PumpFunTransactions] = None

        # Transaction executor (se inicializará en start())
        self.transaction_executor: Optional[TransactionExecutor] = None

        # Liquidations
        self.liquidations: Optional[Liquidations] = None

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

        self._logger.debug("Sistema Copy Trading inicializado correctamente")

    async def __aenter__(self):
        """Context manager entry"""
        self._logger.debug("Entrando en context manager")
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

            # Inicializar QueueManager con context manager
            await self.queue_manager.start()

            # Inyectar open_position_queue a amount_calculator
            self.amount_calculator.set_open_position_queue(self.queue_manager.open_queue)

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
            self.http_client = PumpFunHttpApiClient(api_key=self.wallet_data.api_key)
            await self.http_client.connect()
            self._logger.debug("Cliente API conectado")

            # Conectar cliente WebSocket
            self.ws_client = PumpFunWebSocketApiClient(api_key=self.wallet_data.api_key)
            await self.ws_client.connect()
            self._logger.debug("Cliente WebSocket conectado")

            # Inicializar SolanaTxAnalyzer
            await self.solana_analyzer.__aenter__()
            self._logger.debug("SolanaTxAnalyzer inicializado")

            # Inicializar SolanaWebsocketManager
            await self.solana_websocket.__aenter__()
            self._logger.debug("SolanaWebsocketManager inicializado")

            # Inicializar BalanceManager (maneja SolanaAccountInfo) y luego ValidationEngine
            self._logger.debug("Inicializando BalanceManager...")
            await self.balance_manager.start(system_wallet_address=self.wallet_data.wallet_public_key)
            self._logger.debug("BalanceManager inicializado")

            # Initialize transaction manager con el cliente centralizado
            self.transactions_manager = PumpFunTransactions(api_client=self.http_client, api_key=self.wallet_data.api_key)
            self._logger.debug("PumpFunTransactions inicializado")

            # Inicializar TransactionExecutor
            self.transaction_executor = TransactionExecutor(
                config=self.config,
                transactions_manager=self.transactions_manager,
                wallet_data=self.wallet_data
            )
            self._logger.debug("TransactionExecutor inicializado")

            # Inicializar Liquidations
            self.liquidations = Liquidations(
                system_wallet_address=self.wallet_data.wallet_public_key,
                solana_analyzer=self.solana_analyzer,
                transaction_executor=self.transaction_executor,
                position_queue_manager=self.queue_manager
            )
            self._logger.debug("Liquidations inicializado")

            # Inicializar subscriptions con el cliente centralizado
            self.subscriptions = PumpFunSubscriptions(ws_client=self.ws_client)
            self._logger.debug("PumpFunSubscriptions inicializado")

            if not self.queue_manager.pending_queue:
                error_msg = "PendingPositionQueue no inicializado"
                self._logger.error(error_msg)
                raise ValueError(error_msg)

            # Inicializar TokenTraderManager
            self._logger.debug("Inicializando TokenTraderManager...")
            await self.token_trader_manager.initialize_system_trader_stats()
            self._logger.debug("TokenTraderManager inicializado")

            # Inicializar callback después de que las colas estén listas
            self._logger.debug("Inicializando TradeProcessorCallback...")
            self.trade_processor_callback = TradeProcessorCallback(
                config=self.config,
                pending_position_queue=self.queue_manager.pending_queue,
                validation_engine=self.validation_engine,
                token_trader_manager=self.token_trader_manager,
                amount_calculator=self.amount_calculator,
                position_event_bus=self.position_event_bus,
                open_position_queue=self.queue_manager.open_queue
            )
            self._logger.debug("TradeProcessorCallback inicializado")

            # Suscribirse a trades de los traders
            trader_addresses = [trader.wallet_address for trader in self.config.traders]
            self._logger.debug(f"Suscribiendo a {len(trader_addresses)} traders: {[addr[:8] + '...' for addr in trader_addresses]}")
            await self.subscriptions.subscribe_account_trade(
                account_addresses=trader_addresses,
                callback=self.trade_processor_callback,
            )

            self._logger.debug(f"Suscrito a {len(self.config.traders)} traders")

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
            # Cerrar callback
            if self.trade_processor_callback:
                await self.trade_processor_callback.shutdown()
                self._logger.debug("TradeProcessorCallback cerrado")

            if self.liquidations:
                await self.liquidations.run()
                self._logger.debug("Liquidaciones detenidas")

            self.is_running = False

            # Procesar posiciones pendientes
            pending_count = await self.queue_manager.pending_queue.get_pending_count() if self.queue_manager.pending_queue else 0
            if pending_count > 0:
                self._logger.info(f"Procesando {pending_count} posiciones pendientes...")

            # Detener QueueManager primero para que todas las tareas se cancelen
            try:
                self._logger.debug("Deteniendo QueueManager...")
                await self.queue_manager.stop()
                self._logger.debug("QueueManager detenido")
            except Exception as e:
                self._logger.error(f"Error deteniendo QueueManager: {e}")

            # Liberar recursos
            if self.solana_analyzer:
                await self.solana_analyzer.__aexit__(None, None, None)
                self._logger.debug("SolanaTxAnalyzer cerrado")

            if self.solana_websocket:
                await self.solana_websocket.__aexit__(None, None, None)
                self._logger.debug("SolanaWebsocketManager cerrado")

            if self.balance_manager:
                try:
                    self._logger.debug("Cerrando BalanceManager...")
                    await self.balance_manager.stop()
                    self._logger.debug("BalanceManager cerrado")
                except Exception as e:
                    self._logger.error(f"Error cerrando BalanceManager: {e}")

            # Desconectar API
            if self.http_client:
                try:
                    self._logger.debug("Desconectando cliente API...")
                    await self.http_client.disconnect()
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

            self._logger.warning("Sistema detenido correctamente")

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
        if self.balance_manager and self.wallet_data:
            try:
                current_balance = await self.balance_manager.get_sol_balance()
                self._logger.debug(f"Balance actual obtenido: {current_balance} SOL")
            except Exception as e:
                # Error: registrar y continuar con balance 0
                if self._logger:
                    self._logger.warning(f"No se pudo obtener balance: {e}")

        # Obtener estado del cliente API centralizado
        client_status = self.http_client.get_status() if self.http_client else None

        # Obtener información del TransactionExecutor
        transaction_info = self.transaction_executor.get_transaction_type_info() if self.transaction_executor else None

        return {
            'system_metrics': self.metrics,
            'callback_stats': callback_stats,
            'queue_stats': queue_stats,
            'client_status': client_status,
            'transaction_info': transaction_info,
            'wallet_balance': current_balance,
            'is_running': self.is_running,
            'dry_run': self.config.dry_run,
            'traders_count': len(self.config.traders)
        }

    async def _execute_trade(self, trade_data: PositionTraderTradeData) -> None:
        """
        Ejecuta un trade usando el TransactionExecutor
        
        Args:
            trade_data: Datos del trade a ejecutar
        """
        if not self.transaction_executor:
            error_msg = "TransactionExecutor no inicializado"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        try:
            # Ejecutar trade usando el TransactionExecutor (incluye obtención de precio de entrada)
            success, signature, error_message = await self.transaction_executor.execute_trade(trade_data)

            if success and signature:
                # Incrementar métricas de ejecución
                self.metrics['trades_executed'] += 1
                if trade_data.side == "buy":
                    self.metrics['total_volume_sol'] += float(trade_data.copy_amount_sol)
                self._logger.debug(f"Métricas actualizadas: trades_executed={self.metrics['trades_executed']}, total_volume={self.metrics['total_volume_sol']}")

                # Procesar posición ejecutada
                await self.queue_manager.process_executed_position(trade_data, signature)
            else:
                self._logger.error(f"Error ejecutando trade: {error_message or 'Error desconocido'}")
                self.position_event_bus.emit_position_execution_failed(
                    PositionExecutionFailedEvent(
                        position_id=trade_data.id,
                        token_address=trade_data.token_address,
                        trader_wallet=trade_data.trader_wallet,
                        error_message=error_message or "Error desconocido"
                    )
                )

        except Exception as e:
            self._logger.error(f"Error inesperado ejecutando trade: {e}", exc_info=True)
            self.position_event_bus.emit_position_execution_failed(
                PositionExecutionFailedEvent(
                    position_id=trade_data.id,
                    token_address=trade_data.token_address,
                    trader_wallet=trade_data.trader_wallet,
                    error_message=str(e)
                )
            )

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
            except asyncio.CancelledError:
                # Salir del bucle si la tarea es cancelada
                self._logger.debug("Loop de posiciones pendientes cancelado")
                break
            except Exception as e:
                self._logger.error(f"Error en el loop de ejecución de trades: {e}", exc_info=True)
                # Esperar antes de reintentar para no sobrecargar en caso de error continuo
                await asyncio.sleep(1)

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
            if self.http_client:
                client_status = self.http_client.get_status()
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
        if self.http_client:
            wallet_info['client_status'] = self.http_client.get_status() # type: ignore
            self._logger.debug("Estado del cliente API añadido a la información de wallet")

        return wallet_info

    async def get_client_status(self) -> Dict[str, Any]:
        """
        Obtiene el estado del cliente API centralizado
        
        Returns:
            Estado del cliente API
        """
        if not self.http_client:
            self._logger.warning("Cliente API no inicializado")
            return {'error': 'Cliente API no inicializado'}

        status = self.http_client.get_status()
        self._logger.debug("Estado del cliente API obtenido")
        return status

    async def reset_client_metrics(self):
        """Resetea las métricas del cliente API centralizado"""
        if self.http_client:
            self.http_client.reset_metrics()
            self._logger.info("Métricas del cliente API reseteadas")
        else:
            self._logger.warning("No se pueden resetear métricas: cliente API no inicializado")
