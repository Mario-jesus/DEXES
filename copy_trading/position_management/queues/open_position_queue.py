# -*- coding: utf-8 -*-
"""
Sistema de gestión de posiciones abiertas para Copy Trading.
Utiliza una cola de posiciones por trader y por token.
"""
import aiofiles
import json
import asyncio
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from decimal import getcontext

from logging_system import AppLogger
from ...events import PositionEventBus, PositionAnalysisFinishedEvent
from ...data_management import TokenTraderManager
from ..models import OpenPosition, PositionStatus
from .notification_queue import PositionNotificationQueue

getcontext().prec = 26


class OpenPositionQueue:
    """Gestión de posiciones abiertas con persistencia, agrupadas por trader y luego por token."""

    def __init__(self, data_path: str = "copy_trading/data", max_size: Optional[int] = None, position_event_bus: Optional[PositionEventBus] = None, token_trader_manager: Optional[TokenTraderManager] = None, position_notification_queue: Optional[PositionNotificationQueue] = None):
        self.data_path = Path(data_path)
        self.max_size = max_size
        self.position_event_bus = position_event_bus
        self.token_trader_manager = token_trader_manager
        self._logger = AppLogger(self.__class__.__name__)
        self.position_notification_queue = position_notification_queue

        # Cola principal: Diccionario anidado [trader_wallet -> token_address -> deque]
        self.open_positions_queue: Dict[str, Dict[str, deque[OpenPosition]]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=self.max_size)))

        self._lock = asyncio.Lock()
        # Señales de control para apagado ordenado
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._drained_event: asyncio.Event = asyncio.Event()

        self.data_path.mkdir(parents=True, exist_ok=True)
        self.open_file = self.data_path / "open_positions.json"
        self._initialize_files()

        self._logger.debug(f"OpenPositionQueue inicializado - Data path: {self.data_path}, Max size: {self.max_size}")

    async def __aenter__(self):
        try:
            await self.start()
        except Exception as e:
            self._logger.error(f"Error iniciando OpenPositionQueue: {e}")
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            await self.stop()
            self._logger.debug("OpenPositionQueue cerrado con async context manager")
        except Exception as e:
            self._logger.error(f"Error cerrando OpenPositionQueue: {e}")

    async def add_open_position(self, position: OpenPosition) -> bool:
        try:
            self._logger.info(f"Agregando posición abierta: {position.id}")

            if self._shutdown_event.is_set():
                self._logger.warning("Shutdown en progreso: no se aceptan nuevas posiciones abiertas")
                return False

            async with self._lock:
                trader_token_queue = self.open_positions_queue[position.trader_wallet][position.token_address]

                duplicate_id = any(p.id == position.id for p in trader_token_queue)
                duplicate_signature = False
                if not duplicate_id:
                    duplicate_signature = any(p.signature == position.signature for p in trader_token_queue)
                is_duplicate = duplicate_id or duplicate_signature

                if not is_duplicate:
                    position.status = PositionStatus.OPEN
                    trader_token_queue.append(position)
                    # Al encolar, marcar que no está drenado
                    self._drained_event.clear()

            if is_duplicate:
                position.status = PositionStatus.FAILED
                if duplicate_id:
                    position.message_error = "El id de la posición ya existe dentro de la cola"
                    self._logger.warning(f"Posición {position.id} ya existe para el trader {position.trader_wallet} y token {position.token_address}.")
                else:
                    position.message_error = "El signature de la posición ya existe dentro de la cola"
                    self._logger.warning(f"Posición {position.signature} ya existe para el trader {position.trader_wallet} y token {position.token_address}.")
            else:
                # Registrar datos del token, trader y posiciones de apertura o cierre
                await self._register_token_trader_data(position, trader_token_queue, True)
                # Guardar estado
                await self._save_open()

            # Notificar posición
            await self._notify_position(position)

            return not is_duplicate

        except Exception as e:
            self._logger.error(f"Error agregando posición abierta {position.id}: {e}", exc_info=True)
            return False

    async def get_first_position(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> Optional[OpenPosition]:
        """
        Obtiene la primera posición de la cola (FIFO).
        
        Args:
            trader_address: Wallet del trader (opcional)
            token_address: Dirección del token (opcional)
            
        Returns:
            La primera posición de la cola o None si está vacía
        """
        try:
            self._logger.debug(f"open_positions_queue snapshot disponible: {bool(self.open_positions_queue)}")
            async with self._lock:
                if trader_address and token_address:
                    # Obtener primera posición de un trader y token específicos
                    queue = self.open_positions_queue.get(trader_address, {}).get(token_address, deque())
                    self._logger.debug(f"Buscando primera posición para trader {trader_address} y token {token_address}. Tamaño de la cola: {len(queue) if queue else 0}")
                    head = next(iter(queue), None)
                    return head

                elif trader_address:
                    # Obtener primera posición de un trader (de cualquier token)
                    trader_tokens = self.open_positions_queue.get(trader_address, {})
                    self._logger.debug(f"Buscando primera posición para trader {trader_address} en cualquier token. Tokens encontrados: {list(trader_tokens.keys())}")
                    for token, token_queue in trader_tokens.items():
                        if token_queue:
                            head = next(iter(token_queue), None)
                            if head is not None:
                                self._logger.debug(f"Primera posición encontrada para trader {trader_address} en token {token}: {head.id}")
                                return head
                    self._logger.debug(f"No se encontró ninguna posición para trader {trader_address}")
                    return None

                elif token_address:
                    # Obtener primera posición para un token (de cualquier trader)
                    self._logger.debug(f"Buscando primera posición para token {token_address} en cualquier trader.")
                    for trader, trader_tokens in self.open_positions_queue.items():
                        queue = trader_tokens.get(token_address)
                        if queue:
                            head = next(iter(queue), None)
                            if head is not None:
                                self._logger.debug(f"Primera posición encontrada para token {token_address} en trader {trader}: {head.id}")
                                return head
                    self._logger.debug(f"No se encontró ninguna posición para token {token_address}")
                    return None

                else:
                    # Obtener primera posición de cualquier trader y token
                    self._logger.debug("Buscando primera posición en cualquier trader y token.")
                    for trader, trader_tokens in self.open_positions_queue.items():
                        for token, token_queue in trader_tokens.items():
                            if token_queue:
                                head = next(iter(token_queue), None)
                                if head is not None:
                                    self._logger.debug(f"Primera posición encontrada para trader {trader} en token {token}: {head.id}")
                                    return head
                    self._logger.debug("No se encontró ninguna posición en la cola global.")
                    return None
        except Exception as e:
            self._logger.error(f"Error obteniendo primera posición: {e}")
            return None

    async def remove_position(self, position: OpenPosition, register_data: bool = True) -> bool:
        try:
            was_removed = False
            trader_token_queue = None

            async with self._lock:
                trader_token_queue = self.open_positions_queue[position.trader_wallet][position.token_address]
                if position in trader_token_queue:
                    trader_token_queue.remove(position)
                    was_removed = True

            if was_removed and trader_token_queue is not None:
                # Registrar datos del token, trader y posiciones de apertura o cierre (fuera del lock para evitar deadlock)
                if register_data:
                    await self._register_token_trader_data(position, trader_token_queue, False)

                # Notificar cierre completo
                await self._notify_position(position)

                await self._save_open()

                # Actualizar estado drenado si ya no quedan posiciones abiertas
                try:
                    total = 0
                    async with self._lock:
                        for trader_tokens in self.open_positions_queue.values():
                            for queue in trader_tokens.values():
                                total += len(queue)
                    if total == 0:
                        self._drained_event.set()
                except Exception:
                    pass

            return was_removed
        except Exception as e:
            self._logger.error(f"Error removiendo posición {position.id}: {e}")
            return False

    async def get_position_by_id(self, position_id: str) -> Optional[OpenPosition]:
        try:
            async with self._lock:
                position, _, _ = await self._find_position_in_queue(position_id)
                return position
        except Exception as e:
            self._logger.error(f"Error buscando posición por ID {position_id}: {e}")
            return None

    # Helper para registrar datos del token, trader y posiciones de apertura o cierre
    async def _register_token_trader_data(self, position: OpenPosition, queue: deque[OpenPosition], is_open: bool) -> None:
        """
        Registra datos del token, trader y posiciones de apertura o cierre.
        Usa el nuevo servicio de sincronización para actualizar ambos modelos simultáneamente.
        
        Args:
            position: Posición a registrar
            queue: Cola de posiciones
            is_open: True si es una posición abierta, False si es una posición cerrada
        """
        try:
            if self.token_trader_manager is None:
                return

            if is_open:
                # Usar el nuevo método que actualiza TraderStats y TraderTokenStats simultáneamente
                timestamp = str(position.trader_trade_data.timestamp) if position.trader_trade_data and position.trader_trade_data.timestamp else None
                await self.token_trader_manager.register_trader_token_open_position(
                    position.trader_wallet, 
                    position.token_address, 
                    position.amount_sol,
                    timestamp
                )

                # Agregar trader al token solo si es la primera posición
                if len(queue) == 1:
                    await self.token_trader_manager.add_trader_to_token(position.token_address, position.trader_wallet)
            else:
                # Usar el nuevo método que actualiza TraderStats y TraderTokenStats simultáneamente
                timestamp = str(position.trader_trade_data.timestamp) if position.trader_trade_data and position.trader_trade_data.timestamp else None
                await self.token_trader_manager.register_trader_token_closed_position(
                    position.trader_wallet, 
                    position.token_address, 
                    position.amount_sol,
                    timestamp
                )

                # Remover trader del token solo si no quedan posiciones
                if len(queue) == 0:
                    await self.token_trader_manager.remove_trader_from_token(position.token_address, position.trader_wallet)
                    # Reconciliar contadores cuando la cola queda vacía
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

            # Agregar nombre del trader a los metadatos de la posición
            if self.token_trader_manager and is_open and len(queue) == 1:
                trader_stats = await self.token_trader_manager.get_trader_stats(position.trader_wallet)
                position.add_metadata('trader_nickname', trader_stats.nickname)

        except Exception as e:
            self._logger.error(f"Error registrando datos de token/trader para posición {position.id}: {e}", exc_info=True)

    async def _update_token_trader_data(self, position: OpenPosition, is_failed: bool) -> None:
        try:
            if self.token_trader_manager is None:
                return

            trader_token_queue = self.open_positions_queue[position.trader_wallet][position.token_address]

            if not is_failed:
                # Usar el nuevo método que actualiza TraderStats y TraderTokenStats simultáneamente
                timestamp = str(position.trader_trade_data.timestamp) if position.trader_trade_data and position.trader_trade_data.timestamp else None
                await self.token_trader_manager.update_trader_token_open_position(
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

    async def _find_position_in_queue(self, position_id: str) -> Tuple[Optional[OpenPosition], Optional[str], Optional[str]]:
        """Helper para encontrar una posición y sus claves asociadas (trader, token)."""
        try:
            for trader_wallet, tokens in self.open_positions_queue.items():
                for token_address, queue in tokens.items():
                    for position in queue:
                        if position.id == position_id:
                            return position, trader_wallet, token_address
            return None, None, None
        except Exception as e:
            self._logger.error(f"Error buscando posición {position_id} en cola: {e}")
            return None, None, None

    def get_open_positions(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> List[OpenPosition]:
        return self._get_open_positions_internal(trader_address, token_address)

    def _get_open_positions_internal(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> List[OpenPosition]:
        """Método interno que asume que el lock ya está adquirido."""
        try:
            if trader_address and token_address:
                return list(self.open_positions_queue.get(trader_address, {}).get(token_address, deque()))

            if trader_address:
                trader_positions: List[OpenPosition] = []
                trader_tokens = self.open_positions_queue.get(trader_address, {})
                for _, queue in trader_tokens.items():
                    trader_positions.extend(queue)
                return trader_positions

            if token_address:
                token_positions: List[OpenPosition] = []
                for _, tokens in self.open_positions_queue.items():
                    for token_address, queue in tokens.items():
                        if token_address == token_address:
                            token_positions.extend(queue)
                return token_positions

            # Caso 3: todas las posiciones
            all_positions: List[OpenPosition] = []
            for _, tokens in self.open_positions_queue.items():
                for _, queue in tokens.items():
                    all_positions.extend(queue)

            return all_positions
        except Exception as e:
            self._logger.error(f"Error en _get_open_positions_internal: {e}")
            return []

    async def handle_failed_position(self, position: OpenPosition, event: PositionAnalysisFinishedEvent) -> None:
        try:
            self._logger.debug(f"Manejando resultado del análisis de posición {event.position_id}")

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

                if await self.remove_position(position, register_data=False):
                    self._logger.info(f"Position {position.id} removed from open positions queue")
                else:
                    self._logger.warning(f"Position {position.id} not removed from open positions queue")

                self._logger.debug(f"Notificando resultado del análisis de posición {position.id}")
                await self._notify_position(position)

        except Exception as e:
            self._logger.error(f"Error updating position {event.position_id}: {e}")

    def get_queue_size(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> int:
        """
        Obtiene el tamaño de la cola de un token, el total de posiciones abiertas de un trader o el total general de posiciones abiertas.
        
        Args:
            trader_address: Wallet del trader (opcional)
            token_address: Dirección del token (opcional)
            
        Returns:
            Número de posiciones en la cola
        """
        try:
            if trader_address and token_address:
                return len(self.open_positions_queue.get(trader_address, {}).get(token_address, deque()))

            elif trader_address:
                total_size = 0
                for queue in self.open_positions_queue.get(trader_address, {}).values():
                    total_size += len(queue)
                return total_size

            else:
                total_size = 0
                for tokens in self.open_positions_queue.values():
                    for queue in tokens.values():
                        total_size += len(queue)
                return total_size
        except Exception as e:
            self._logger.error(f"Error obteniendo tamaño de cola: {e}")
            return 0

    async def _on_analysis_finished(self, event: PositionAnalysisFinishedEvent) -> None:
        try:
            if event.position_type != "open":
                return

            self._logger.debug(f"Manejando resultado del análisis de posición {event.position_id}")

            positions = self.get_open_positions(
                trader_address=event.trader_wallet,
                token_address=event.token_address
            )

            position_list = [position for position in positions if position.id == event.position_id]
            if not position_list:
                self._logger.warning(f"Position {event.position_id} not found in open positions queue")
                return
            position = position_list[0]

            position.status = PositionStatus.OPEN if event.success else PositionStatus.FAILED

            if not event.success:
                await self._update_token_trader_data(position, is_failed=True)
                await self.handle_failed_position(position, event)
            else:
                await self._update_token_trader_data(position, is_failed=False)

            position.is_analyzed = True
            self._logger.info(f"Position {position.id} analysis finished with status {position.status}")

        except Exception as e:
            self._logger.error(f"Error updating position {event.position_id}: {e}")

    async def is_head_open_analysis_analyzed_for_token(self, token_address: str) -> bool:
        """Indica si la cabeza de la cola de análisis para el token dado ya fue analizada."""
        try:
            self._logger.debug(f"Verificando si la cabeza de la cola de análisis para el token {token_address} ya fue analizada.")
            position = await self.get_first_position(token_address=token_address)
            if position:
                analyzed = position.get_is_analyzed()
                self._logger.debug(f"Posición encontrada para token {token_address}: {position.id}, is_analyzed={analyzed}")
                return analyzed
            self._logger.debug(f"No se encontró posición para token {token_address}, se considera analizada.")
            return True
        except Exception as e:
            self._logger.error(f"Error en is_head_open_analysis_analyzed_for_token({token_address}): {e}")
            return True

    async def get_stats(self) -> Dict[str, Any]:
        try:
            async with self._lock:
                all_positions = self.get_open_positions()
                open_positions = [p for p in all_positions if p.status != PositionStatus.CLOSED]

                total_open_value = sum(float(p.amount_sol) for p in open_positions)
                #total_unrealized_pnl = sum(p.unrealized_pnl_sol or 0 for p in open_positions)
                unique_tokens = len(set(pos.token_address for pos in open_positions))

                return {
                    'open_count': len(open_positions),
                    'total_open_value_sol': total_open_value,
                    #'total_unrealized_pnl_sol': total_unrealized_pnl,
                    'unique_traders': len(self.open_positions_queue),
                    'unique_tokens': unique_tokens,
                }

        except Exception as e:
            self._logger.error(f"Error en get_stats: {e}")
            raise

    async def load_from_disk(self):
        try:
            async with self._lock:
                if not self.open_file.exists():
                    return

                async with aiofiles.open(self.open_file, 'r') as f:
                    content = await f.read()
                    if content.strip():
                        data: Dict[str, Dict[str, List[Dict]]] = json.loads(content)
                        self.open_positions_queue.clear()
                        for trader_wallet, tokens_data in data.items():
                            for token_address, positions_data in tokens_data.items():
                                trader_token_deque = deque(maxlen=self.max_size)
                                for pos_data in positions_data:
                                    trader_token_deque.append(OpenPosition.from_dict(pos_data))
                                self.open_positions_queue[trader_wallet][token_address] = trader_token_deque
            # Actualizar estado drenado tras carga
            try:
                total = 0
                async with self._lock:
                    for trader_tokens in self.open_positions_queue.values():
                        for queue in trader_tokens.values():
                            total += len(queue)
                if total == 0:
                    self._drained_event.set()
                else:
                    self._drained_event.clear()
            except Exception:
                self._drained_event.clear()
        except (json.JSONDecodeError, Exception) as e:
            self._logger.warning(f"Error cargando open_positions.json: {e}")

    async def save_state(self):
        await self._save_open()

    async def _save_open(self):
        try:
            data_to_save = defaultdict(dict)
            for trader_wallet, tokens in self.open_positions_queue.items():
                for token_address, queue in tokens.items():
                    if queue:  # Solo guardar si la cola no está vacía
                        posiciones_dict = [p.to_dict() for p in queue]
                        data_to_save[trader_wallet][token_address] = posiciones_dict

            async with aiofiles.open(self.open_file, 'w') as f:
                await f.write(json.dumps(data_to_save, indent=2))

        except Exception as e:
            self._logger.error(f"Error guardando posiciones abiertas en {self.open_file}: {e}", exc_info=True)
            raise

    def _initialize_files(self):
        try:
            if not self.open_file.exists() or self.open_file.stat().st_size == 0:
                with open(self.open_file, 'w') as f:
                    f.write('{}') # Inicializar como un objeto JSON vacío
        except Exception as e:
            self._logger.error(f"Error inicializando {self.open_file.name}: {e}")

    async def _notify_position(self, position: OpenPosition):
        """
        Envía posiciones a la cola de notificaciones de forma asíncrona.
        No bloquea el flujo principal del sistema.
        """
        try:
            position_id = position.id

            if self.position_notification_queue:
                await self.position_notification_queue.add_position(position)
            else:
                self._logger.warning(f"No hay cola de notificaciones disponible para posición {position_id}")

        except Exception as e:
            position_id = position.id
            self._logger.error(f"Error enviando posición {position_id} a notificaciones: {e}", exc_info=True)

    async def start(self) -> None:
        """Inicia el worker de seguimiento y carga el estado."""
        try:
            self._logger.debug("Iniciando carga de datos desde disco")
            await self.load_from_disk()

            # Limpiar señal de shutdown
            self._shutdown_event.clear()

            # Actualizar estado drenado después de cargar
            try:
                total = 0
                for trader_tokens in self.open_positions_queue.values():
                    for queue in trader_tokens.values():
                        total += len(queue)
                if total == 0:
                    self._drained_event.set()
                else:
                    self._drained_event.clear()
            except Exception:
                self._drained_event.clear()

            # Suscribirse a eventos
            if self.position_event_bus:
                self.position_event_bus.on_position_analysis_finished(self._on_analysis_finished)
        except Exception as e:
            self._logger.error(f"Error iniciando OpenPositionQueue: {e}")
            raise

    async def stop(self) -> None:
        """Detiene el worker de seguimiento y guarda el estado."""
        try:
            # Shutdown ordenado: no aceptar nuevas posiciones y esperar drenado
            await self.shutdown()
            await self.join()
            # Guardar estado final
            await self.save_state()

        except Exception as e:
            self._logger.error(f"Error durante la detención: {e}")
            raise

    def _get_file_path(self, status: PositionStatus) -> Path:
        """Obtiene la ruta del archivo según el estado de la posición."""
        try:
            if status == PositionStatus.OPEN:
                return self.open_file
            else:
                raise ValueError(f"Estado de posición no válido: {status}")
        except Exception as e:
            self._logger.error(f"Error obteniendo ruta de archivo para estado {status}: {e}")
            raise

    # ===================== Shutdown/Join helpers =====================
    async def shutdown(self) -> None:
        """Señaliza que no se aceptarán más posiciones abiertas."""
        try:
            self._shutdown_event.set()
        except Exception as e:
            self._logger.error(f"Error en shutdown(): {e}")

    async def join(self) -> None:
        """Bloquea hasta que no queden posiciones abiertas."""
        try:
            # Si ya está drenado, retorna inmediatamente
            total = 0
            async with self._lock:
                for trader_tokens in self.open_positions_queue.values():
                    for queue in trader_tokens.values():
                        total += len(queue)
            if total == 0:
                self._drained_event.set()
                return
            await self._drained_event.wait()
        except Exception as e:
            self._logger.error(f"Error en join(): {e}")
