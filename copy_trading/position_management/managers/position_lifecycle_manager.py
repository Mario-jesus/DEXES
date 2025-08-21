# -*- coding: utf-8 -*-
"""
Manager para coordinar el flujo de vida de las posiciones en el sistema de Copy Trading.
Separa la lógica de coordinación de flujo de la gestión de colas.
"""
from typing import Union, TYPE_CHECKING

from logging_system import AppLogger
from ..models import PositionTraderTradeData, OpenPosition, ClosePosition, PositionStatus
from ..factories import PositionFactory

if TYPE_CHECKING:
    from ..queues import PendingPositionQueue, AnalysisPositionQueue, OpenPositionQueue, ClosedPositionQueue


class PositionLifecycleManager:
    """
    Coordinador del flujo de vida de las posiciones.
    Responsabilidad: Determinar qué hacer con cada posición ejecutada y coordinar su flujo.
    """

    def __init__(self,
                    pending_queue: 'PendingPositionQueue',
                    analysis_queue: 'AnalysisPositionQueue',
                    open_queue: 'OpenPositionQueue',
                    closed_queue: 'ClosedPositionQueue',
                    position_factory: PositionFactory):
        self._logger = AppLogger(self.__class__.__name__)

        self.pending_queue = pending_queue
        self.analysis_queue = analysis_queue
        self.open_queue = open_queue
        self.closed_queue = closed_queue
        self.position_factory = position_factory

        self._logger.debug("PositionLifecycleManager inicializado")

    async def process_executed_position(self, 
                                        position_trade_data: PositionTraderTradeData, 
                                        signature: str, 
                                        entry_price: str) -> bool:
        """
        Procesa una posición ejecutada coordinando su flujo a través del sistema.
        
        Args:
            position_trade_data: Datos del trade del trader
            signature: Firma de la transacción ejecutada
            entry_price: Precio de entrada
            
        Returns:
            True si el procesamiento fue exitoso, False en caso contrario
        """
        try:
            self._logger.info(f"Iniciando procesamiento de posición ejecutada: {signature[:8]}...")
            self._logger.debug(f"Trader: {position_trade_data.trader_wallet[:8]}..., Token: {position_trade_data.token_address[:8]}..., Side: {position_trade_data.side}, Amount: {position_trade_data.copy_amount_sol} SOL")

            # 1. Crear la posición usando el factory
            position = self.position_factory.create_position_from_trade_data(
                position_trade_data, signature, entry_price
            )

            if not position:
                self._logger.error(f"No se pudo crear posición para trade {signature[:8]}...")
                return False

            # 2. Agregar a cola de análisis
            analysis_success = await self.analysis_queue.add_position(position)

            if not analysis_success:
                self._logger.warning(f"No se pudo agregar posición {position.id} a análisis")
            else:
                self._logger.debug(f"Posición {position.id} agregada a cola de análisis")

            self._logger.debug(f"Posición creada exitosamente: {position.id}")

            # 3. Enrutar la posición según su tipo
            success = await self._route_position_to_appropriate_queue(position)

            if not success:
                self._logger.error(f"Error enrutando posición {position.id} a cola apropiada")
                return False

            self._logger.debug(f"Posición {position.id} enrutada correctamente")

            self._logger.info(f"Procesamiento de posición {position.id} completado exitosamente")

            return True

        except Exception as e:
            self._logger.error(f"Error procesando posición ejecutada {signature[:8]}...: {e}", exc_info=True)
            return False

    async def _route_position_to_appropriate_queue(self, position: Union[OpenPosition, ClosePosition]) -> bool:
        """
        Enruta una posición a la cola apropiada según su tipo.
        
        Args:
            position: Posición a enrutar (OpenPosition o ClosePosition)
            
        Returns:
            True si el enrutamiento fue exitoso, False en caso contrario
        """
        try:
            self._logger.debug(f"Enrutando posición {position.id} según su tipo")

            if isinstance(position, OpenPosition):
                self._logger.debug(f"Posición {position.id} es OpenPosition, manejando como posición abierta")
                return await self._handle_open_position(position)
            elif isinstance(position, ClosePosition):
                self._logger.debug(f"Posición {position.id} es ClosePosition, manejando como posición de cierre")
                return await self._handle_close_position(position)
            else:
                self._logger.error(f"Tipo de posición no reconocido: {type(position)}")
                return False

        except Exception as e:
            self._logger.error(f"Error enrutando posición {position.id}: {e}")
            return False

    async def _handle_open_position(self, position: OpenPosition) -> bool:
        """
        Maneja una posición abierta agregándola a la cola correspondiente.
        
        Args:
            position: Posición abierta a manejar
            
        Returns:
            True si el manejo fue exitoso, False en caso contrario
        """
        try:
            self._logger.debug(f"Manejando posición abierta: {position.id}")
            success = await self.open_queue.add_open_position(position)

            if success:
                self._logger.debug(f"Posición abierta {position.id} agregada exitosamente")
            else:
                self._logger.warning(f"No se pudo agregar posición abierta {position.id}")

            return success

        except Exception as e:
            self._logger.error(f"Error manejando posición abierta {position.id}: {e}")
            return False

    async def _handle_close_position(self, position: ClosePosition) -> bool:
        """
        Maneja una posición de cierre agregándola a la cola correspondiente.
        
        Args:
            position: Posición de cierre a manejar
            
        Returns:
            True si el manejo fue exitoso, False en caso contrario
        """
        try:
            self._logger.debug(f"Manejando posición de cierre: {position.id}")
            success = await self.closed_queue.add_closed_position(position)

            if success:
                self._logger.debug(f"Posición de cierre {position.id} agregada exitosamente")
            else:
                self._logger.warning(f"No se pudo agregar posición de cierre {position.id}")

            return success

        except Exception as e:
            self._logger.error(f"Error manejando posición de cierre {position.id}: {e}")
            return False
