# -*- coding: utf-8 -*-
"""
Sistema principal de Copy Trading Mini
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio

from pumpfun.api_client import PumpFunApiClient
from pumpfun.transactions import PumpFunTransactions
from pumpfun.subscriptions import PumpFunSubscriptions
from pumpfun.wallet_manager import PumpFunWalletStorage, WalletData, WalletImportException

from .config import CopyTradingConfig
from .logger import CopyTradingLogger
from .position_queue import PositionQueue, Position
from .validation import ValidationEngine
from .callback import CopyTradingCallback
from .notifications import (
    NotificationManager, 
    TelegramStrategy, 
    ConsoleStrategy
)


class CopyTrading:
    """Sistema principal de copy trading simplificado"""

    def __init__(self, 
                    config: CopyTradingConfig,
                    logger: Optional[CopyTradingLogger] = None):
        """
        Inicializa el sistema de copy trading
        
        Args:
            config: Configuración del sistema
            logger: Logger personalizado (opcional)
        """
        self.config = config

        # Inicializar componentes
        self.logger = logger or CopyTradingLogger()
        self.position_queue = PositionQueue(
            data_path=config.data_path, 
            logger=self.logger,
            notification_callback=self._notify_position_status_change
        )
        self.validation_engine = ValidationEngine(config, logger=self.logger)

        # Inicializar notificaciones
        self.notification_manager = self._setup_notifications()

        # Cliente API centralizado (se configurará en start())
        self.client: Optional[PumpFunApiClient] = None

        # Wallet data
        self.wallet_data: Optional[WalletData] = None

        self.subscriptions: Optional[PumpFunSubscriptions] = None
        self.transactions_manager: Optional[PumpFunTransactions] = None

        # Callback
        self.callback = CopyTradingCallback(
            config=config,
            position_queue=self.position_queue,
            validation_engine=self.validation_engine,
            logger=self.logger,
            trade_executor=self._execute_trade,
            notification_manager=self.notification_manager
        )

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

    async def __aenter__(self):
        """Context manager entry"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.stop()

    def _setup_notifications(self) -> Optional[NotificationManager]:
        """Configura el sistema de notificaciones"""
        if not self.config.notifications_enabled:
            return None

        strategies = []

        # Añadir estrategia de Telegram si está configurada
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            telegram_strategy = TelegramStrategy(
                config={
                    'token': self.config.telegram_bot_token,
                    'chat_id': self.config.telegram_chat_id,
                    'messages_per_minute': self.config.telegram_messages_per_minute
                },
                logger=self.logger
            )
            strategies.append(telegram_strategy)

        # Siempre incluir consola como fallback
        console_strategy = ConsoleStrategy(
            config={'colored': True},
            logger=self.logger
        )
        strategies.append(console_strategy)

        return NotificationManager(strategies, logger=self.logger)

    async def start(self):
        """Inicia el sistema de copy trading"""
        if self.is_running:
            self.logger.warning("El sistema ya está ejecutándose")
            return

        try:
            self.logger.info("🚀 Iniciando sistema Copy Trading Mini")
            self.logger.info(f"Modo: {'DRY RUN' if self.config.dry_run else 'LIVE'}")
            self.logger.info(f"Traders a seguir: {len(self.config.traders)}")

            # Cargar datos completos de la wallet usando WalletManager
            try:
                self.wallet_data = await PumpFunWalletStorage.load_wallet_data_from_file(self.config.wallet_file)
                if not isinstance(self.wallet_data, WalletData):
                    raise WalletImportException("No se pudieron cargar los datos de la wallet", file_path=self.config.wallet_file)
            except WalletImportException as e:
                self.logger.error(f"Error cargando wallet: {e}")
                if self.notification_manager:
                    await self.notification_manager.notify_system(
                        f"Error cargando wallet: {e}",
                        "error"
                    )
                raise

            # Conectar cliente API
            self.client = PumpFunApiClient(api_key=self.wallet_data.api_key, enable_websocket=True, enable_http=True)
            await self.client.connect()
            self.logger.info("✅ Cliente API conectado")

            self.logger.info(f"Wallet cargada: {self.wallet_data.wallet_public_key}")
            self.logger.info(f"API Key configurada: {self.wallet_data.api_key[:20]}...")

            # Inicializar validation engine con el keypair y la conexión rpc
            await self.validation_engine.initialize(self.wallet_data.get_keypair())

            # Verificar balance inicial
            balance = await self.validation_engine.account_info.get_sol_balance(self.wallet_data.wallet_public_key)
            self.logger.info(f"Balance inicial: {balance:.6f} SOL")

            # Initialize transaction manager con el cliente centralizado
            self.transactions_manager = PumpFunTransactions(api_client=self.client)

            # Inicializar subscriptions con el cliente centralizado
            self.subscriptions = PumpFunSubscriptions(api_client=self.client)

            # Suscribirse a trades de los traders
            await self.subscriptions.subscribe_account_trade(
                account_addresses=self.config.traders,
                callback=self.callback,
                use_api_key=True
            )

            self.logger.info(f"✅ Suscrito a {len(self.config.traders)} traders")

            # Cargar estado previo de posiciones
            await self.position_queue.load_from_disk()

            # Actualizar estado
            self.is_running = True
            self.start_time = datetime.now()

            self.logger.info("🎯 Sistema iniciado correctamente")

            # Notificar inicio del sistema
            if self.notification_manager:
                await self.notification_manager.notify_system(
                    "Sistema iniciado correctamente",
                    "success"
                )

            # Lanzar el loop de procesamiento de posiciones pendientes
            if not self._pending_task:
                self._pending_task = asyncio.create_task(self._pending_positions_loop())

        except Exception as e:
            self.logger.error(f"Error iniciando sistema: {str(e)}", exc_info=True)
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
            self.logger.info("🛑 Deteniendo sistema Copy Trading Mini")
            self.is_running = False

            # Procesar posiciones pendientes
            pending_positions = await self.position_queue.get_pending_positions()
            pending_count = len(pending_positions)

            if pending_count > 0:
                self.logger.info(f"Procesando {pending_count} posiciones pendientes...")
                await self.position_queue.save_state()

            # Liberar recursos
            if self.validation_engine:
                await self.validation_engine.close()
                self.logger.info("Recursos de AccountInfo liberados en ValidationEngine")

            # Desconectar API
            if self.client:
                await self.client.disconnect()

            # Mostrar estadísticas finales
            stats = await self.get_metrics()
            self._log_final_stats(stats)

            self.logger.info("✅ Sistema detenido correctamente")

            # Enviar notificación de detención
            if self.notification_manager:
                stats_msg = (
                    f"Sistema detenido\n"
                    f"- Tiempo activo: ⏱️ {stats['system_metrics']['uptime_seconds']/3600:.1f}h\n"
                    f"- Trades ejecutados: ✅ {stats['system_metrics']['trades_executed']}\n"
                    f"- Volumen total: 💰 {stats['system_metrics']['total_volume_sol']:.6f} SOL"
                )
                await self.notification_manager.notify_system(stats_msg, "stopped")

            if self._pending_task:
                self._pending_task.cancel()
                self._pending_task = None

        except Exception as e:
            self.logger.error(f"Error deteniendo sistema: {e}")
            if self.notification_manager:
                error_msg = f"Error al detener sistema: {str(e)}"
                await self.notification_manager.notify_system(error_msg, "error")

    async def add_trader(self, trader_address: str):
        """
        Añade un nuevo trader a seguir
        
        Args:
            trader_address: Dirección del wallet del trader
        """
        if trader_address not in self.config.traders:
            self.config.traders.append(trader_address)

            # Si el sistema está corriendo, actualizar suscripción
            if self.is_running and self.subscriptions:
                await self.subscriptions.unsubscribe_account_trade(self.config.traders[:-1])
                await self.subscriptions.subscribe_account_trade(
                    account_addresses=self.config.traders,
                    callback=self.callback,
                    use_api_key=True
                )

            self.logger.info(f"Trader añadido: {trader_address[:8]}...")
        else:
            self.logger.warning(f"Trader ya existe: {trader_address[:8]}...")

    async def remove_trader(self, trader_address: str):
        """
        Elimina un trader de la lista
        
        Args:
            trader_address: Dirección del wallet del trader
        """
        if trader_address in self.config.traders:
            self.config.traders.remove(trader_address)

            # Si el sistema está corriendo, actualizar suscripción
            if self.is_running and self.subscriptions:
                await self.subscriptions.unsubscribe_account_trade([trader_address])
                if self.config.traders:  # Si quedan traders
                    await self.subscriptions.subscribe_account_trade(
                        account_addresses=self.config.traders,
                        callback=self.callback,
                        use_api_key=True
                    )

            self.logger.info(f"Trader eliminado: {trader_address[:8]}...")
        else:
            self.logger.warning(f"Trader no encontrado: {trader_address[:8]}...")

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Obtiene todas las posiciones"""
        return await self.position_queue.get_all_positions()

    async def get_pending_positions(self) -> List[Dict[str, Any]]:
        """Obtiene posiciones pendientes"""
        return await self.position_queue.get_pending_positions()

    async def get_metrics(self) -> Dict[str, Any]:
        """Obtiene métricas del sistema"""
        # Actualizar uptime
        if self.start_time:
            self.metrics['uptime_seconds'] = (datetime.now() - self.start_time).total_seconds()

        # Combinar con métricas del callback
        callback_stats = self.callback.get_stats()

        # Combinar con métricas de la cola
        queue_stats = await self.position_queue.get_stats()

        # Obtener balance actual
        current_balance = 0.0
        if self.validation_engine and self.validation_engine.account_info and self.wallet_data:
            current_balance = await self.validation_engine.account_info.get_sol_balance(self.wallet_data.wallet_public_key)

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
                        'pnl': position_data.get('realized_pnl_sol', 0)
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
                self.logger.error(f"Error notificando cambio de estado de posición: {e}")

    async def _execute_trade(self, position: Position) -> None:
        """
        Ejecuta un trade
        
        Args:
            position: Posición a ejecutar
        """
        try:
            # Ejecutar trade usando execute_lightning_trade
            result = await self.transactions_manager.execute_lightning_trade(
                action=position.side.value,  # "buy" o "sell"
                mint=position.token_address,
                amount=position.amount_sol,
                denominated_in_sol=True,
                slippage=self.config.slippage_tolerance,
                priority_fee=self.config.priority_fee_sol,
                pool="auto",
                skip_preflight=True
            )

            if result and result.get('signature'):
                self.logger.info(f"✅ Trade ejecutado exitosamente (lightning_trade): {position.id}")

                # Incrementar métricas de ejecución
                self.metrics['trades_executed'] += 1
                self.metrics['total_volume_sol'] += position.amount_sol

                # Usar la cantidad de tokens que ya viene en la posición (del trade original)
                amount_tokens = position.amount_tokens or 0
                execution_price = 0
                if amount_tokens > 0:
                    execution_price = position.amount_sol / amount_tokens

                # Actualizar posición como ejecutada - la notificación se manejará automáticamente
                await self.position_queue.execute_position(
                    position_id=position.id,
                    signature=result['signature'],
                    execution_price=execution_price,
                    amount_tokens=amount_tokens
                )

            else:
                error_msg = result.get('error', 'Unknown error')
                self.logger.error(f"❌ Error ejecutando trade (lightning_trade): {error_msg}")

                # Marcar posición como fallida - la notificación se manejará automáticamente
                await self.position_queue.update_position(
                    position_id=position.id,
                    status='failed',
                    error=error_msg
                )

        except Exception as e:
            self.logger.error(f"Error inesperado ejecutando trade (lightning_trade): {e}")
            
            # Marcar posición como fallida - la notificación se manejará automáticamente
            await self.position_queue.update_position(
                position_id=position.id,
                status='failed',
                error=str(e)
            )

    async def _pending_positions_loop(self):
        """
        Loop asíncrono que procesa y ejecuta las posiciones pendientes
        """
        while self.is_running:
            try:
                pending_positions = await self.position_queue.get_pending_positions()
                for position_data in pending_positions:
                    # Crea un objeto Position desde el dict si es necesario
                    position = Position.from_dict(position_data)
                    await self._execute_trade(position)
                    # Espera un poco entre ejecuciones para evitar rate limits
                    await asyncio.sleep(1)
            except Exception as e:
                self.logger.error(f"Error en el loop de ejecución de trades: {e}")
            await asyncio.sleep(2)

    async def _process_pending_positions(self):
        """Procesa posiciones pendientes en la cola"""
        try:
            pending_positions = await self.position_queue.get_pending_positions()

            for position_data in pending_positions:
                if not self.config.dry_run:
                    # Aquí iría la lógica de ejecución real
                    pass
                else:
                    self.logger.info(f"[DRY RUN] Procesando posición: {position_data['id']}")

        except Exception as e:
            self.logger.error(f"Error procesando posiciones pendientes: {str(e)}")

    def _log_final_stats(self, stats: Dict[str, Any]):
        """Log de estadísticas finales"""
        if self.start_time:
            uptime = (datetime.now() - self.start_time).total_seconds()

            self.logger.info("📊 Estadísticas finales:")
            self.logger.info(f"  • Tiempo activo: {uptime/3600:.1f}h")
            self.logger.info(f"  • Trades procesados: {self.metrics['trades_processed']}")
            self.logger.info(f"  • Trades ejecutados: {self.metrics['trades_executed']}")
            vol = self.metrics['total_volume_sol']
            if vol < 1e-6 and vol > 0:
                self.logger.info(f"  • Volumen total: {vol:.12f} SOL")
            else:
                self.logger.info(f"  • Volumen total: {vol:.6f} SOL")

            # Estadísticas del cliente API
            if self.client:
                client_status = self.client.get_status()
                self.logger.info("📡 Estadísticas del cliente API:")
                self.logger.info(f"  • Peticiones HTTP: {client_status.get('request_count', 0)}")
                self.logger.info(f"  • Errores: {client_status.get('error_count', 0)}")
                self.logger.info(f"  • Mensajes WebSocket: {client_status.get('websocket_messages_received', 0)}")
                self.logger.info(f"  • Suscripciones activas: {client_status.get('active_subscriptions', 0)}")

    async def get_wallet_info(self) -> Dict[str, Any]:
        """Obtiene información de la wallet actual"""
        if not self.config.wallet_file:
            return {'error': 'No hay archivo de wallet configurado'}

        wallet_info = self.wallet_data.get_short_info()

        # Añadir información del cliente API centralizado
        if self.client:
            wallet_info['client_status'] = self.client.get_status()

        return wallet_info

    async def get_client_status(self) -> Dict[str, Any]:
        """
        Obtiene el estado del cliente API centralizado
        
        Returns:
            Estado del cliente API
        """
        if not self.client:
            return {'error': 'Cliente API no inicializado'}

        return self.client.get_status()

    async def reset_client_metrics(self):
        """Resetea las métricas del cliente API centralizado"""
        if self.client:
            self.client.reset_metrics()
            self.logger.info("Métricas del cliente API reseteadas")
