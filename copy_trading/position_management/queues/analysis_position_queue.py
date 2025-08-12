# -*- coding: utf-8 -*-
"""
Sistema de cola de análisis de posiciones para Copy Trading
"""
import aiofiles
import json
import asyncio
from collections import deque
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from pumpfun import PumpFunTradeAnalyzer
from logging_system import AppLogger
from ...data_management import TokenTraderManager
from ..models import Position
from ..processors import TradeAnalysisProcessor


class AnalysisPositionQueue:
    """Cola FIFO de posiciones para análisis con persistencia y worker"""

    def __init__(self, trader_analyzer: PumpFunTradeAnalyzer, token_trader_manager: TokenTraderManager,
                    data_path: str = "copy_trading/data", max_size: Optional[int] = None):
        self.data_path = Path(data_path)
        self.max_size = max_size
        self._logger = AppLogger(self.__class__.__name__)
        self.trade_analyzer = trader_analyzer
        self.token_trader_manager = token_trader_manager

        self.analysis_queue: deque[Position] = deque(maxlen=max_size)
        self.analysis_task: Optional[asyncio.Task] = None
        self.analysis_interval: int = 15  # segundos

        self.analysis_processor = TradeAnalysisProcessor(
            trader_analyzer=trader_analyzer,
            token_trader_manager=token_trader_manager
        )

        self._lock = asyncio.Lock()

        self.data_path.mkdir(parents=True, exist_ok=True)

        self.analysis_file = self.data_path / "analysis_queue.json"

        self._initialize_file()

        self._logger.debug(f"AnalysisPositionQueue inicializado - Data path: {self.data_path}, Max size: {self.max_size}")

    async def __aenter__(self):
        """Inicia el worker al entrar en el contexto."""
        self._logger.debug("Iniciando AnalysisPositionQueue con async context manager")
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Detiene el worker y guarda el estado al salir del contexto."""
        try:
            await self.stop()
            self._logger.debug("AnalysisPositionQueue cerrado con async context manager")
        except Exception as e:
            self._logger.error(f"Error cerrando AnalysisPositionQueue: {e}", exc_info=True)

    async def start(self):
        """Inicia el analizador de trades, carga el estado y arranca el worker."""
        try:
            self._logger.debug("Iniciando trade analyzer")
            await self.trade_analyzer.__aenter__()
            await self.load_from_disk()
            await self.start_worker()
            self._logger.debug("AnalysisPositionQueue iniciado correctamente")
        except Exception as e:
            self._logger.error(f"Error iniciando AnalysisPositionQueue: {e}")
            raise

    async def stop(self):
        """Detiene el worker de análisis y guarda el estado de la cola."""
        try:
            self._logger.info("Deteniendo AnalysisPositionQueue")
            await self.stop_worker()
            await self.trade_analyzer.__aexit__(None, None, None)
            await self.save_state()
            self._logger.debug("AnalysisPositionQueue detenido correctamente")
        except Exception as e:
            self._logger.error(f"Error deteniendo AnalysisPositionQueue: {e}")
            raise

    async def add_position(self, position: Position) -> bool:
        """
        Agrega una posición a la cola de análisis.
        """
        try:
            async with self._lock:
                self._logger.info(f"Agregando posición {position.id} a cola de análisis")

                # Verificar límite de tamaño solo si max_size no es None
                if self.max_size is not None and len(self.analysis_queue) >= self.max_size:
                    self._logger.warning(f"Cola de análisis llena, no se puede agregar posición {position.id}")
                    return False

                self.analysis_queue.append(position)
                await self._save_analysis_queue()

                self._logger.info(f"Posición {position.id} agregada a cola de análisis (tamaño: {len(self.analysis_queue)})")

                return True
        except Exception as e:
            self._logger.error(f"Error agregando posición {position.id} a cola de análisis: {e}")
            return False

    async def get_position_by_id(self, position_id: str) -> Optional[Position]:
        try:
            async with self._lock:
                for pos in self.analysis_queue:
                    if pos.id == position_id:
                        return pos
                return None
        except Exception as e:
            self._logger.error(f"Error buscando posición {position_id} en cola de análisis: {e}")
            return None

    async def get_analysis_positions(self) -> List[Position]:
        """Obtiene todas las posiciones en análisis"""
        try:
            async with self._lock:
                positions = list(self.analysis_queue)
                self._logger.debug(f"Obtenidas {len(positions)} posiciones de análisis")
                return positions
        except Exception as e:
            self._logger.error(f"Error obteniendo posiciones de análisis: {e}")
            return []

    async def remove_position_by_id(self, position_id: str) -> Optional[Position]:
        try:
            async with self._lock:
                for i, pos in enumerate(self.analysis_queue):
                    if pos.id == position_id:
                        removed_position = self.analysis_queue.popleft() if i == 0 else self.analysis_queue.remove(pos)
                        await self._save_analysis_queue()
                        self._logger.info(f"Posición {position_id} removida de cola de análisis")
                        return removed_position
                self._logger.warning(f"Posición {position_id} no encontrada en cola de análisis")
                return None
        except Exception as e:
            self._logger.error(f"Error removiendo posición {position_id} de cola de análisis: {e}")
            return None

    async def start_worker(self) -> None:
        try:
            if self.analysis_task and not self.analysis_task.done():
                self._logger.debug("Worker de análisis ya está ejecutándose")
                return

            self.analysis_task = asyncio.create_task(self._analysis_worker())
            self._logger.debug("Worker de análisis iniciado")
        except Exception as e:
            self._logger.error(f"Error iniciando worker de análisis: {e}")

    async def stop_worker(self) -> None:
        """Detiene el worker de análisis de trades."""
        try:
            if self.analysis_task and not self.analysis_task.done():
                self._logger.debug("Deteniendo worker de análisis")
                self.analysis_task.cancel()
                try:
                    await self.analysis_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self._logger.error(f"Error cancelando worker de análisis: {e}")
                finally:
                    self.analysis_task = None
                    self._logger.debug("Worker de análisis detenido")
            else:
                self._logger.debug("Worker de análisis no estaba ejecutándose")
        except Exception as e:
            self._logger.error(f"Error deteniendo worker de análisis: {e}")

    async def _analysis_worker(self) -> None:
        self._logger.debug("Worker de análisis iniciado")
        while True:
            try:
                await self._process_analysis_queue()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                self._logger.debug("Worker de análisis cancelado")
                break
            except Exception as e:
                self._logger.error(f"Error en worker de análisis: {e}")
                await asyncio.sleep(5)

    async def _process_analysis_queue(self) -> None:
        try:
            if not self.analysis_queue:
                return

            self._logger.debug(f"Procesando cola de análisis - Tamaño: {len(self.analysis_queue)}")

            positions_to_analyze: List[Position] = []

            for position in self.analysis_queue:
                if position.created_at < (datetime.now() - timedelta(seconds=self.analysis_interval)):
                    positions_to_analyze.append(position)

            if positions_to_analyze:
                self._logger.info(f"Analizando {len(positions_to_analyze)} posiciones")
                await self._analyze_positions(positions_to_analyze)

            for position in positions_to_analyze:
                if position.is_analyzed and position in self.analysis_queue:
                    async with self._lock:
                        self.analysis_queue.remove(position)
                        self._logger.info(f"Posición {position.id} analizada y removida de la cola")

            await self._save_analysis_queue()
        except Exception as e:
            self._logger.error(f"Error procesando cola de análisis: {e}")

    async def _analyze_positions(self, positions: List[Position]) -> None:
        """
        Analiza posiciones usando el procesador de análisis.
        """
        try:
            self._logger.info(f"Iniciando análisis de {len(positions)} posiciones")
            success = await self.analysis_processor.analyze_positions(positions)
            if not success:
                self._logger.warning("Error en el análisis de posiciones")
            else:
                self._logger.info("Análisis de posiciones completado exitosamente")
        except Exception as e:
            self._logger.error(f"Error analizando posiciones: {e}")

    async def load_from_disk(self):
        try:
            async with self._lock:
                if self.analysis_file.exists():
                    self._logger.debug(f"Cargando cola de análisis desde {self.analysis_file}")
                    async with aiofiles.open(self.analysis_file, 'r') as f:
                        content = await f.read()
                        if content.strip():
                            data: List[Dict[str, Any]] = json.loads(content)
                            self.analysis_queue = deque(
                                [Position.from_dict(p) for p in data],
                                maxlen=self.max_size
                            )
                            self._logger.debug(f"Cargadas {len(self.analysis_queue)} posiciones de análisis desde disco")
                        else:
                            self._logger.debug("Archivo de análisis está vacío")
                else:
                    self._logger.debug("Archivo de análisis no existe, iniciando con cola vacía")
        except (json.JSONDecodeError, Exception) as e:
            self._logger.warning(f"Error cargando analysis_queue.json: {e}")

    async def save_state(self):
        try:
            self._logger.debug("Guardando estado de cola de análisis")
            await self._save_analysis_queue()
        except Exception as e:
            self._logger.error(f"Error guardando estado de cola de análisis: {e}")

    async def _save_analysis_queue(self):
        try:
            data = [p.to_dict() for p in self.analysis_queue]
            async with aiofiles.open(self.analysis_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
            self._logger.debug(f"Cola de análisis guardada con {len(data)} posiciones")
        except Exception as e:
            self._logger.error(f"Error guardando cola de análisis: {e}")
            raise

    def _initialize_file(self):
        try:
            if not self.analysis_file.exists() or self.analysis_file.stat().st_size == 0:
                with open(self.analysis_file, 'w') as f:
                    f.write('[]')
                self._logger.debug(f"Archivo {self.analysis_file.name} inicializado")
        except Exception as e:
            self._logger.error(f"Error inicializando {self.analysis_file.name}: {e}")

    async def get_analysis_statistics(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas del procesador de análisis.
        """
        try:
            stats = {
                'queue_size': len(self.analysis_queue),
                'max_size': self.max_size
            }
            self._logger.debug(f"Estadísticas de análisis: {stats}")
            return stats
        except Exception as e:
            self._logger.error(f"Error obteniendo estadísticas de análisis: {e}")
            return {}
