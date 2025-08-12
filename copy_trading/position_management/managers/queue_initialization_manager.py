# -*- coding: utf-8 -*-
"""
Manager para la inicialización ordenada de colas en el sistema de Copy Trading.
Separa la lógica de inicialización compleja de la gestión de colas.
"""
import asyncio
from typing import Optional, TypedDict

from pumpfun import PumpFunTradeAnalyzer
from logging_system import AppLogger

from ...config import CopyTradingConfig
from ...callbacks.notification_callback import PositionNotificationCallback
from ...data_management import TradingDataFetcher, TokenTraderManager
from ...notifications import NotificationManager
from ..queues import PendingPositionQueue, AnalysisPositionQueue, OpenPositionQueue, ClosedPositionQueue, PositionNotificationQueue
from ..processors import PositionClosureProcessor


class QueueInitializationManagerComponents(TypedDict):
    pending_queue: PendingPositionQueue
    analysis_queue: AnalysisPositionQueue
    open_queue: OpenPositionQueue
    closed_queue: ClosedPositionQueue
    notification_queue: PositionNotificationQueue
    closure_processor: PositionClosureProcessor
    notification_callback: PositionNotificationCallback


class QueueInitializationManager:
    """
    Manager responsable de la inicialización ordenada de todas las colas del sistema.
    Separa la lógica de inicialización compleja de la gestión de colas.
    """

    def __init__(self, 
                    config: CopyTradingConfig,
                    trader_analyzer: PumpFunTradeAnalyzer,
                    trading_data_fetcher: TradingDataFetcher,
                    token_trader_manager: TokenTraderManager,
                    notification_manager: Optional[NotificationManager] = None):
        self._logger = AppLogger(self.__class__.__name__)
        self.config = config
        self.trader_analyzer = trader_analyzer
        self.trading_data_fetcher = trading_data_fetcher
        self.token_trader_manager = token_trader_manager
        self.notification_manager = notification_manager

        # Parámetros de configuración
        self.data_path = config.data_path
        self.max_size = config.max_queue_size

        # Referencias a las colas (se inicializarán)
        self.pending_queue: Optional[PendingPositionQueue] = None
        self.analysis_queue: Optional[AnalysisPositionQueue] = None
        self.open_queue: Optional[OpenPositionQueue] = None
        self.closed_queue: Optional[ClosedPositionQueue] = None
        self.notification_queue: Optional[PositionNotificationQueue] = None

        # Referencias a managers y procesadores
        self.closure_processor: Optional[PositionClosureProcessor] = None
        self.notification_callback: Optional[PositionNotificationCallback] = None

        # Estado de inicialización
        self._initialized = False
        self._lock = asyncio.Lock()

        self._logger.debug("QueueInitializationManager inicializado")

    async def initialize_all_queues(self) -> bool:
        """
        Inicializa todas las colas del sistema en el orden correcto.
        
        Returns:
            True si la inicialización fue exitosa, False en caso contrario
        """
        if self._initialized:
            self._logger.debug("Colas ya inicializadas, saltando inicialización")
            return True

        async with self._lock:
            if self._initialized:  # Double-check pattern
                self._logger.debug("Colas ya inicializadas (double-check)")
                return True

            try:
                self._logger.debug("Iniciando inicialización de todas las colas")
                
                # Paso 1: Inicializar callback de notificaciones
                if not await self._initialize_notification_callback():
                    self._logger.error("Falló inicialización del callback de notificaciones")
                    return False

                # Paso 2: Inicializar cola de notificaciones
                if not await self._initialize_notification_queue():
                    self._logger.error("Falló inicialización de la cola de notificaciones")
                    return False

                # Paso 3: Inicializar cola de pendientes
                if not await self._initialize_pending_queue():
                    self._logger.error("Falló inicialización de la cola de pendientes")
                    return False

                # Paso 4: Inicializar cola de análisis
                if not await self._initialize_analysis_queue():
                    self._logger.error("Falló inicialización de la cola de análisis")
                    return False

                # Paso 5: Inicializar cola de posiciones abiertas
                if not await self._initialize_open_queue():
                    self._logger.error("Falló inicialización de la cola de posiciones abiertas")
                    return False

                # Paso 6: Inicializar cola de posiciones cerradas
                if not await self._initialize_closed_queue():
                    self._logger.error("Falló inicialización de la cola de posiciones cerradas")
                    return False

                # Paso 7: Inicializar procesadores
                if not await self._initialize_processors():
                    self._logger.error("Falló inicialización de los procesadores")
                    return False

                self._initialized = True

                self._logger.debug("✅ Todas las colas inicializadas correctamente")

                return True

            except Exception as e:
                # Si hay error, limpiar recursos ya inicializados
                await self._cleanup_on_error()
                self._logger.error(f"Error inicializando colas: {e}", exc_info=True)
                return False

    async def _initialize_notification_callback(self) -> bool:
        """Inicializa el callback de notificaciones."""
        try:
            self._logger.debug("Inicializando callback de notificaciones")
            if self.notification_manager:
                self.notification_callback = PositionNotificationCallback(
                    notification_manager=self.notification_manager,
                    trading_data_fetcher=self.trading_data_fetcher,
                    token_trader_manager=self.token_trader_manager
                )
                self._logger.debug("Callback de notificaciones inicializado")
            else:
                self._logger.debug("NotificationManager no disponible, saltando callback")
            return True
        except Exception as e:
            self._logger.error(f"Error inicializando notification callback: {e}")
            return False

    async def _initialize_notification_queue(self) -> bool:
        """Inicializa la cola de notificaciones."""
        try:
            self._logger.debug("Inicializando cola de notificaciones")
            self.notification_queue = PositionNotificationQueue(
                notification_callback=self.notification_callback,
                max_size=self.max_size,
                process_interval=1.0
            )
            await self.notification_queue.__aenter__()
            self._logger.debug("Cola de notificaciones inicializada")
            return True
        except Exception as e:
            self._logger.error(f"Error inicializando notification queue: {e}")
            return False

    async def _initialize_pending_queue(self) -> bool:
        """Inicializa la cola de posiciones pendientes."""
        try:
            self._logger.debug("Inicializando cola de posiciones pendientes")
            self.pending_queue = PendingPositionQueue(
                data_path=self.data_path,
                max_size=self.max_size
            )
            await self.pending_queue.__aenter__()
            self._logger.debug("Cola de posiciones pendientes inicializada")
            return True
        except Exception as e:
            self._logger.error(f"Error inicializando pending queue: {e}")
            return False

    async def _initialize_analysis_queue(self) -> bool:
        """Inicializa la cola de análisis."""
        try:
            self._logger.debug("Inicializando cola de análisis")
            self.analysis_queue = AnalysisPositionQueue(
                trader_analyzer=self.trader_analyzer,
                token_trader_manager=self.token_trader_manager,
                data_path=self.data_path,
                max_size=self.max_size
            )
            await self.analysis_queue.__aenter__()
            self._logger.debug("Cola de análisis inicializada")
            return True
        except Exception as e:
            self._logger.error(f"Error inicializando analysis queue: {e}")
            return False

    async def _initialize_open_queue(self) -> bool:
        """Inicializa la cola de posiciones abiertas."""
        try:
            self._logger.debug("Inicializando cola de posiciones abiertas")
            self.open_queue = OpenPositionQueue(
                data_path=self.data_path,
                max_size=self.max_size,
                token_trader_manager=self.token_trader_manager,
                position_notification_queue=self.notification_queue
            )
            await self.open_queue.__aenter__()
            self._logger.debug("Cola de posiciones abiertas inicializada")
            return True
        except Exception as e:
            self._logger.error(f"Error inicializando open queue: {e}")
            return False

    async def _initialize_closed_queue(self) -> bool:
        """Inicializa la cola de posiciones cerradas."""
        try:
            self._logger.debug("Inicializando cola de posiciones cerradas")
            self.closed_queue = ClosedPositionQueue(
                data_path=self.data_path,
                max_size=self.max_size
            )
            await self.closed_queue.__aenter__()
            self._logger.debug("Cola de posiciones cerradas inicializada")
            return True
        except Exception as e:
            self._logger.error(f"Error inicializando closed queue: {e}")
            return False

    async def _initialize_processors(self) -> bool:
        """Inicializa los procesadores."""
        try:
            self._logger.debug("Inicializando procesadores")
            
            # Verificar que las colas necesarias estén inicializadas
            if not self.open_queue or not self.closed_queue:
                self._logger.error("Colas requeridas no están inicializadas para procesadores")
                return False

            # Inicializar procesador de cierre
            self.closure_processor = PositionClosureProcessor(
                open_position_queue=self.open_queue,
                closed_position_queue=self.closed_queue,
                notification_queue=self.notification_queue
            )

            self._logger.debug("Procesadores inicializados")
            return True
        except Exception as e:
            self._logger.error(f"Error inicializando procesadores: {e}")
            return False

    async def _cleanup_on_error(self) -> None:
        """Limpia los recursos en caso de error de inicialización."""
        try:
            self._logger.warning("Limpiando recursos debido a error de inicialización")
            cleanup_tasks = []

            if self.pending_queue:
                cleanup_tasks.append(self.pending_queue.__aexit__(None, None, None))
            if self.analysis_queue:
                cleanup_tasks.append(self.analysis_queue.__aexit__(None, None, None))
            if self.open_queue:
                cleanup_tasks.append(self.open_queue.__aexit__(None, None, None))
            if self.closed_queue:
                cleanup_tasks.append(self.closed_queue.__aexit__(None, None, None))
            if self.notification_queue:
                cleanup_tasks.append(self.notification_queue.__aexit__(None, None, None))

            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
                self._logger.debug("Limpieza de recursos completada")

        except Exception as e:
            self._logger.error(f"Error limpiando recursos: {e}")

    def get_initialized_components(self) -> QueueInitializationManagerComponents:
        """
        Retorna todas las colas y componentes inicializados.
        
        Returns:
            Diccionario con todas las referencias inicializadas
        """
        if not self.pending_queue or not self.analysis_queue or not self.open_queue or not self.closed_queue or not self.notification_queue:
            error_msg = "Colas requeridas no están inicializadas"
            self._logger.error(error_msg)
            raise Exception(error_msg)

        if not self.closure_processor or not self.notification_callback:
            error_msg = "Componentes requeridos no están inicializados"
            self._logger.error(error_msg)
            raise Exception(error_msg)

        self._logger.debug("Retornando componentes inicializados")
        return {
            'pending_queue': self.pending_queue,
            'analysis_queue': self.analysis_queue,
            'open_queue': self.open_queue,
            'closed_queue': self.closed_queue,
            'notification_queue': self.notification_queue,
            'closure_processor': self.closure_processor,
            'notification_callback': self.notification_callback
        }

    def is_initialized(self) -> bool:
        """Verifica si todas las colas están inicializadas."""
        return self._initialized
