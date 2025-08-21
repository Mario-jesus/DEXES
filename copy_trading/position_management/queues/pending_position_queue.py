# -*- coding: utf-8 -*-
"""
Sistema de cola de posiciones pendientes para Copy Trading
"""
import aiofiles
import json
import asyncio
from collections import deque
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

        self.pending_queue: deque[PositionTraderTradeData] = deque(maxlen=max_size)

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
        async with self._lock:
            # Verificar límite de tamaño solo si max_size no es None
            if self.max_size is not None and len(self.pending_queue) >= self.max_size:
                self._logger.warning(f"Cola de pendientes llena. No se pudo añadir la posición {position.signature[:8]}...")
                return False

            self.pending_queue.append(position)
            await self._save_pending()
            return True

    async def get_next_pending(self) -> Optional[PositionTraderTradeData]:
        pending_position = None
        async with self._lock:
            if self.pending_queue:
                pending_position = self.pending_queue.popleft()

        if pending_position:
            await self.save_state()

        return pending_position

    async def get_pending_count(self) -> int:
        async with self._lock:
            return len(self.pending_queue)

    async def get_pending_positions(self) -> deque[PositionTraderTradeData]:
        async with self._lock:
            return self.pending_queue

    async def load_from_disk(self):
        async with self._lock:
            if self.pending_file.exists():
                try:
                    async with aiofiles.open(self.pending_file, 'r') as f:
                        content = await f.read()
                        if content.strip():
                            data: List[Dict[str, Any]] = json.loads(content)
                            self.pending_queue = deque(
                                [PositionTraderTradeData.from_dict(p) for p in data],
                                maxlen=self.max_size
                            )
                            self._logger.debug(f"Cargadas {len(self.pending_queue)} posiciones pendientes desde disco")
                except (json.JSONDecodeError, Exception) as e:
                    self._logger.warning(f"Error cargando pending_positions.json: {e}")

    async def save_state(self):
        await self._save_pending()

    async def _save_pending(self):
        try:
            data = [p.to_dict() for p in self.pending_queue]
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
