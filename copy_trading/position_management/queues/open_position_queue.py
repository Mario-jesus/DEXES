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
from typing import Dict, List, Optional, Any, Tuple, Union
from decimal import getcontext

from logging_system import AppLogger
from ...data_management import TokenTraderManager
from ..models import OpenPosition, ClosePosition, SubClosePosition, PositionStatus
from .notification_queue import PositionNotificationQueue

getcontext().prec = 26


class OpenPositionQueue:
    """Gestión de posiciones abiertas con persistencia, agrupadas por trader y luego por token."""

    def __init__(self, data_path: str = "copy_trading/data", max_size: Optional[int] = None, token_trader_manager: Optional[TokenTraderManager] = None, position_notification_queue: Optional[PositionNotificationQueue] = None):
        self.data_path = Path(data_path)
        self.max_size = max_size
        self.token_trader_manager = token_trader_manager
        self._logger = AppLogger(self.__class__.__name__)
        self.position_notification_queue = position_notification_queue

        # Cola principal: Diccionario anidado [trader_wallet -> token_address -> deque]
        self.open_positions_queue: Dict[str, Dict[str, deque[OpenPosition]]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=self.max_size)))

        self._lock = asyncio.Lock()

        self.data_path.mkdir(parents=True, exist_ok=True)
        self.open_file = self.data_path / "open_positions.json"
        self._initialize_files()

        self._logger.debug(f"OpenPositionQueue inicializado - Data path: {self.data_path}, Max size: {self.max_size}")

    async def __aenter__(self):
        self._logger.debug("Iniciando carga de datos desde disco")
        await self.load_from_disk()
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

            async with self._lock:
                trader_token_queue = self.open_positions_queue[position.trader_wallet][position.token_address]

                if any(p.id == position.id for p in trader_token_queue):
                    self._logger.warning(f"Posición {position.id} ya existe para el trader {position.trader_wallet} y token {position.token_address}.")
                    return False

                position.status = PositionStatus.OPEN
                trader_token_queue.append(position)

            # Registrar datos del token, trader y posiciones de apertura o cierre
            await self._register_token_trader_data(position, trader_token_queue, True)

            # Notificar posición
            await self._notify_position(position)

            # Guardar estado
            await self._save_open()

            return True

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
            async with self._lock:
                if trader_address and token_address:
                    # Obtener primera posición de un trader y token específicos
                    queue = self.open_positions_queue.get(trader_address, {}).get(token_address, deque())
                    return queue[0] if queue else None

                elif trader_address:
                    # Obtener primera posición de un trader (de cualquier token)
                    trader_tokens = self.open_positions_queue.get(trader_address, {})
                    for token_queue in trader_tokens.values():
                        if token_queue:
                            return token_queue[0]
                    return None

                else:
                    # Obtener primera posición de cualquier trader y token
                    for trader_tokens in self.open_positions_queue.values():
                        for token_queue in trader_tokens.values():
                            if token_queue:
                                return token_queue[0]
                    return None
        except Exception as e:
            self._logger.error(f"Error obteniendo primera posición: {e}")
            return None

    async def remove_position(self, position: OpenPosition) -> bool:
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
                await self._register_token_trader_data(position, trader_token_queue, False)

                # Notificar cierre completo
                await self._notify_position(position)

                await self._save_open()

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
            if self.token_trader_manager:
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

            # Agregar nombre del trader a los metadatos de la posición
            if self.token_trader_manager and is_open and len(queue) == 1:
                trader_stats = await self.token_trader_manager.get_trader_stats(position.trader_wallet)
                position.add_metadata('trader_nickname', trader_stats.nickname)

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

    async def get_open_positions(self, trader_address: Optional[str] = None, token_address: Optional[str] = None, _lock_acquired: bool = False) -> List[OpenPosition]:
        try:
            # Solo adquirir el lock si no lo tenemos ya
            if not _lock_acquired:
                async with self._lock:
                    return await self._get_open_positions_internal(trader_address, token_address)
            else:
                return await self._get_open_positions_internal(trader_address, token_address)

        except Exception as e:
            self._logger.error(f"Error en get_open_positions: {e}")
            raise

    async def _get_open_positions_internal(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> List[OpenPosition]:
        """Método interno que asume que el lock ya está adquirido."""
        try:
            if trader_address and token_address:
                return list(self.open_positions_queue.get(trader_address, {}).get(token_address, deque()))

            if trader_address:
                trader_positions = []
                trader_tokens = self.open_positions_queue.get(trader_address, {})
                for token_addr, queue in trader_tokens.items():
                    trader_positions.extend(queue)
                return trader_positions

            # Caso 3: todas las posiciones
            all_positions = []
            for trader_wallet, tokens in self.open_positions_queue.items():
                for token_addr, queue in tokens.items():
                    all_positions.extend(queue)

            return all_positions
        except Exception as e:
            self._logger.error(f"Error en _get_open_positions_internal: {e}")
            return []

    async def get_queue_size(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> int:
        """
        Obtiene el tamaño de la cola de un token, el total de posiciones abiertas de un trader o el total general de posiciones abiertas.
        
        Args:
            trader_address: Wallet del trader (opcional)
            token_address: Dirección del token (opcional)
            
        Returns:
            Número de posiciones en la cola
        """
        try:
            async with self._lock:
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

    async def get_stats(self) -> Dict[str, Any]:
        try:
            async with self._lock:
                all_positions = await self.get_open_positions(_lock_acquired=True)
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

    async def _notify_position(self, position: Union[OpenPosition, ClosePosition, SubClosePosition]):
        """
        Envía posiciones a la cola de notificaciones de forma asíncrona.
        No bloquea el flujo principal del sistema.
        """
        try:
            position_id = getattr(position, 'id', 'unknown')

            if self.position_notification_queue:
                await self.position_notification_queue.add_position(position)
            else:
                self._logger.warning(f"No hay cola de notificaciones disponible para posición {position_id}")

        except Exception as e:
            position_id = getattr(position, 'id', 'unknown')
            self._logger.error(f"Error enviando posición {position_id} a notificaciones: {e}", exc_info=True)

    async def stop(self) -> None:
        """Detiene el worker de seguimiento y guarda el estado."""
        try:
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
