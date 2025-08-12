# -*- coding: utf-8 -*-
"""
Procesador de cierre de posiciones para Copy Trading.
Maneja toda la lógica de cierre de posiciones abiertas.
"""
import asyncio
from typing import Optional, Union
from decimal import Decimal, getcontext

from logging_system import AppLogger
from ..models import OpenPosition, ClosePosition, SubClosePosition, ClosePositionStatus
from ..queues.open_position_queue import OpenPositionQueue
from ..queues.closed_position_queue import ClosedPositionQueue
from ..queues.notification_queue import PositionNotificationQueue
from ..services import PositionCalculationService

getcontext().prec = 26


class PositionClosureProcessor:
    """
    Procesador responsable de manejar la lógica de cierre de posiciones.
    Separa la lógica de negocio del cierre de la gestión de colas.
    """

    def __init__(self, 
                    open_position_queue: OpenPositionQueue,
                    closed_position_queue: ClosedPositionQueue,
                    notification_queue: Optional[PositionNotificationQueue] = None):
        self.open_position_queue = open_position_queue
        self.closed_position_queue = closed_position_queue
        self.notification_queue = notification_queue
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
                result = await self._evaluate_and_process_closure(close_position)

                if result:
                    self._logger.info(f"Cierre de posición {close_position.id} procesado exitosamente")
                else:
                    self._logger.error(f"Error en el procesamiento de cierre de posición {close_position.id}")

                return result
        except Exception as e:
            self._logger.error(f"Error procesando cierre de posición {close_position.id}: {e}")
            return False

    async def _evaluate_and_process_closure(self, close_position: ClosePosition) -> bool:
        """
        Lógica exacta del módulo original evaluate_and_process_closure
        """
        if not close_position.trader_trade_data:
            self._logger.error(f"Error cerrando posición {close_position.id}: no se encontró el trader_trade_data")
            return False

        close_amount_sol_remaining = Decimal(close_position.amount_sol)
        close_amount_tokens_remaining = Decimal(close_position.amount_tokens)

        self._logger.debug(
            f"Comenzando proceso de cierre para close_position {close_position.id} - "
            f"Total a cerrar: {format(close_amount_sol_remaining, 'f')} SOL, {format(close_amount_tokens_remaining, 'f')} tokens"
        )

        processed_positions = 0
        while close_amount_sol_remaining > 0:

            open_position = await self.open_position_queue.get_first_position(
                close_position.trader_trade_data.trader_wallet,
                close_position.trader_trade_data.token_address
            )

            if not open_position:
                self._logger.warning(
                    f"Error cerrando posición {close_position.id}: no se encontró la posición abierta. "
                    f"Restante por cerrar: {format(close_amount_sol_remaining, 'f')} SOL, {format(close_amount_tokens_remaining, 'f')} tokens"
                )
                break

            amounts = self.position_calculation_service.calculate_remaining_amounts(open_position)
            open_amount_sol_remaining = Decimal(amounts[0])
            open_amount_tokens_remaining = Decimal(amounts[1])

            self._logger.debug(
                f"Procesando open_position {open_position.id} - "
                f"Disponible para cerrar: {format(open_amount_sol_remaining, 'f')} SOL, {format(open_amount_tokens_remaining, 'f')} tokens. "
                f"Restante por cerrar: {format(close_amount_sol_remaining, 'f')} SOL, {format(close_amount_tokens_remaining, 'f')} tokens"
            )

            # Cierre completo de la posición abierta
            if close_amount_sol_remaining > open_amount_sol_remaining:
                self._logger.debug(
                    f"Cierre completo de open_position {open_position.id} con subcierre de "
                    f"{format(open_amount_sol_remaining, 'f')} SOL, {format(open_amount_tokens_remaining, 'f')} tokens"
                )
                close_position_partial = SubClosePosition(
                    close_position=close_position,
                    amount_sol=format(open_amount_sol_remaining, 'f'),
                    amount_tokens=format(open_amount_tokens_remaining, 'f'),
                    status=ClosePositionStatus.SUCCESS
                )

                open_position.add_close(close_position_partial)
                await self.complete_position_closure(open_position)
                processed_positions += 1

                close_amount_sol_remaining -= open_amount_sol_remaining
                close_amount_tokens_remaining -= open_amount_tokens_remaining
                close_position.status = ClosePositionStatus.PARTIAL
                continue

            if close_position.status == ClosePositionStatus.PARTIAL:
                self._logger.debug(
                    f"Finalizando cierre parcial con subcierre de "
                    f"{format(close_amount_sol_remaining, 'f')} SOL, {format(close_amount_tokens_remaining, 'f')} tokens en open_position {open_position.id}"
                )
                close_position.status = ClosePositionStatus.SUCCESS
                close_position_partial = SubClosePosition(
                    close_position=close_position,
                    amount_sol=format(close_amount_sol_remaining, 'f'),
                    amount_tokens=format(close_amount_tokens_remaining, 'f'),
                    status=ClosePositionStatus.SUCCESS
                )
                open_position.add_close(close_position_partial)
            else:
                self._logger.debug(
                    f"Cierre total de open_position {open_position.id} con close_position {close_position.id} "
                    f"por {format(close_amount_sol_remaining, 'f')} SOL, {format(close_amount_tokens_remaining, 'f')} tokens"
                )
                close_position.status = ClosePositionStatus.SUCCESS
                open_position.add_close(close_position)

            if close_amount_sol_remaining == open_amount_sol_remaining:
                self._logger.debug(
                    f"Se cierra completamente open_position {open_position.id} (match exacto con el cierre solicitado)"
                )
                await self.complete_position_closure(open_position)
                processed_positions += 1
            else:
                self._logger.debug(
                    f"Se notifica cierre parcial para close_position {close_position.id} (aún quedan posiciones por cerrar)"
                )
                await self._notify_position(close_position)

            close_amount_sol_remaining -= open_amount_sol_remaining
            close_amount_tokens_remaining -= open_amount_tokens_remaining

        if close_amount_sol_remaining > 0:
            if close_position.amount_sol == close_amount_sol_remaining:
                self._logger.error(
                    f"No se encontró la posición abierta para cerrar y no se pudo cerrar ninguna posición para close_position {close_position.id}."
                )
                close_position.status = ClosePositionStatus.FAILED
                close_position.message_error = (
                    f"No se encontró la posición abierta para cerrar y no se pudo cerrar ninguna posición para close_position {close_position.id}"
                )
                await self._notify_position(close_position)
                return False

            self._logger.error(
                f"No se encontró la posición abierta para cerrar el resto de la posición."
                f"Restante: {format(close_amount_sol_remaining, 'f')} SOL, {format(close_amount_tokens_remaining, 'f')} tokens para close_position {close_position.id}"
            )
            close_position_partial = SubClosePosition(
                close_position=close_position,
                amount_sol=format(close_amount_sol_remaining, 'f'),
                amount_tokens=format(close_amount_tokens_remaining, 'f'),
                status=ClosePositionStatus.FAILED
            )
            close_position_partial.message_error = (
                f"No se encontró la posición abierta para cerrar el resto de la posición."
            )
            await self._notify_position(close_position_partial)
            return False

        self._logger.info(
            f"Cierre de posición {close_position.id} completado exitosamente. Posiciones procesadas: {processed_positions}"
        )
        return True

    async def complete_position_closure(self, position: OpenPosition) -> bool:
        """
        Completa el cierre de una posición - lógica exacta del original
        """
        try:
            self._logger.debug(f"Completando cierre de posición {position.id}")

            was_removed = await self.open_position_queue.remove_position(position)
            if was_removed:
                self._logger.debug(f"Posición {position.id} removida de cola abierta, agregando a cola cerrada")
                await self.closed_position_queue.add_closed_position(position)
                self._logger.info(f"Posición {position.id} cerrada exitosamente")
            else:
                self._logger.warning(f"No se pudo remover posición {position.id} de la cola abierta")

            return was_removed
        except Exception as e:
            self._logger.error(f"Error completando cierre de posición {position.id}: {e}")
            return False

    async def _notify_position(self, position: Union[OpenPosition, ClosePosition, SubClosePosition]) -> None:
        """
        Envía posiciones a la cola de notificaciones de forma asíncrona.
        No bloquea el flujo principal del sistema.
        
        Args:
            position: Posición a notificar
        """
        try:
            position_id = getattr(position, 'id', 'unknown')

            if self.notification_queue:
                await self.notification_queue.add_position(position)
                self._logger.debug(f"Posición {position_id} enviada a notificaciones")
            else:
                self._logger.warning(f"No hay cola de notificaciones disponible para posición {position_id}")
        except Exception as e:
            position_id = getattr(position, 'id', 'unknown')
            self._logger.error(f"Error enviando posición {position_id} a notificaciones: {e}")

    async def get_closure_statistics(self) -> dict:
        """
        Obtiene estadísticas de cierre de posiciones.
        """
        try:
            self._logger.debug("Obteniendo estadísticas de cierre de posiciones")

            open_stats = await self.open_position_queue.get_stats()
            closed_stats = await self.closed_position_queue.get_stats()

            stats = {
                'open_positions': open_stats,
                'closed_positions': closed_stats,
                'total_processed': closed_stats.get('closed_count', 0) + open_stats.get('open_count', 0)
            }

            self._logger.info(f"Estadísticas de cierre obtenidas: {stats['total_processed']} posiciones totales")
            return stats
        except Exception as e:
            self._logger.error(f"Error obteniendo estadísticas de cierre: {e}")
            return {}
