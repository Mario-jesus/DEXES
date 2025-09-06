# -*- coding: utf-8 -*-
"""
Cola de posiciones cerradas con coordinación por token.
Su objetivo ya no es almacenar historial, sino retener temporalmente posiciones cerradas
hasta que no existan análisis pendientes de posiciones abiertas del mismo token,
evitando bloquear cierres de otros tokens.
"""
import asyncio
from collections import defaultdict, deque
from typing import Dict, Optional, Any, List, TYPE_CHECKING

from logging_system import AppLogger
from ...events import PositionEventBus, PositionAnalysisFinishedEvent
from ...data_management import TokenTraderManager
from ..models import ClosePosition, ClosePositionStatus
from .notification_queue import PositionNotificationQueue

if TYPE_CHECKING:
    from ..processors import PositionClosureProcessor
    from .analysis_position_queue import AnalysisPositionQueue
    from .open_position_queue import OpenPositionQueue


class ClosedPositionQueue:
    """Puerta de salida de posiciones de cierre coordinada por token."""

    def __init__(self,
            analysis_queue: 'AnalysisPositionQueue',
            position_event_bus: Optional[PositionEventBus] = None,
            open_position_queue: Optional['OpenPositionQueue'] = None,
            position_notification_queue: Optional[PositionNotificationQueue] = None,
            closure_processor: Optional['PositionClosureProcessor'] = None,
            token_trader_manager: Optional[TokenTraderManager] = None,
            max_size: Optional[int] = None,
            max_retries: int = 3
        ):
        self._logger = AppLogger(self.__class__.__name__)
        self.position_event_bus = position_event_bus
        self.analysis_queue = analysis_queue
        self.open_position_queue = open_position_queue
        self.position_notification_queue = position_notification_queue
        self.closure_processor = closure_processor
        self.token_trader_manager = token_trader_manager
        self.max_size = max_size
        self.max_retries = max_retries

        # Posiciones de cierre esperando liberación por token (token -> deque[ClosePosition])
        self._pending_by_token: Dict[str, deque[ClosePosition]] = defaultdict(lambda: deque(maxlen=self.max_size))

        # Métricas
        self._stats = {
            'added_count': 0,
            'finalized_count': 0,
            'failed_count': 0,
            'retry_count': 0,
        }

        # Concurrencia
        self._lock = asyncio.Lock()
        self._running = False
        self._process_task: Optional[asyncio.Task] = None

        # Señales de control para cierre ordenado
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._drained_event: asyncio.Event = asyncio.Event()
        self._wakeup_event: asyncio.Event = asyncio.Event()

        self._logger.debug("ClosedPositionQueue inicializada (modo coordinador, sin persistencia)")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self) -> None:
        try:
            if self._running:
                return

            # Estado inicial
            self._shutdown_event.clear()

            # Drained si no hay posiciones pendientes
            if sum(len(q) for q in self._pending_by_token.values()) == 0:
                self._drained_event.set()
            else:
                self._drained_event.clear()

            # Suscribirse a eventos
            if self.position_event_bus:
                self.position_event_bus.on_position_analysis_finished(self._on_analysis_finished)

            # Iniciar worker
            self._running = True
            self._process_task = asyncio.create_task(self._process_loop())
            self._logger.debug("ClosedPositionQueue worker iniciado")
        except Exception as e:
            self._logger.error(f"Error iniciando ClosedPositionQueue: {e}")

    async def stop(self) -> None:
        """Cierre ordenado: no aceptar más posiciones y drenar pendientes."""
        try:
            if not self._running and not self._process_task:
                return
            self._logger.info("Deteniendo ClosedPositionQueue (shutdown ordenado)")

            await self.shutdown()

            await self.join()

            # Señalar al loop que ya puede terminar
            self._running = False
            self._wakeup_event.set()

            if self._process_task:
                try:
                    await self._process_task
                finally:
                    self._process_task = None
            self._logger.debug("ClosedPositionQueue detenida exitosamente")
        except Exception as e:
            self._logger.error(f"Error durante la detención de ClosedPositionQueue: {e}")

    async def _force_drain_pending(self) -> None:
        """Remueve todas las posiciones pendientes marcándolas como fallidas por shutdown y notificando."""
        try:
            positions_to_fail: list[ClosePosition] = []
            async with self._lock:
                for token, queue in self._pending_by_token.items():
                    while len(queue) > 0:
                        pos = queue.popleft()
                        positions_to_fail.append(pos)

            for pos in positions_to_fail:
                try:
                    pos.status = ClosePositionStatus.FAILED
                    pos.message_error = "Finalizado por shutdown"
                    await self._update_token_trader_data(pos, is_failed=True)
                    await self._notify_position(pos)
                except Exception as e:
                    self._logger.error(f"Error finalizando por shutdown posición {getattr(pos, 'id', '?')}: {e}")

            # Actualizar drenado
            try:
                self._drained_event.set()
            except Exception:
                pass
        except Exception as e:
            self._logger.error(f"Error en _force_drain_pending: {e}")

    def set_closure_processor(self, closure_processor: 'PositionClosureProcessor') -> None:
        self.closure_processor = closure_processor

    async def add_closed_position(self, position: ClosePosition) -> bool:
        """
        Encola una ClosePosition y la deja en espera hasta que:
        - no haya análisis pendientes de OPENs del mismo token, y
        - la propia ClosePosition esté analizada.
        """
        try:
            if self._shutdown_event.is_set():
                self._logger.warning("Shutdown en progreso: no se aceptan nuevas posiciones cerradas")
                return False
            async with self._lock:
                token = position.token_address if hasattr(position, 'token_address') else (position.trader_trade_data.token_address if position.trader_trade_data else None)
                if not token:
                    self._logger.error(f"ClosePosition {position.id} no tiene token_address")
                    return False
                queue = self._pending_by_token[token]

                # Evitar duplicados por id dentro del mismo token
                if any(p.id == position.id for p in queue):
                    self._logger.debug(f"Posición {position.id} ya estaba en espera para token {token}")
                    return False

                queue.append(position)
                self._stats['added_count'] += 1
                # Al encolar, dejar en estado no drenado
                self._drained_event.clear()
                self._logger.info(f"ClosePosition {position.id} encolada para token {token}. En espera de condiciones de ejecución")
            # Despertar el loop para que procese más rápido
            self._wakeup_event.set()
            return True
        except Exception as e:
            self._logger.error(f"Error en add_closed_position({position.id}): {e}")
            return False

    async def _update_token_trader_data(self, position: ClosePosition, is_failed: bool) -> None:
        try:
            if self.token_trader_manager is None:
                return

            trader_token_queue = self._pending_by_token[position.token_address]

            if not is_failed:
                # Usar el nuevo método que actualiza TraderStats y TraderTokenStats simultáneamente
                timestamp = str(position.trader_trade_data.timestamp) if position.trader_trade_data and position.trader_trade_data.timestamp else None
                await self.token_trader_manager.update_trader_token_closed_position(
                    position.trader_wallet, 
                    position.token_address, 
                    position.amount_sol,
                    position.amount_sol_executed,
                    timestamp
                )
            else:
                # Usar el nuevo método que actualiza TraderStats y TraderTokenStats simultáneamente
                timestamp = str(position.trader_trade_data.timestamp) if position.trader_trade_data and position.trader_trade_data.timestamp else None
                await self.token_trader_manager.register_trader_token_failed_position(
                    position.trader_wallet, 
                    position.token_address, 
                    position.amount_sol,
                    timestamp
                )

                # Remover trader del token solo si no quedan posiciones
                if len(trader_token_queue) == 0:
                    await self.token_trader_manager.remove_trader_from_token(position.token_address, position.trader_wallet)
                    # Reconciliar contadores: si la cola está vacía, no deben quedar posiciones activas
                    try:
                        manager = self.token_trader_manager
                        if manager and hasattr(manager, 'reconcile_trader_token_active_positions'):
                            await getattr(manager, 'reconcile_trader_token_active_positions')(
                                position.trader_wallet,
                                position.token_address,
                                active_count=0
                            )
                    except Exception as e:
                        self._logger.warning(f"No se pudo reconciliar contadores para {position.trader_wallet}-{position.token_address}: {e}")

        except Exception as e:
            self._logger.error(f"Error registrando datos de token/trader para posición {position.id}: {e}", exc_info=True)

    async def _on_analysis_finished(self, event: PositionAnalysisFinishedEvent) -> None:
        try:
            if event.position_type != "close":
                return

            queue = self._pending_by_token[event.token_address]
            position_list = [position for position in queue if position.id == event.position_id]
            if not position_list:
                self._logger.warning(f"Position {event.position_id} not found in closed positions queue")
                return
            position = position_list[0]

            position.status = ClosePositionStatus.SUCCESS if event.success else ClosePositionStatus.FAILED

            if not event.success:
                error_kind = event.error_kind
                if error_kind == "slippage":
                    position.message_error = "Transaction failed due to slippage. The price moved unfavorably before the transaction could be completed."
                elif error_kind == "insufficient_tokens":
                    position.message_error = "insufficient tokens available to complete the operation."
                elif error_kind == "insufficient_lamports":
                    position.message_error = "insufficient SOL (lamports) to pay for the transaction or fees."
                elif error_kind == "transaction_not_found":
                    position.message_error = "The transaction was not found on the Solana blockchain."
                elif error_kind == "insufficient_funds_for_rent":
                    position.message_error = "insufficient SOL to cover the account rent requirement."
                else:
                    position.message_error = event.error_message or "Unknown error occurred during transaction analysis."

                if await self._remove_position_from_queue(position.id, position.token_address):
                    self._logger.info(f"Position {position.id} removed from closed positions queue")
                else:
                    self._logger.warning(f"Position {position.id} not removed from closed positions queue")

                await self._update_token_trader_data(position, is_failed=True)

                await self._notify_position(position)
            else:
                await self._update_token_trader_data(position, is_failed=False)

            position.is_analyzed = True
            self._logger.info(f"Position {position.id} analysis finished with status {position.status}")

            # Despertar el loop de cierres por si ahora se puede liberar
            try:
                await self.wake()
            except Exception:
                pass

        except Exception as e:
            self._logger.error(f"Error en on_analysis_finished({position.id}): {e}")

    async def _process_loop(self) -> None:
        self._logger.debug("ClosedPositionQueue loop iniciado")
        while self._running or self._shutdown_event.is_set():
            try:
                did_process = await self._process_pending()
                # Esperar cuando no haya trabajo o cuando hay trabajo pero está bloqueado por análisis
                total_pending = sum(len(q) for q in self._pending_by_token.values())
                if total_pending == 0 or not did_process:
                    # Esperar a wakeup
                    await self._wakeup_event.wait()
                    self._wakeup_event.clear()
                else:
                    await asyncio.sleep(1)

                # Si estamos en shutdown y ya no quedan pendientes, terminar
                if self._shutdown_event.is_set() and sum(len(q) for q in self._pending_by_token.values()) == 0:
                    self._drained_event.set()
                    break
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error en loop de ClosedPositionQueue: {e}")
                await asyncio.sleep(1)

    async def _remove_position_from_queue(self, position_id: str, token: str) -> bool:
        """
        Remueve una posición de la cola por token de forma segura.
        
        Args:
            position_id: ID de la posición a remover
            token: Token del cual remover la posición
            
        Returns:
            True si se removió exitosamente, False en caso contrario
        """
        try:
            async with self._lock:
                queue = self._pending_by_token[token]
                if len(queue) > 0 and queue[0].id == position_id:
                    # Si es la cabeza de la cola, usar popleft para eficiencia
                    queue.popleft()
                    return True
                else:
                    # Buscar y remover por ID en caso de desincronización
                    for item in list(queue):
                        if item.id == position_id:
                            queue.remove(item)
                            return True
                return False
        except Exception as e:
            self._logger.error(f"Error removiendo posición {position_id} de token {token}: {e}")
            return False

        finally:
            # Actualizar estado drenado
            try:
                total = sum(len(q) for q in self._pending_by_token.values())
                if total == 0:
                    self._drained_event.set()
                else:
                    self._drained_event.clear()
            except Exception:
                pass

    async def _process_pending(self) -> bool:
        processed_any = False
        self._logger.debug(f"Procesando cola de posiciones cerradas")
        # Revisar por token si aún hay análisis de OPENs; si no, liberar todas las posiciones de ese token
        tokens_snapshot: List[str] = []
        async with self._lock:
            tokens_snapshot = [t for t, q in self._pending_by_token.items() if len(q) > 0]

        if not tokens_snapshot:
            return False

        for token in tokens_snapshot:
            try:
                head_is_analyzed = await self._is_head_open_analysis_analyzed_for_token(token)
            except Exception as e:
                self._logger.error(f"Error consultando análisis pendientes para token {token}: {e}")
                head_is_analyzed = False

            if not head_is_analyzed:
                # Aún no liberar este token (cabeza no analizada)
                self._logger.debug(f"Aún no liberar este token {token}")
                continue

            # Procesar solo la cabeza de la cola por token (FIFO)
            pos: Optional[ClosePosition] = None
            async with self._lock:
                queue = self._pending_by_token[token]
                if len(queue) > 0:
                    pos = queue[0]

            if not pos:
                self._logger.debug(f"No se encontró posición para token {token}")
                continue

            # Requerir que la ClosePosition esté analizada
            is_analyzed = False
            try:
                is_analyzed = bool(pos.is_analyzed) or bool(pos.get_is_analyzed())
            except Exception:
                is_analyzed = False

            if not is_analyzed:
                # No bloquear otros tokens; simplemente saltar este token por ahora
                self._logger.debug(f"No bloquear otros tokens; simplemente saltar este token por ahora {token}")
                continue

            # Ejecutar cierre usando el procesador
            if not self.closure_processor:
                self._logger.error("ClosureProcessor no configurado en ClosedPositionQueue")
                continue

            try:
                success = await self.closure_processor.process_position_closure(pos)
            except Exception as e:
                self._logger.error(f"Error ejecutando cierre para {pos.id}: {e}")
                success = False

            if success:
                self._logger.info(f"ClosePosition {pos.id} ejecutada para token {token}")
            else:
                self._logger.warning(f"No se pudo ejecutar ClosePosition {pos.id}")

            await self._remove_position_from_queue(pos.id, token)
            self._stats['finalized_count'] += 1
            # Despertar para continuar procesando
            self._wakeup_event.set()
            processed_any = True
        return processed_any

    async def wake(self) -> None:
        """Despierta el loop para intentar procesar posiciones pendientes."""
        try:
            self._wakeup_event.set()
        except Exception:
            pass

    async def _is_head_open_analysis_analyzed_for_token(self, token_address: str) -> bool:
        """Consulta directa al OpenPositionQueue."""
        try:
            # Método preferido
            if not self.open_position_queue:
                self._logger.error("OpenPositionQueue no configurado en ClosedPositionQueue")
                return True
            is_analyzed = await self.open_position_queue.is_head_open_analysis_analyzed_for_token(token_address)
            self._logger.debug(f"_is_head_open_analysis_analyzed_for_token({token_address}): is_analyzed: {is_analyzed}")
            return is_analyzed
        except Exception as e:
            self._logger.error(f"Error en _is_head_open_analysis_analyzed_for_token({token_address}): {e}")
            return True

    async def _notify_position(self, position: ClosePosition) -> None:
        try:
            position_id = position.id

            if self.position_notification_queue:
                await self.position_notification_queue.add_position(position)
            else:
                self._logger.warning(f"No hay cola de notificaciones disponible para posición {position_id}")

        except Exception as e:
            position_id = position.id
            self._logger.error(f"Error enviando posición {position_id} a notificaciones: {e}", exc_info=True)

    async def get_queue_size(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> int:
        try:
            async with self._lock:
                if token_address:
                    return len(self._pending_by_token.get(token_address, deque()))
                if trader_address:
                    total = 0
                    for queue in self._pending_by_token.values():
                        total += sum(1 for p in queue if p.trader_wallet == trader_address)
                    return total
                return sum(len(q) for q in self._pending_by_token.values())
        except Exception as e:
            self._logger.error(f"Error obteniendo tamaño de cola: {e}")
            return 0

    async def get_stats(self) -> Dict[str, Any]:
        try:
            async with self._lock:
                pending_total = sum(len(q) for q in self._pending_by_token.values())
                pending_tokens = {token: len(q) for token, q in self._pending_by_token.items() if len(q) > 0}
                stats = {
                    'closed_count': self._stats['finalized_count'],
                    'pending_total': pending_total,
                    'pending_tokens': pending_tokens,
                    'added_count': self._stats['added_count'],
                    'failed_count': self._stats['failed_count'],
                    'retry_count': self._stats['retry_count'],
                    'max_retries': self.max_retries
                }
                return stats
        except Exception as e:
            self._logger.error(f"Error en get_stats: {e}")
            return {}

    async def save_state(self):
        # Sin persistencia; método mantenido por compatibilidad
        return

    # ===================== Shutdown/Join helpers =====================
    async def shutdown(self) -> None:
        """Señaliza que no se aceptarán más posiciones y comienza drenado."""
        try:
            self._shutdown_event.set()
            self._wakeup_event.set()
        except Exception as e:
            self._logger.error(f"Error en shutdown(): {e}")

    async def join(self) -> None:
        """Bloquea hasta que no queden posiciones pendientes por token."""
        try:
            # Si ya está drenado, retorna inmediatamente
            total = sum(len(q) for q in self._pending_by_token.values())
            if total == 0:
                self._drained_event.set()
                return
            await self._drained_event.wait()
        except Exception as e:
            self._logger.error(f"Error en join(): {e}")
