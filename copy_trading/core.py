# -*- coding: utf-8 -*-
"""
Sistema principal de Copy Trading
"""
from typing import Dict, Any, Optional
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
import asyncio

from pumpfun.api_client import PumpFunHttpApiClient, PumpFunWebSocketApiClient
from pumpfun.transactions import PumpFunTransactions
from pumpfun.subscriptions import PumpFunSubscriptions
from pumpfun.wallet_manager import PumpFunWalletStorage, WalletData, WalletImportException
from logging_system import AppLogger

from .config import CopyTradingConfig
from .validation import ValidationEngine
from .balance_management import BalanceManager
from .callbacks import TradeProcessorCallback, MinimumBalanceHandler, DryRunMinimumBalanceHandler, MinimumBalanceHandlerProtocol
from .position_management import PositionQueueManager
from .position_management.models import PositionTraderTradeData
from .events import PositionEventBus, PositionExecutionFailedEvent, PositionFailedEvent
from .data_management import (
    TokenTraderManager, 
    TradingDataFetcher, 
    SolanaTxAnalyzer, 
    SolanaWebsocketManager,
    TradingDataStore,
    PumpFunRedisSubscriptions
)
from .data_management.solana_manager import DryRunSolanaTxAnalyzer, DryRunSolanaWebsocketManager
from .notifications import (
    NotificationManager,
    TelegramStrategy,
    ConsoleStrategy
)
from .transactions_management import (
    TransactionExecutor,
    CopyAmountCalculator,
    Liquidations,
    DryRunTransactionExecutor,
    TransactionExecutorProtocol,
    DryRunLiquidations,
    LiquidationsProtocol
)
from .position_timeout import PositionTimeoutManager
from .data_management import MoralisPriceClient
from .persistence.repositories import TraderMintRepository, CopyTradingBotRepository, RunRepository, PNLRepository
from .persistence.subscribers import attach_position_events_subscriber, attach_mint_events_subscriber


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

        # Inicializar MoralisPriceClient
        self.moralis_client = MoralisPriceClient()
        self._logger.debug("MoralisPriceClient inicializado")

        # Inicializar TradingDataStore
        self.trading_data_store = TradingDataStore()
        self._logger.debug("TradingDataStore inicializado")

        # Inicializar TokenTraderManager
        self.token_trader_manager = TokenTraderManager(
            config=config,
            trading_data_fetcher=self.trading_data_fetcher,
            trading_data_store=self.trading_data_store,
            position_event_bus=self.position_event_bus
        )
        self._logger.debug("TokenTraderManager inicializado")

        # Inicializar notificaciones
        self.notification_manager = self._setup_notifications()
        if self.notification_manager:
            self._logger.debug("Sistema de notificaciones configurado")
        else:
            self._logger.debug("Sistema de notificaciones deshabilitado")

        if self.config.dry_run:
            self.solana_analyzer = DryRunSolanaTxAnalyzer(config=config)
            self.solana_websocket = DryRunSolanaWebsocketManager(ws_url=config.websocket_url)
        else:
            self.solana_analyzer = SolanaTxAnalyzer(endpoint=config.rpc_url)
            self.solana_websocket = SolanaWebsocketManager(ws_url=config.websocket_url)

        # Balance manager centralizado (antes de crear colas/managers para inyectarlo)
        self.balance_manager = BalanceManager(
            config=config,
            solana_analyzer=self.solana_analyzer,
            position_event_bus=self.position_event_bus
        )

        pnl_repository = PNLRepository()

        self.queue_manager = PositionQueueManager(
            config=config,
            solana_analyzer=self.solana_analyzer,
            solana_websocket=self.solana_websocket,
            trading_data_fetcher=self.trading_data_fetcher,
            token_trader_manager=self.token_trader_manager,
            balance_manager=self.balance_manager,
            position_event_bus=self.position_event_bus,
            notification_manager=self.notification_manager,
            pnl_repository=pnl_repository
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
            position_event_bus=self.position_event_bus,
            solana_analyzer=self.solana_analyzer,
            balance_manager=self.balance_manager
        )
        self._logger.debug("CopyAmountCalculator inicializado")

        # Cliente API centralizado (se configurará en start())
        self.http_client: Optional[PumpFunHttpApiClient] = None
        self.ws_client: Optional[PumpFunWebSocketApiClient] = None

        # Wallet data
        self.wallet_data: Optional[WalletData] = None

        self.subscriptions: Optional[PumpFunSubscriptions] = None
        self.redis_subscriptions: Optional[PumpFunRedisSubscriptions] = None
        self.transactions_manager: Optional[PumpFunTransactions] = None

        # Transaction executor (se inicializará en start())
        self.transaction_executor: Optional[TransactionExecutorProtocol] = None

        # Liquidations
        self.liquidations: Optional[LiquidationsProtocol] = None

        # Position Timeout Manager
        self.position_timeout_manager: Optional[PositionTimeoutManager] = None

        # Callback (se inicializará después de que las colas estén listas)
        self.trade_processor_callback: Optional[TradeProcessorCallback] = None

        # Minimum balance handler
        self.minimum_balance_handler: Optional[MinimumBalanceHandlerProtocol] = None

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

            # Inicializar NotificationManager
            if self.notification_manager:
                self._logger.debug("Inicializando NotificationManager...")
                await self.notification_manager.start()
                self._logger.debug("NotificationManager inicializado")

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
            if self.config.use_pumpfun_redis_bridge:
                redis_url = self.config.pumpfun_redis_url or "redis://localhost:6379/0"
                self._logger.debug(
                    f"Inicializando PumpFunRedisSubscriptions ({redis_url}, namespace={self.config.pumpfun_redis_namespace})"
                )
                self.redis_subscriptions = PumpFunRedisSubscriptions(
                    redis_url=redis_url,
                    namespace=self.config.pumpfun_redis_namespace,
                    client_id=self.config.pumpfun_redis_client_id or f"copytrading-{self.config.system_run_id}",
                    ack_timeout=float(self.config.pumpfun_redis_ack_timeout_seconds),
                )
                await self.redis_subscriptions.start()
                self._logger.debug("PumpFunRedisSubscriptions iniciado")
            else:
                self.ws_client = PumpFunWebSocketApiClient(api_key=self.wallet_data.api_key)
                await self.ws_client.connect()
                self._logger.debug("Cliente WebSocket conectado")
                self.subscriptions = PumpFunSubscriptions(ws_client=self.ws_client)
                self._logger.debug("Sistema de suscripciones PumpFun inicializado")

            # Inicializar SolanaTxAnalyzer
            self.solana_analyzer.set_system_wallet_address(self.wallet_data.wallet_public_key)
            await self.solana_analyzer.__aenter__()
            self._logger.debug("SolanaTxAnalyzer inicializado")

            # Inicializar SolanaWebsocketManager
            await self.solana_websocket.__aenter__()
            self._logger.debug("SolanaWebsocketManager inicializado")

            # Inicializar BalanceManager (maneja SolanaAccountInfo) y luego ValidationEngine
            self._logger.debug("Inicializando BalanceManager...")
            await self.balance_manager.start(system_wallet_address=self.wallet_data.wallet_public_key)
            self._logger.debug("BalanceManager inicializado")

            # Inicializar MoralisPriceClient
            await self.moralis_client.start()
            self._logger.debug("MoralisPriceClient inicializado")

            if self.config.dry_run:
                self.transaction_executor = DryRunTransactionExecutor(
                    config=self.config,
                    moralis_client=self.moralis_client,
                    position_event_bus=self.position_event_bus
                )

                self.liquidations = DryRunLiquidations(
                    system_wallet_address=self.wallet_data.wallet_public_key,
                    solana_analyzer=self.solana_analyzer,
                    transaction_executor=self.transaction_executor,
                    position_queue_manager=self.queue_manager
                )
                self._logger.debug("DryRunLiquidations inicializado")
            else:
                # Initialize transaction manager con el cliente centralizado
                self.transactions_manager = PumpFunTransactions(api_client=self.http_client, api_key=self.wallet_data.api_key)
                self._logger.debug("PumpFunTransactions inicializado")

                # Inicializar TransactionExecutor
                self.transaction_executor = TransactionExecutor(
                    config=self.config,
                    transactions_manager=self.transactions_manager,
                    wallet_data=self.wallet_data,
                    position_event_bus=self.position_event_bus
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

            # Inicializar PositionTimeoutManager (tanto para dry_run como live)
            if self.config.position_timeout_enabled:
                self.position_timeout_manager = PositionTimeoutManager(
                    config=self.config,
                    position_queue_manager=self.queue_manager,
                    transaction_executor=self.transaction_executor,
                    position_event_bus=self.position_event_bus,
                    system_wallet_address=self.wallet_data.wallet_public_key
                )
                await self.position_timeout_manager.start()
                self._logger.debug("PositionTimeoutManager inicializado y ejecutándose")


            if not self.queue_manager.pending_queue:
                error_msg = "PendingPositionQueue no inicializado"
                self._logger.error(error_msg)
                raise ValueError(error_msg)

            # Inicializar TokenTraderManager
            self._logger.debug("Inicializando TokenTraderManager...")
            await self.token_trader_manager.initialize_system_trader_stats()
            self._logger.debug("TokenTraderManager inicializado")

            # Inicializar suscriptores de eventos
            attach_position_events_subscriber(self.position_event_bus)
            attach_mint_events_subscriber(self.position_event_bus)

            # Persistir entidades iniciales (traders/mints) provenientes de la configuración/cache
            await self._persist_initial_config_entities()

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

            # Inicializar MinimumBalanceHandler
            self._logger.debug("Inicializando MinimumBalanceHandler...")
            if self.config.dry_run:
                self.minimum_balance_handler = DryRunMinimumBalanceHandler(
                    system_wallet_address=self.wallet_data.wallet_public_key,
                    transaction_executor=self.transaction_executor,
                    position_queue_manager=self.queue_manager
                )
                self._logger.debug("MinimumBalanceHandler inicializado")
            elif isinstance(self.transaction_executor, TransactionExecutor):
                self.minimum_balance_handler = MinimumBalanceHandler(
                system_wallet_address=self.wallet_data.wallet_public_key,
                transaction_executor=self.transaction_executor,
                position_queue_manager=self.queue_manager
                )
                self._logger.debug("[DRY RUN] MinimumBalanceHandler inicializado")
            else:
                self._logger.error("TransactionExecutor no inicializado")
                raise ValueError("TransactionExecutor no inicializado")

            # Obtener addresses de los traders
            trader_addresses = [trader.wallet_address for trader in self.config.traders]

            # Establecer callback de errores y suscribirse a trades
            if self.config.use_pumpfun_redis_bridge and self.redis_subscriptions:
                #self.redis_subscriptions.set_error_callback(self.minimum_balance_handler)
                #self._logger.debug("Callback de errores registrado en consumidor Redis")
                # Suscribirse a trades de los traders
                self._logger.debug(f"Suscribiendo a {len(trader_addresses)} traders: {[addr[:8] + '...' for addr in trader_addresses]}")
                await self.redis_subscriptions.subscribe_account_trade(
                    account_addresses=trader_addresses,
                    callback=self.trade_processor_callback,
                )
                self._logger.debug(f"Suscrito a {len(self.config.traders)} traders")
            elif self.subscriptions and self.ws_client:
                self.ws_client.set_error_callback(self.minimum_balance_handler)
                self._logger.debug("Callback de errores en WebSocket registrado")
                # Suscribirse a trades de los traders
                self._logger.debug(f"Suscribiendo a {len(trader_addresses)} traders: {[addr[:8] + '...' for addr in trader_addresses]}")
                await self.subscriptions.subscribe_account_trade(
                    account_addresses=trader_addresses,
                    callback=self.trade_processor_callback,
                )
                self._logger.debug(f"Suscrito a {len(self.config.traders)} traders")
            else:
                self._logger.error("No se puede establecer callback de errores ni suscribirse a trades")
                raise ValueError("No se puede establecer callback de errores ni suscribirse a trades")

            # Actualizar estado
            self.is_running = True
            self.start_time = datetime.now()

            self._logger.debug("Sistema iniciado correctamente")

            # Notificar inicio del sistema
            if self.notification_manager:
                status_msg = (
                    f"Sistema iniciado correctamente\n"
                    f"- Modo: {'🔄 DRY RUN' if self.config.dry_run else '🚀 LIVE'}\n"
                    f"- Traders: 👥 {len(self.config.traders)}"
                )
                await self.notification_manager.notify_system(status_msg, "success")

            # Mostrar mensaje de modo de trading
            self.trading_mode_message()

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
            # Desuscribir y desconectar WebSocket de PumpFun para detener pings
            try:
                if self.config.use_pumpfun_redis_bridge and self.redis_subscriptions:
                    self._logger.debug("Desconectando consumidor Redis de PumpFun...")
                    await self.redis_subscriptions.disconnect()
                    self._logger.debug("Consumidor Redis de PumpFun desconectado")
                elif self.subscriptions and self.ws_client:
                    self._logger.debug("Desconectando cliente WebSocket de PumpFun...")
                    await self.subscriptions.disconnect()
                    self._logger.debug("Interfaz de suscripciones PumpFun desconectada")
                    await self.ws_client.disconnect()
                    self._logger.debug("Cliente WebSocket de PumpFun desconectado")
                else:
                    self._logger.error("No se puede desconectar WebSocket de PumpFun")
                    raise ValueError("No se puede desconectar WebSocket de PumpFun")
            except Exception as e:
                self._logger.error(f"Error desconectando PumpFun: {e}")

            # Cerrar callback
            if self.trade_processor_callback:
                await self.trade_processor_callback.shutdown()
                self._logger.debug("TradeProcessorCallback cerrado")

            if self.liquidations:
                await self.liquidations.run()
                self._logger.debug("Liquidaciones detenidas")

            # Detener PositionTimeoutManager
            if self.position_timeout_manager:
                try:
                    await self.position_timeout_manager.stop()
                    self._logger.debug("PositionTimeoutManager detenido")
                except Exception as e:
                    self._logger.error(f"Error deteniendo PositionTimeoutManager: {e}")

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

            total_pnl = await self._get_total_pnl()

            if self.balance_manager:
                try:
                    self._logger.debug("Cerrando BalanceManager...")
                    await self.balance_manager.stop()
                    self._logger.debug("BalanceManager cerrado")
                except Exception as e:
                    self._logger.error(f"Error cerrando BalanceManager: {e}")

            # Cerrar MoralisPriceClient
            if self.moralis_client:
                await self.moralis_client.stop()
                self._logger.debug("MoralisPriceClient cerrado")

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
                self._logger.info(f"Total P&L: {total_pnl['pnl_sol']} SOL = {total_pnl['pnl_usd']} USD ({total_pnl['pnl_percent']}%)")

                # Construct P&L message
                pnl_sol_val = Decimal(total_pnl['pnl_sol'])

                # Determine if profit or loss
                if pnl_sol_val >= 0:
                    emoji_pnl = "📈"
                    status_text = "PROFIT"
                else:
                    emoji_pnl = "📉"
                    status_text = "LOSS"

                pnl_msg = (
                    f"{emoji_pnl} <b>Total P&L</b>\n\n"
                    f"💰 <b>Balance Summary</b>\n"
                    f"{'─'*12}\n"
                    f"💼 <b>Initial:</b> {total_pnl['initial_balance_sol']} SOL (${total_pnl['initial_balance_usd']})\n"
                    f"💎 <b>Current:</b> {total_pnl['current_balance_sol']} SOL (${total_pnl['current_balance_usd']})\n"
                    f"💵 <b>SOL Price:</b> ${total_pnl['sol_price']}\n\n"
                    f"{emoji_pnl} <b>{status_text}</b>\n"
                    f"{'─'*12}\n"
                    f"🔸 <b>SOL:</b> {total_pnl['pnl_sol']} SOL\n"
                    f"💵 <b>USD:</b> ${total_pnl['pnl_usd']}\n"
                    f"📊 <b>Return:</b> {total_pnl['pnl_percent']}%"
                )
                await self.notification_manager.notify_system(pnl_msg, "info")

                stats_msg = (
                    f"System stopped\n"
                    f"- Uptime: ⏱️ {stats['system_metrics']['uptime_seconds']/3600:.1f}h\n"
                    f"- Trades executed: ✅ {stats['system_metrics']['trades_executed']}\n"
                    f"- Total volume: 💰 {stats['system_metrics']['total_volume_sol']:.6f} SOL"
                )
                await self.notification_manager.notify_system(stats_msg, "stopped")

                # Cerrar NotificationManager
                self._logger.debug("Cerrando NotificationManager...")
                await self.notification_manager.stop()
                self._logger.debug("NotificationManager cerrado")

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

            # Setear ended en el run
            run_repo = RunRepository()
            run = await run_repo.get(self.config.system_run_id)
            if not run:
                msg = "No se pudo obtener el run"
                self._logger.error(msg)
                raise RuntimeError(msg)

            # Setear ended en el run
            await run_repo.set_ended(run.id)
            # Setear final capital sol en el run (balance final de la wallet)
            final_capital_sol = Decimal(total_pnl['current_balance_sol'] or "0.0")
            await run_repo.set_final_capital_sol(run.id, final_capital_sol)

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
            if self.is_running and self.config.use_pumpfun_redis_bridge and self.redis_subscriptions:
                self._logger.debug("Actualizando suscripciones para incluir nuevo trader...")
                await self.redis_subscriptions.unsubscribe_account_trade([trader.wallet_address for trader in self.config.traders if trader.wallet_address != trader_address])
                await self.redis_subscriptions.subscribe_account_trade(
                    account_addresses=[trader.wallet_address for trader in self.config.traders],
                    callback=self.trade_processor_callback,
                )
                self._logger.debug("Suscripciones actualizadas")
            elif self.is_running and self.subscriptions:
                self._logger.debug("Actualizando suscripciones para incluir nuevo trader...")
                await self.subscriptions.unsubscribe_account_trade([trader.wallet_address for trader in self.config.traders if trader.wallet_address != trader_address])
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
            if self.is_running and self.config.use_pumpfun_redis_bridge and self.redis_subscriptions:
                self._logger.debug("Actualizando suscripciones para excluir trader...")
                await self.redis_subscriptions.unsubscribe_account_trade([trader_address])
                if self.config.traders:  # Si quedan traders
                    await self.redis_subscriptions.subscribe_account_trade(
                        account_addresses=[trader.wallet_address for trader in self.config.traders],
                        callback=self.trade_processor_callback,
                    )
                    self._logger.debug("Suscripciones actualizadas")
                else:
                    self._logger.debug("No quedan traders para suscribir")
            elif self.is_running and self.subscriptions:
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
                current_balance = await self.balance_manager.get_sol_balance(force_onchain=True)
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
                was_processed = await self.queue_manager.process_executed_position(trade_data, signature)
                if not was_processed:
                    self._logger.warning(f"No se pudo procesar posición ejecutada: {trade_data.id}")
            else:
                error_message = error_message or 'Error desconocido'
                self._logger.error(f"Error ejecutando trade: {error_message or 'Error desconocido'}")
                self.position_event_bus.emit_position_failed(
                    PositionFailedEvent(
                        position_id=trade_data.id,
                        token_address=trade_data.token_address,
                        trader_wallet=trade_data.trader_wallet,
                        position_type="open" if trade_data.side == "buy" else "close",
                        error_message=error_message
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

    async def _get_total_pnl(self) -> Dict[str, str]:
        """
        Calcula el P&L (profit and loss) total, en SOL, USD y porcentaje.
        Returns:
            dict: {'initial_balance': str, 'current_balance': str, 'sol_price': str, 'pnl_sol': str, 'pnl_usd': str, 'pnl_percent': str}
        """
        sol_price = Decimal(await self.trading_data_fetcher.get_sol_price_usd() or "0.0")
        initial_balance = Decimal(self.config.general_available_balance_to_invest or "0.0")
        initial_balance_usd = initial_balance * sol_price
        current_balance = Decimal(await self.balance_manager.get_sol_balance(force_onchain=True) or "0.0")
        current_balance_usd = current_balance * sol_price
        pnl_sol = current_balance - initial_balance
        pnl_usd = pnl_sol * sol_price
        # Calcular el P&L porcentual
        if initial_balance != Decimal("0.0"):
            pnl_percent = (pnl_sol / initial_balance) * Decimal("100.0")
            pnl_percent_str = format(pnl_percent.quantize(Decimal("0.01"), rounding=ROUND_DOWN).normalize(), "f")
        else:
            pnl_percent_str = "0.00"
        pnl_sol = format(pnl_sol.quantize(Decimal("0.000000001"), rounding=ROUND_DOWN).normalize(), "f")
        pnl_usd = format(pnl_usd.quantize(Decimal("0.01"), rounding=ROUND_DOWN).normalize(), "f")
        return {
            "initial_balance_sol": format(initial_balance.quantize(Decimal("0.000000001"), rounding=ROUND_DOWN).normalize(), "f"),
            "initial_balance_usd": format(initial_balance_usd.quantize(Decimal("0.01"), rounding=ROUND_DOWN).normalize(), "f"),
            "current_balance_sol": format(current_balance.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN).normalize(), "f"),
            "current_balance_usd": format(current_balance_usd.quantize(Decimal("0.01"), rounding=ROUND_DOWN).normalize(), "f"),
            "sol_price": format(sol_price.quantize(Decimal("0.01"), rounding=ROUND_DOWN).normalize(), "f"),
            "pnl_sol": pnl_sol,
            "pnl_usd": pnl_usd,
            "pnl_percent": pnl_percent_str
        }

    def trading_mode_message(self) -> None:
        """
        Obtiene el mensaje de modo de trading
        """
        if self.config.dry_run:
            self._logger.warning(f"=" * 80)
            self._logger.warning("⚠️  MODO DRY RUN ACTIVADO")
            self._logger.warning("⚠️  No se ejecutarán trades reales on-chain")
            self._logger.warning("⚠️  Las signatures serán falsas (DRY_RUN_xxx)")
            self._logger.warning("⚠️  Los precios se obtendrán de Moralis API")
            self._logger.warning("⚠️  Los balances se actualizarán como si fueran reales")
            self._logger.warning("=" * 80)
        elif isinstance(self.transaction_executor, TransactionExecutor):
            self._logger.info("=" * 80)
            self._logger.info("ℹ️  MODO REAL ACTIVADO")
            self._logger.info("ℹ️  Se ejecutarán trades reales on-chain")
            self._logger.info("ℹ️  Las signatures serán reales")
            self._logger.info("ℹ️  Los precios se obtendrán de la API de PumpFun")
            self._logger.info("ℹ️  Los balances se actualizarán como si fueran reales")
            self._logger.info("=" * 80)
        else:
            self._logger.error("=" * 80)
            self._logger.error("❌  MODO DESCONOCIDO ACTIVADO")
            self._logger.error("❌  No se puede determinar el modo de trading")
            self._logger.error("=" * 80)

    # ==================== Persistencia inicial ====================
    async def _persist_initial_config_entities(self) -> None:
        """
        Guarda en base de datos los traders y mints iniciales.

        - Traders: tomados de self.config.traders
        - Mints: tomados del cache de tokens si hubiera datos disponibles
        """
        try:
            copy_trading_bot_repo = CopyTradingBotRepository()
            run_repo = RunRepository()
            trader_mint_repo = TraderMintRepository()

            if not self.wallet_data:
                raise ValueError("WalletData no inicializado")

            # Upsert del copy trading bot
            copy_trading_bot = await copy_trading_bot_repo.upsert_bot(self.wallet_data.wallet_public_key, self.config.system_name)

            # Upsert del run
            run = await run_repo.create(self.config.system_run_id, copy_trading_bot.system_wallet_address, self.config.dry_run)
            if not run:
                msg = "No se pudo crear el run"
                self._logger.error(msg)
                raise RuntimeError(msg)

            # Setear started en el run
            await run_repo.set_started(run.id)

            # Setear initial capital sol en el run (balance inicial de la wallet)
            await run_repo.set_initial_capital_sol(run.id, Decimal(self.config.general_available_balance_to_invest or "0.0"))

            # Upsert de traders desde configuración
            trader_items = []
            for trader in self.config.traders:
                nickname = None
                try:
                    nickname = trader.nickname if getattr(trader, 'nickname', None) else None
                except Exception:
                    nickname = None
                trader_items.append((trader.wallet_address, nickname))

            if trader_items:
                count = await trader_mint_repo.bulk_add_traders_to_run(run.id, trader_items)
                self._logger.debug(f"RunTraders iniciales persistidos: {count}")

        except Exception as e:
            self._logger.warning(f"No se pudieron persistir entidades iniciales (traders/mints): {e}")
