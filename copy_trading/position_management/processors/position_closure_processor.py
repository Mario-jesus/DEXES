# -*- coding: utf-8 -*-
"""
Procesador de cierre de posiciones para Copy Trading.
Maneja toda la lógica de cierre de posiciones abiertas.
"""
import asyncio, datetime
from typing import Optional, Union, TYPE_CHECKING, Tuple, List
from decimal import ROUND_DOWN, Decimal, getcontext

from logging_system import AppLogger
from ...events import PositionEventBus, PositionCloseExecutedEvent, PositionPartialClosedEvent
from ..models import OpenPosition, ClosePosition, SubClosePosition, ClosePositionStatus
from ..services import PositionCalculationService

if TYPE_CHECKING:
    from ..queues.open_position_queue import OpenPositionQueue
    from ..queues.notification_queue import PositionNotificationQueue

getcontext().prec = 26


class PositionClosureProcessor:
    """
    Procesador responsable de manejar la lógica de cierre de posiciones.
    Separa la lógica de negocio del cierre de la gestión de colas.
    """

    def __init__(self, 
                    open_position_queue: 'OpenPositionQueue',
                    notification_queue: Optional['PositionNotificationQueue'] = None,
                    position_event_bus: Optional[PositionEventBus] = None):
        self.open_position_queue = open_position_queue
        self.notification_queue = notification_queue
        self.position_event_bus = position_event_bus
        self._logger = AppLogger(self.__class__.__name__)
        self._lock = asyncio.Lock()
        self.position_calculation_service = PositionCalculationService()

        self._logger.debug("PositionClosureProcessor inicializado")

    async def process_position_closure(self, close_position: ClosePosition) -> bool:
        """
        Procesa el cierre de una posición.
        Esta es la interfaz principal para cerrar posiciones.
        
        Args:
            close_position: Posición a cerrar
            
        Returns:
            True si el cierre fue exitoso, False en caso contrario
        """
        if not close_position.trader_trade_data:
            self._logger.error(f"Error cerrando posición {close_position.id}: no se encontró el trader_trade_data")
            return False

        try:
            self._logger.info(f"Iniciando procesamiento de cierre para posición {close_position.id}")
            async with self._lock:
                is_success, processed_open_position_ids, last_partial_closure = await self._evaluate_and_process_closure(close_position)

                if is_success:
                    self._logger.info(f"Cierre de posición {close_position.id} procesado exitosamente")
                else:
                    self._logger.error(f"Error en el procesamiento de cierre de posición {close_position.id}")

                if self.position_event_bus:
                    self.position_event_bus.emit_position_close_executed(
                        PositionCloseExecutedEvent(
                            position_id=close_position.id,
                            token_address=close_position.token_address,
                            trader_wallet=close_position.trader_wallet,
                            processed_open_position_ids=processed_open_position_ids,
                            last_partial_closure=last_partial_closure,
                            status="success" if is_success else "failed"
                        )
                    )

                return is_success
        except Exception as e:
            self._logger.error(f"Error procesando cierre de posición {close_position.id}: {e}")
            return False

    async def _evaluate_and_process_closure(self, close_position: ClosePosition) -> Tuple[bool, List[str], bool]:
        """
        Evalúa y procesa el cierre de una posición.

        Args:
            close_position: Objeto ClosePosition que representa la posición a cerrar.

        Returns:
            Tuple:
                - bool: True si el cierre fue exitoso, False si falló completamente.
                - List[str]: Lista de IDs de posiciones abiertas cerradas completa o parcialmente.
                - bool: True si la última posición fue un cierre parcial, False si fue cierre total.
        """
        if not close_position.trader_trade_data:
            # Los datos de trader_wallet y token_address se obtienen del trader_trade_data
            self._logger.error(f"Error cerrando posición {close_position.id}: no se encontró el trader_trade_data")
            return False, [], False

        close_amount_tokens_remaining = Decimal(close_position.amount_tokens_executed)

        self._logger.debug(
            f"Comenzando proceso de cierre para close_position {close_position.id} - "
            f"Total a cerrar: {format(close_amount_tokens_remaining, 'f')} tokens"
        )

        last_partial_closure = False
        processed_open_position_ids = []

        while close_amount_tokens_remaining > 0:

            open_position = await self.open_position_queue.get_first_position(
                close_position.trader_wallet if not close_position.is_liquidation else None,
                close_position.token_address
            )
            self._logger.debug(f"open_position: {open_position}")

            if not open_position:
                self._logger.warning(
                    f"Error cerrando posición {close_position.id}: no se encontró la posición abierta. "
                    f"Restante por cerrar: {format(close_amount_tokens_remaining, 'f')} tokens"
                )
                break

            amounts = self.position_calculation_service.calculate_remaining_amounts(open_position, exact=True)
            open_amount_tokens_remaining = Decimal(amounts[1])

            self._logger.debug(
                f"Procesando open_position {open_position.id} - "
                f"Disponible para cerrar: {format(open_amount_tokens_remaining, 'f')} tokens. "
                f"Restante por cerrar: {format(close_amount_tokens_remaining, 'f')} tokens"
            )

            # Cierre completo de la posición abierta
            if close_amount_tokens_remaining > open_amount_tokens_remaining:
                self._logger.debug(
                    f"Cierre completo de open_position {open_position.id} con subcierre de "
                    f"{format(open_amount_tokens_remaining, 'f')} tokens"
                )
                close_position_partial = self._create_sub_close_position(
                    close_position=close_position,
                    amount_sol_executed=Decimal("0.0"),
                    amount_tokens_executed=open_amount_tokens_remaining,
                    open_position_id=open_position.id,
                    open_position_amount_sol_executed=open_position.amount_sol_executed,
                    open_position_total_cost_sol=open_position.total_cost_sol
                )

                open_position.add_close(close_position_partial)
                self.position_calculation_service.update_position_status_after_close(open_position)

                was_removed = await self.complete_position_closure(open_position)
                if was_removed:
                    processed_open_position_ids.append(open_position.id)
                last_partial_closure = False

                close_amount_tokens_remaining -= open_amount_tokens_remaining
                close_position.status = ClosePositionStatus.PARTIAL
                continue

            if close_position.status == ClosePositionStatus.PARTIAL:
                self._logger.debug(
                    f"Finalizando cierre parcial con subcierre de "
                    f"{format(close_amount_tokens_remaining, 'f')} tokens en open_position {open_position.id}"
                )
                close_position.status = ClosePositionStatus.SUCCESS
                close_position_partial = self._create_sub_close_position(
                    close_position=close_position,
                    amount_sol_executed=Decimal("0.0"),
                    amount_tokens_executed=close_amount_tokens_remaining,
                    open_position_id=open_position.id,
                    open_position_amount_sol_executed=open_position.amount_sol_executed,
                    open_position_total_cost_sol=open_position.total_cost_sol
                )
                open_position.add_close(close_position_partial)
                self.position_calculation_service.update_position_status_after_close(open_position)
                processed_open_position_ids.append(open_position.id)
                last_partial_closure = True
            else:
                self._logger.debug(
                    f"Cierre total de open_position {open_position.id} con close_position {close_position.id} "
                    f"por {format(close_amount_tokens_remaining, 'f')} tokens"
                )
                close_position.status = ClosePositionStatus.SUCCESS
                close_position.add_metadata("open_position_amount_sol_executed", open_position.amount_sol_executed)
                close_position.add_metadata("open_position_total_cost_sol", open_position.total_cost_sol)
                open_position.add_close(close_position)
                self.position_calculation_service.update_position_status_after_close(open_position)
                processed_open_position_ids.append(open_position.id)
                last_partial_closure = True

            if close_amount_tokens_remaining == open_amount_tokens_remaining:
                self._logger.debug(
                    f"Se cierra completamente open_position {open_position.id} (match exacto con el cierre solicitado)"
                )
                was_removed = await self.complete_position_closure(open_position)
                if was_removed:
                    processed_open_position_ids.append(open_position.id)
                last_partial_closure = False
            else:
                self._logger.debug(
                    f"Se notifica cierre parcial para close_position {close_position.id} (aún quedan posiciones por cerrar)"
                )
                await self._notify_position(close_position)

            close_amount_tokens_remaining -= open_amount_tokens_remaining

        if close_amount_tokens_remaining > 0:
            if close_position.amount_tokens == close_amount_tokens_remaining:
                self._logger.error(
                    f"No se encontró la posición abierta para cerrar y no se pudo cerrar ninguna posición para close_position {close_position.id}."
                )
                close_position.status = ClosePositionStatus.FAILED
                close_position.message_error = (
                    f"No se encontró la posición abierta para cerrar y no se pudo cerrar ninguna posición para close_position {close_position.id}"
                )
                await self._notify_position(close_position)
                return False, [], False

            self._logger.debug(
                f"No se encontró la posición abierta para cerrar el resto de la posición."
                f"Restante: {format(close_amount_tokens_remaining, 'f')} tokens para close_position {close_position.id}"
            )
            close_position_partial = self._create_sub_close_position(
                close_position=close_position,
                amount_sol_executed=Decimal("0.0"),
                amount_tokens_executed=close_amount_tokens_remaining,
                status=ClosePositionStatus.FAILED,
                message_error = f"No se encontró la posición abierta para cerrar el resto de la posición."
            )
            await self._notify_position(close_position_partial)
            return False, processed_open_position_ids, last_partial_closure

        self._logger.info(
            f"Cierre de posición {close_position.id} completado exitosamente. Posiciones procesadas: {processed_open_position_ids}"
        )
        return True, processed_open_position_ids, last_partial_closure

    def _create_sub_close_position(
        self,
        close_position: ClosePosition,
        amount_sol_executed: Decimal,
        amount_tokens_executed: Decimal,
        open_position_id: str = "",
        status: ClosePositionStatus = ClosePositionStatus.SUCCESS,
        message_error: str = "",
        **kwargs: str
    ) -> SubClosePosition:
        """
        Crea un objeto SubClosePosition para un cierre parcial.
        """
        self._logger.debug(f"Creando subcierre de posición {close_position.id} con amount_sol_executed {amount_sol_executed}, amount_tokens_executed {amount_tokens_executed}, open_position_id {open_position_id}, status {status}, message_error {message_error}")

        sub_close_position = SubClosePosition(
            close_position=close_position,
            amount_sol_executed=format(amount_sol_executed, 'f'),
            amount_tokens_executed=format(amount_tokens_executed, 'f'),
            status=status,
            message_error=message_error
        )

        sub_close_position.add_metadata("open_position_amount_sol_executed", kwargs.get("open_position_amount_sol_executed", ""))
        sub_close_position.add_metadata("open_position_total_cost_sol", kwargs.get("open_position_total_cost_sol", ""))

        if self.position_event_bus:
            self._logger.debug(f"Emitiendo evento de cierre parcial {sub_close_position.id}")
            self.position_event_bus.emit_position_partial_closed(
                PositionPartialClosedEvent(
                    position_id=sub_close_position.id,
                    token_address=sub_close_position.token_address,
                    trader_wallet=sub_close_position.trader_wallet,
                    close_position_id=close_position.id,
                    open_position_id=open_position_id,
                    amount_sol=sub_close_position.amount_sol_executed,
                    amount_tokens=sub_close_position.amount_tokens_executed,
                    total_cost_sol=sub_close_position.total_cost_sol,
                    message_error=message_error,
                    status="success" if status == ClosePositionStatus.SUCCESS else "failed",
                    timestamp=datetime.datetime.now(datetime.UTC)
                )
            )

        return sub_close_position

    async def complete_position_closure(self, position: OpenPosition) -> bool:
        """
        Completa el cierre de una posición - lógica exacta del original
        """
        try:
            self._logger.debug(f"Completando cierre de posición {position.id}")

            was_removed = await self.open_position_queue.remove_position(position)
            if was_removed:
                self._logger.info(f"Posición {position.id} cerrada exitosamente")
            else:
                self._logger.warning(f"No se pudo remover posición {position.id} de la cola abierta")

            return was_removed
        except Exception as e:
            self._logger.error(f"Error completando cierre de posición {position.id}: {e}")
            return False

    async def _notify_position(self, position: Union[ClosePosition, SubClosePosition]) -> None:
        """
        Envía posiciones a la cola de notificaciones de forma asíncrona.
        No bloquea el flujo principal del sistema.
        
        Args:
            position: Posición a notificar
        """
        try:
            position_id = position.id

            if self.notification_queue:
                await self.notification_queue.add_position(position)
                self._logger.debug(f"Posición {position_id} enviada a notificaciones")
            else:
                self._logger.warning(f"No hay cola de notificaciones disponible para posición {position_id}")
        except Exception as e:
            position_id = position.id
            self._logger.error(f"Error enviando posición {position_id} a notificaciones: {e}")
