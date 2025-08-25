# -*- coding: utf-8 -*-
"""
Sistema de cola de posiciones pendientes para Copy Trading
"""
import aiofiles
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any

from logging_system import AppLogger
from ..models import PositionTraderTradeData


class PendingPositionQueue:
    """Cola FIFO de posiciones pendientes con persistencia"""

    def __init__(self, data_path: str = "copy_trading/data", max_size: Optional[int] = None):
        self._logger = AppLogger(self.__class__.__name__)
        self.data_path = Path(data_path)
        self.max_size = max_size

        # Usar asyncio.Queue en lugar de deque
        self.pending_queue: asyncio.Queue[PositionTraderTradeData] = asyncio.Queue(maxsize=max_size if max_size else 0)

        self._lock = asyncio.Lock()

        self.data_path.mkdir(parents=True, exist_ok=True)

        self.pending_file = self.data_path / "pending_positions.json"

        self._initialize_file()

    async def __aenter__(self):
        await self.load_from_disk()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Guarda el estado al salir del contexto."""
        await self.stop()

    async def start(self):
        """Carga el estado inicial de la cola."""
        self._logger.debug("Iniciando PendingPositionQueue")
        await self.load_from_disk()
        self._logger.debug("PendingPositionQueue iniciada correctamente")

    async def stop(self):
        """Guarda el estado de la cola."""
        self._logger.info("Deteniendo PendingPositionQueue")
        await self.save_state()
        self._logger.debug("Estado de la cola de posiciones pendientes guardado.")

    async def add_position(self, position: PositionTraderTradeData) -> bool:
        try:
            # asyncio.Queue.put_nowait() lanza QueueFull si está llena
            self.pending_queue.put_nowait(position)
            await self._save_pending()
            return True
        except asyncio.QueueFull:
            self._logger.warning(f"Cola de pendientes llena. No se pudo añadir la posición {position.signature[:8]}...")
            return False

    async def get_next_pending(self) -> Optional[PositionTraderTradeData]:
        try:
            # asyncio.Queue.get_nowait() lanza QueueEmpty si está vacía
            pending_position = self.pending_queue.get_nowait()
            self.pending_queue.task_done()
            await self.save_state()
            return pending_position
        except asyncio.QueueEmpty:
            return None

    async def get_next_pending_wait(self, timeout: Optional[float] = None) -> Optional[PositionTraderTradeData]:
        """Obtiene la siguiente posición pendiente esperando si es necesario"""
        try:
            pending_position = await asyncio.wait_for(self.pending_queue.get(), timeout=timeout)
            self.pending_queue.task_done()
            await self.save_state()
            return pending_position
        except asyncio.TimeoutError:
            return None

    async def get_pending_count(self) -> int:
        return self.pending_queue.qsize()

    async def get_pending_positions(self) -> List[PositionTraderTradeData]:
        """Obtiene todas las posiciones pendientes como lista (para compatibilidad)"""
        positions = []
        temp_queue = asyncio.Queue()

        # Transferir elementos a una cola temporal
        while not self.pending_queue.empty():
            try:
                position = self.pending_queue.get_nowait()
                self.pending_queue.task_done()
                positions.append(position)
                temp_queue.put_nowait(position)
            except asyncio.QueueEmpty:
                break

        # Restaurar elementos a la cola original
        while not temp_queue.empty():
            try:
                position = temp_queue.get_nowait()
                temp_queue.task_done()
                self.pending_queue.put_nowait(position)
            except asyncio.QueueEmpty:
                break

        return positions

    async def load_from_disk(self):
        async with self._lock:
            if self.pending_file.exists():
                try:
                    async with aiofiles.open(self.pending_file, 'r') as f:
                        content = await f.read()
                        if content.strip():
                            data: List[Dict[str, Any]] = json.loads(content)

                            # Limpiar la cola actual
                            while not self.pending_queue.empty():
                                try:
                                    self.pending_queue.get_nowait()
                                    self.pending_queue.task_done()
                                except asyncio.QueueEmpty:
                                    break

                            # Cargar posiciones desde disco
                            for position_data in data:
                                position = PositionTraderTradeData.from_dict(position_data)
                                try:
                                    self.pending_queue.put_nowait(position)
                                except asyncio.QueueFull:
                                    self._logger.warning(f"No se pudo cargar posición {position.signature[:8]}... - cola llena")
                                    break

                            self._logger.debug(f"Cargadas {self.pending_queue.qsize()} posiciones pendientes desde disco")
                except (json.JSONDecodeError, Exception) as e:
                    self._logger.warning(f"Error cargando pending_positions.json: {e}")

    async def save_state(self):
        await self._save_pending()

    async def _save_pending(self):
        try:
            # Obtener todas las posiciones para guardar
            positions = await self.get_pending_positions()
            data = [p.to_dict() for p in positions]
            async with aiofiles.open(self.pending_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
        except Exception as e:
            self._logger.error(f"Error guardando estado de posiciones pendientes: {e}")

    def _initialize_file(self):
        if not self.pending_file.exists() or self.pending_file.stat().st_size == 0:
            try:
                with open(self.pending_file, 'w') as f:
                    f.write('[]')
            except Exception as e:
                self._logger.error(f"Error inicializando {self.pending_file.name}: {e}")

    def is_empty(self) -> bool:
        """Verifica si la cola está vacía"""
        return self.pending_queue.empty()

    def is_full(self) -> bool:
        """Verifica si la cola está llena (solo si max_size está definido)"""
        if self.max_size is None:
            return False
        return self.pending_queue.full()

    async def wait_for_completion(self):
        """Espera a que todas las tareas en la cola se completen"""
        await self.pending_queue.join()
