# -*- coding: utf-8 -*-
"""
Manager simplificado para coordinar las colas de posiciones en el sistema de Copy Trading.
Delega responsabilidades complejas a managers especializados.
"""
import asyncio
from typing import Optional, Dict, Any, TYPE_CHECKING

from logging_system import AppLogger

from ...config import CopyTradingConfig
from ...data_management import TradingDataFetcher, TokenTraderManager, SolanaTxAnalyzer, SolanaWebsocketManager
from ...notifications import NotificationManager
from ..models import PositionTraderTradeData, Position, OpenPosition, ClosePosition, PositionStatus
from ..processors import PositionClosureProcessor, TradeAnalysisProcessor
from ..factories import PositionFactory
from ...balance_management import BalanceManager
from .position_lifecycle_manager import PositionLifecycleManager
from .queue_initialization_manager import QueueInitializationManager

if TYPE_CHECKING:
    from ..queues import PendingPositionQueue, AnalysisPositionQueue, OpenPositionQueue, ClosedPositionQueue, PositionNotificationQueue


class PositionQueueManager:
    """
    Manager simplificado que coordina las colas de posiciones.
    Delega responsabilidades complejas a managers especializados.
    """

    def __init__(self, config: CopyTradingConfig,
                solana_analyzer: SolanaTxAnalyzer,
                solana_websocket: SolanaWebsocketManager,
                trading_data_fetcher: TradingDataFetcher,
                token_trader_manager: TokenTraderManager,
                balance_manager: BalanceManager,
                notification_manager: Optional[NotificationManager] = None):
        # Logger
        self._logger = AppLogger(self.__class__.__name__)

        # Managers especializados
        self.initialization_manager = QueueInitializationManager(
            config=config,
            solana_analyzer=solana_analyzer,
            solana_websocket=solana_websocket,
            trading_data_fetcher=trading_data_fetcher,
            token_trader_manager=token_trader_manager,
            balance_manager=balance_manager,
            notification_manager=notification_manager
        )

        self.position_factory = PositionFactory()

        # Referencias a las colas (se inicializarán en start())
        self.pending_queue: Optional['PendingPositionQueue'] = None
        self.analysis_queue: Optional['AnalysisPositionQueue'] = None
        self.open_queue: Optional['OpenPositionQueue'] = None
        self.closed_queue: Optional['ClosedPositionQueue'] = None
        self.notification_queue: Optional['PositionNotificationQueue'] = None

        # Referencias a managers y procesadores
        self.closure_processor: Optional[PositionClosureProcessor] = None
        self.analysis_processor: Optional[TradeAnalysisProcessor] = None

        # Manager de ciclo de vida
        self.lifecycle_manager: Optional[PositionLifecycleManager] = None

        # Estado de inicialización
        self._initialized = False
        self._lock = asyncio.Lock()

        self._logger.debug("PositionQueueManager inicializado")

    async def _initialize_queues(self) -> None:
        """
        Inicializa todas las colas usando el QueueInitializationManager.
        """
        if self._initialized:
            self._logger.debug("Colas ya inicializadas, saltando inicialización")
            return

        async with self._lock:
            if self._initialized:  # Double-check pattern
                self._logger.debug("Colas ya inicializadas (double-check)")
                return

            try:
                self._logger.info("Inicializando colas con QueueInitializationManager")

                # Usar el initialization manager para inicializar todas las colas
                success = await self.initialization_manager.initialize_all_queues()

                if not success:
                    self._logger.error("Error inicializando colas con QueueInitializationManager")
                    raise Exception("Failed to initialize queues")

                # Obtener todas las referencias inicializadas
                components = self.initialization_manager.get_initialized_components()

                # Asignar referencias a las colas
                self.pending_queue = components['pending_queue']
                self.analysis_queue = components['analysis_queue']
                self.open_queue = components['open_queue']
                self.closed_queue = components['closed_queue']
                self.notification_queue = components['notification_queue']

                # Asignar referencias a managers y procesadores
                self.closure_processor = components['closure_processor']
                self.analysis_processor = components['analysis_processor']

                # Verificar que todos los componentes necesarios estén inicializados
                if not all([self.pending_queue, self.analysis_queue, self.open_queue, self.closed_queue]):
                    self._logger.error("Componentes requeridos no están inicializados para lifecycle manager")
                    raise Exception("Required components not initialized")

                # Crear el lifecycle manager
                self._logger.debug("Creando PositionLifecycleManager")
                self.lifecycle_manager = PositionLifecycleManager(
                    pending_queue=self.pending_queue,
                    analysis_queue=self.analysis_queue,
                    open_queue=self.open_queue,
                    closed_queue=self.closed_queue,
                    position_factory=self.position_factory
                )

                self._initialized = True

                self._logger.debug("✅ PositionQueueManager: Todas las colas inicializadas correctamente")

            except Exception as e:
                self._logger.error(f"Error inicializando PositionQueueManager: {e}", exc_info=True)
                raise

    async def _ensure_initialized(self) -> None:
        """
        Asegura que las colas estén inicializadas antes de usarlas.
        """
        if not self._initialized:
            self._logger.debug("Colas no inicializadas, inicializando...")
            await self._initialize_queues()

    async def add_pending_position(self, position: PositionTraderTradeData) -> bool:
        """
        Agrega una posición nueva a la cola de pendientes.
        Este es el punto de entrada principal para nuevas posiciones.
        """
        try:
            await self._ensure_initialized()
            if not self.pending_queue:
                self._logger.error("Cola de pendientes no inicializada")
                return False

            self._logger.debug(f"Agregando posición pendiente: {position.signature[:8]}...")
            success = await self.pending_queue.add_position(position)

            if success:
                self._logger.debug(f"Posición {position.signature[:8]}... agregada exitosamente a pendientes")
            else:
                self._logger.warning(f"No se pudo agregar posición {position.signature[:8]}... a pendientes")

            return success

        except Exception as e:
            self._logger.error(f"Error agregando posición {position.signature[:8]}... a pending: {e}")
            return False

    async def get_next_pending(self) -> Optional[PositionTraderTradeData]:
        """
        Obtiene la siguiente posición de la cola de pendientes.
        """
        try:
            await self._ensure_initialized()
            if not self.pending_queue:
                return None

            position = await self.pending_queue.get_next_pending()
            if position:
                self._logger.debug(f"Obtenida posición pendiente: {position.signature[:8]}...")
            return position
        except Exception as e:
            self._logger.error(f"Error obteniendo posición: {e}")
            return None

    async def process_executed_position(self, position_trade_data: PositionTraderTradeData, signature: str, entry_price: str) -> bool:
        """
        Procesa una posición ejecutada delegando al PositionLifecycleManager.
        """
        try:
            await self._ensure_initialized()

            if not self.lifecycle_manager:
                self._logger.error("Lifecycle manager no está inicializado")
                return False

            self._logger.debug(f"Procesando posición ejecutada: {signature[:8]}...")
            success = await self.lifecycle_manager.process_executed_position(position_trade_data, signature, entry_price)

            if success:
                self._logger.debug(f"Posición {signature[:8]}... procesada exitosamente")
            else:
                self._logger.warning(f"No se pudo procesar posición {signature[:8]}...")
                
            return success

        except Exception as e:
            self._logger.error(f"Error procesando posición {signature[:8]}...: {e}")
            return False

    async def add_analysis_position(self, position: Position) -> bool:
        """
        Agrega una posición ejecutada a la cola de análisis.
        Se llama cuando una posición pendiente se ejecuta exitosamente.
        """
        try:
            await self._ensure_initialized()
            if not self.analysis_queue:
                self._logger.error("Cola de análisis no inicializada")
                return False

            self._logger.debug(f"Agregando posición a análisis: {position.id}")
            success = await self.analysis_queue.add_position(position)

            if success:
                self._logger.debug(f"Posición {position.id} agregada exitosamente a análisis")
            else:
                self._logger.warning(f"No se pudo agregar posición {position.id} a análisis")

            return success

        except Exception as e:
            self._logger.error(f"Error agregando posición {position.id} a analysis: {e}")
            return False

    async def add_open_position(self, position: OpenPosition) -> bool:
        """
        Agrega una posición analizada a la cola de abiertas/cerradas.
        Se llama cuando una posición termina su análisis.
        """
        try:
            await self._ensure_initialized()
            if not self.open_queue:
                self._logger.error("Cola de posiciones abiertas no inicializada")
                return False

            position.status = PositionStatus.OPEN
            self._logger.debug(f"Agregando posición abierta: {position.id}")
            success = await self.open_queue.add_open_position(position)

            if success:
                self._logger.debug(f"Posición {position.id} agregada exitosamente como abierta")
            else:
                self._logger.warning(f"No se pudo agregar posición {position.id} como abierta")

            return success

        except Exception as e:
            self._logger.error(f"Error agregando posición {position.id} a open/closed: {e}")
            return False

    async def close_position(self, close_position: ClosePosition) -> bool:
        """
        Agrega una posición cerrada a la cola de posiciones cerradas.
        """
        try:
            await self._ensure_initialized()
            if not self.closed_queue:
                self._logger.error("Cola de posiciones cerradas no inicializada")
                return False

            self._logger.debug(f"Cerrando posición: {close_position.id}")
            success = await self.closed_queue.add_closed_position(close_position)

            if success:
                self._logger.debug(f"Posición {close_position.id} cerrada exitosamente")
            else:
                self._logger.warning(f"No se pudo cerrar posición {close_position.id}")

            return success
        except Exception as e:
            self._logger.error(f"Error cerrando posición {close_position.id}: {e}")
            return False

    async def get_position_by_id(self, position_id: str) -> Optional[Position]:
        """
        Busca una posición en la cola de abierta por ID.
        """
        try:
            await self._ensure_initialized()

            if self.open_queue:
                position = await self.open_queue.get_position_by_id(position_id)
                if position:
                    self._logger.debug(f"Posición {position_id} encontrada")
                else:
                    self._logger.debug(f"Posición {position_id} no encontrada")
            else:
                self._logger.error("Cola de posiciones abiertas no inicializada")
                position = None

            return position

        except Exception as e:
            self._logger.error(f"Error buscando posición {position_id}: {e}")
            return None

    async def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas combinadas de todas las colas.
        """
        try:
            await self._ensure_initialized()

            pending_stats = { 'count': await self.pending_queue.get_pending_count() if self.pending_queue else 0 }
            analysis_stats = await self.analysis_queue.get_analysis_statistics() if self.analysis_queue else {}
            notification_stats = await self.notification_queue.get_stats() if self.notification_queue else {}
            open_closed_stats = await self.open_queue.get_stats() if self.open_queue else {}
            closed_stats = await self.closed_queue.get_stats() if self.closed_queue else {}

            total_positions = (
                pending_stats['count'] +
                analysis_stats.get('queue', {}).get('queue_size', 0) +
                open_closed_stats.get('total_count', 0)
            )

            self._logger.debug(f"Estadísticas obtenidas - Total posiciones: {total_positions}")

            return {
                'pending': pending_stats,
                'analysis': analysis_stats,
                'open_closed': open_closed_stats,
                'notifications': notification_stats,
                'closed_queue': closed_stats,
                'total_positions': total_positions
            }
        except Exception as e:
            self._logger.error(f"Error obteniendo estadísticas: {e}")
            return {}

    async def start(self) -> None:
        """Inicia todas las colas y workers"""
        self._logger.info("Iniciando PositionQueueManager")
        await self._initialize_queues()
        self._logger.debug("✅ PositionQueueManager iniciado correctamente")

    async def stop(self) -> None:
        """Detiene todas las colas concurrentemente."""
        try:
            self._logger.info("Deteniendo PositionQueueManager")
            stop_tasks = []

            if self.analysis_queue:
                stop_tasks.append(self.analysis_queue.stop())
            if self.pending_queue:
                stop_tasks.append(self.pending_queue.stop())
            if self.open_queue:
                stop_tasks.append(self.open_queue.stop())
            if self.closed_queue:
                stop_tasks.append(self.closed_queue.stop())
            if self.notification_queue:
                stop_tasks.append(self.notification_queue.stop())

            # Ejecutar todas las tareas de detención en paralelo
            if stop_tasks:
                self._logger.debug(f"Deteniendo {len(stop_tasks)} colas concurrentemente")
                await asyncio.gather(*stop_tasks, return_exceptions=True)
                self._logger.debug("Todas las colas detenidas")

            self._logger.debug("PositionQueueManager detenido correctamente")

        except Exception as e:
            self._logger.error(f"Error deteniendo PositionQueueManager: {e}")

    async def save_state(self) -> None:
        """Guarda el estado de todas las colas concurrentemente"""
        if not self._initialized:
            self._logger.debug("PositionQueueManager no inicializado, saltando guardado")
            return

        try:
            self._logger.debug("Guardando estado de PositionQueueManager")

            # Guardar todas las colas concurrentemente para mejor rendimiento
            save_tasks = []

            if self.pending_queue:
                save_tasks.append(self.pending_queue.save_state())
            if self.analysis_queue:
                save_tasks.append(self.analysis_queue.save_state())
            if self.open_queue:
                save_tasks.append(self.open_queue.save_state())
            if self.closed_queue:
                save_tasks.append(self.closed_queue.save_state())
            # La notification_queue no requiere persistencia (solo en memoria)

            # Ejecutar todas las tareas de guardado en paralelo
            if save_tasks:
                self._logger.debug(f"Guardando estado de {len(save_tasks)} colas concurrentemente")
                await asyncio.gather(*save_tasks, return_exceptions=True)
                self._logger.debug("Estado de todas las colas guardado")

            self._logger.debug("Estado de PositionQueueManager guardado")

        except Exception as e:
            self._logger.error(f"Error guardando estado: {e}")
