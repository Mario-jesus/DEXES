# -*- coding: utf-8 -*-
"""
Sistema de cola de análisis de posiciones para Copy Trading
"""
import aiofiles
import json
import asyncio
from collections import deque
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal, Tuple, cast, TYPE_CHECKING

from logging_system import AppLogger
from ...data_management.solana_manager import SolanaTxAnalyzer, SolanaWebsocketManager
from ...data_management.models import SignatureNotification, TransactionAnalysis
from ...data_management import TokenTraderManager
from ...balance_management import BalanceManager
from ..models import Position, OpenPosition, ClosePosition, ProcessedAnalysisResult

if TYPE_CHECKING:
    from ..processors import TradeAnalysisProcessor
    from .open_position_queue import OpenPositionQueue
    from .closed_position_queue import ClosedPositionQueue

class AnalysisPositionQueue:
    """Cola FIFO de posiciones para análisis con persistencia y worker"""

    def __init__(self, 
                    solana_analyzer: SolanaTxAnalyzer,
                    solana_websocket: SolanaWebsocketManager,
                    token_trader_manager: TokenTraderManager,
                    balance_manager: BalanceManager,
                    open_position_queue: Optional['OpenPositionQueue'] = None,
                    closed_position_queue: Optional['ClosedPositionQueue'] = None,
                    analysis_processor: Optional['TradeAnalysisProcessor'] = None,
                    data_path: str = "copy_trading/data",
                    max_size: Optional[int] = None):
        self.data_path = Path(data_path)
        self.max_size = max_size
        self._logger = AppLogger(self.__class__.__name__)
        self.solana_analyzer = solana_analyzer
        self.solana_websocket = solana_websocket
        self.token_trader_manager = token_trader_manager
        self.balance_manager = balance_manager
        self.analysis_processor = analysis_processor
        self.open_position_queue = open_position_queue
        self.closed_position_queue = closed_position_queue

        # Cola de Posiciones a analizar
        self._analysis_queue: asyncio.Queue[Position] = asyncio.Queue(maxsize=max_size if max_size else 0)
        self._analysis_task: Optional[asyncio.Task] = None

        # Cola de signatures a analizar
        self._signatures_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_size if max_size else 0)
        self._signatures_task: Optional[asyncio.Task] = None
        self._signatures_interval: int = 10 # Segundos

        # Cola de posiciones pendientes a analizar
        self._pending_analysis_queue: deque[Position] = deque(maxlen=max_size)

        # Tareas en segundo plano
        self.background_tasks: set[asyncio.Task] = set()

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
        """Inicia el analizador de transacciones, carga el estado y arranca el worker."""
        try:
            self._logger.debug("Iniciando analizador de transacciones")
            await self.load_from_disk()
            await self.start_worker()

            self.solana_websocket.set_callbacks(
                on_signature_confirmed=self.on_signature_confirmed,
                on_signature_timeout=self.on_signature_timeout,
                on_connection_error=self.on_connection_error
            )

            self._logger.debug("AnalysisPositionQueue iniciado correctamente")
        except Exception as e:
            self._logger.error(f"Error iniciando AnalysisPositionQueue: {e}")
            raise

    async def stop(self):
        """Detiene el worker de análisis y guarda el estado de la cola."""
        try:
            self._logger.info("Deteniendo AnalysisPositionQueue")
            await self.stop_worker()
            await self.save_state()
            self._logger.debug("AnalysisPositionQueue detenido correctamente")
        except Exception as e:
            self._logger.error(f"Error deteniendo AnalysisPositionQueue: {e}")
            raise

    def set_analysis_processor(self, analysis_processor: 'TradeAnalysisProcessor'):
        self.analysis_processor = analysis_processor

    def set_open_position_queue(self, open_position_queue: 'OpenPositionQueue'):
        self.open_position_queue = open_position_queue

    def set_closed_position_queue(self, closed_position_queue: 'ClosedPositionQueue'):
        self.closed_position_queue = closed_position_queue

    async def on_signature_confirmed(self, signature: str, data: SignatureNotification):
        """
        Maneja la notificación de confirmación de una firma.
        """
        try:
            self._logger.info(f"Firma {signature} confirmada, data: {data}")

            positions_removed = await self.remove_pending_position_by_signature([signature])

            for position in positions_removed:
                if data.is_success or data.error == "unknown": # TODO: Se incluyen a los analisis las posiciones con errores desconosidos momentaneamente para conoces mas detalles sobre ellos
                    await self._add_analysis_queue(position, no_wait=True)
                else:
                    await self._handle_error_position(
                        position=position,
                        error_kind=data.error if data.error else "unknown"
                    )

        except Exception as e:
            self._logger.error(f"Error manejando notificación de firma: {e}")

    async def on_signature_timeout(self, signature: str, timeout: int):
        """
        Maneja el timeout de una firma.
        """
        try:
            self._logger.info(f"Firma {signature} expiró {timeout} segundos, se agrega a cola de análisis")
            await self._add_signature(signature)
        except Exception as e:
            self._logger.error(f"Error manejando timeout de firma: {e}")

    async def on_connection_error(self, error: Exception):
        """
        Maneja el error de conexión.
        """
        try:
            self._logger.error(f"Error de conexión: {error}")
        except Exception as e:
            self._logger.error(f"Error manejando error de conexión: {e}")

    async def _handle_error_position(self,
        position: Position,
        error_kind: Literal["slippage", "insufficient_tokens", "insufficient_lamports", "transaction_not_found", "unknown"],
        error_message: Optional[str] = None
    ) -> None:
        """
        Maneja una posición erronea detectada por el analizador de transacciones.
        """
        try:
            if not position.signature or not isinstance(position.signature, str):
                self._logger.warning(f"Posición {position.id} no tiene signature, no se puede manejar")
                return

            positions_removed = await self.remove_pending_position_by_signature([position.signature])
            for position in positions_removed:
                await self._notify_analysis_finished(position, ProcessedAnalysisResult(
                    success=False,
                    error_kind=error_kind,
                    error_message=error_message
                ))

        except Exception as e:
            self._logger.error(f"Error manejando posición erronea {position.id}: {e}", exc_info=True)

    async def _notify_analysis_finished(self, position: Position, details: ProcessedAnalysisResult) -> None:
        """
        Notifica el resultado del análisis de una posición.
        """
        try:
            if isinstance(position, OpenPosition) and self.open_position_queue:
                await self.open_position_queue.on_analysis_finished(position, details)
            elif isinstance(position, ClosePosition) and self.closed_position_queue:
                await self.closed_position_queue.on_analysis_finished(position, details)
            else:
                self._logger.warning(f"Posición {position.id} no es OpenPosition ni ClosePosition, no se puede manejar")

            if self.balance_manager and position.token_address:
                await self.balance_manager.on_analysis_finished(position.token_address)
        except Exception as e:
            self._logger.error(f"Error notificando resultado del análisis de posición {position.id}: {e}", exc_info=True)

    async def add_position(self, position: Position) -> bool:
        """
        Agrega una posición a la cola de análisis.
        """
        try:
            if not position.signature:
                self._logger.warning(f"Posición {position.id} no tiene signature, no se puede agregar a cola de análisis")
                return False

            was_subscribed = await self.solana_websocket.subscribe_signature(signature=position.signature)
            if not was_subscribed:
                self._logger.warning(f"Posición {position.id} no se pudo suscribir, no se puede agregar a cola de análisis")
                return False

            added_to_pending = await self._add_pending_position(position)

            if added_to_pending and self.balance_manager and position.token_address:
                try:
                    await self.balance_manager.on_analysis_enqueued(position.token_address)
                except Exception as e:
                    self._logger.error(f"Error al avisar al BalanceManager que se agregó una posición a cola de pendientes de análisis: {e}")

            return added_to_pending
        except Exception as e:
            self._logger.error(f"Error agregando posición {position.id} a cola de análisis por suscripción: {e}", exc_info=True)
            return False

    async def get_position_by_id(self, position_id: str) -> Optional[Position]:
        try:
            # Crear una cola temporal para buscar la posición
            temp_queue: asyncio.Queue[Position] = asyncio.Queue()
            found_position = None

            # Transferir elementos de la cola original a la temporal
            while not self._analysis_queue.empty():
                try:
                    position = self._analysis_queue.get_nowait()
                    if position.id == position_id:
                        found_position = position
                    else:
                        temp_queue.put_nowait(position)
                except asyncio.QueueEmpty:
                    break

            # Transferir elementos de vuelta a la cola original
            while not temp_queue.empty():
                try:
                    position = temp_queue.get_nowait()
                    self._analysis_queue.put_nowait(position)
                except asyncio.QueueEmpty:
                    break

            return found_position
        except Exception as e:
            self._logger.error(f"Error buscando posición {position_id} en cola de análisis: {e}")
            return None

    async def get_analysis_positions(self) -> List[Position]:
        """Obtiene todas las posiciones en análisis"""
        try:
            # Crear una cola temporal para obtener todas las posiciones
            temp_queue: asyncio.Queue[Position] = asyncio.Queue()
            positions: List[Position] = []

            # Transferir elementos de la cola original a la temporal
            while not self._analysis_queue.empty():
                try:
                    position = self._analysis_queue.get_nowait()
                    positions.append(position)
                    temp_queue.put_nowait(position)
                except asyncio.QueueEmpty:
                    break

            # Transferir elementos de vuelta a la cola original
            while not temp_queue.empty():
                try:
                    position = temp_queue.get_nowait()
                    self._analysis_queue.put_nowait(position)
                except asyncio.QueueEmpty:
                    break

            self._logger.debug(f"Obtenidas {len(positions)} posiciones de análisis")
            return positions
        except Exception as e:
            self._logger.error(f"Error obteniendo posiciones de análisis: {e}")
            return []

    async def remove_position_by_id(self, position_id: str) -> Optional[Position]:
        try:
            # Crear una cola temporal para buscar y remover la posición
            temp_queue: asyncio.Queue[Position] = asyncio.Queue()
            removed_position = None

            # Transferir elementos de la cola original a la temporal
            while not self._analysis_queue.empty():
                try:
                    position = self._analysis_queue.get_nowait()
                    if position.id == position_id:
                        removed_position = position
                        # No lo agregamos de vuelta a la cola temporal
                    else:
                        temp_queue.put_nowait(position)
                except asyncio.QueueEmpty:
                    break

            # Transferir elementos de vuelta a la cola original
            while not temp_queue.empty():
                try:
                    position = temp_queue.get_nowait()
                    self._analysis_queue.put_nowait(position)
                except asyncio.QueueEmpty:
                    break

            if removed_position:
                await self._save_analysis_queue()
                self._logger.info(f"Posición {position_id} removida de cola de análisis")
            else:
                self._logger.warning(f"Posición {position_id} no encontrada en cola de análisis")

            return removed_position
        except Exception as e:
            self._logger.error(f"Error removiendo posición {position_id} de cola de análisis: {e}")
            return None

    async def _add_analysis_queue(self, position: Position, no_wait=False) -> bool:
        try:
            if self._analysis_queue.full():
                self._logger.warning(f"Cola de análisis llena, no se puede agregar posición {position.id}")
                return False

            if no_wait:
                try:
                    self._analysis_queue.put_nowait(position)
                except asyncio.QueueFull:
                    self._logger.warning(f"Cola de análisis llena, no se puede agregar posición {position.id}")
                    return False
            else:
                await self._analysis_queue.put(position)

            return True
        except Exception as e:
            self._logger.error(f"Error agregando posiciones a cola de análisis: {e}")
            return False

    async def _add_signature(self, signature: str) -> bool:
        """
        Agrega una signature a la cola de análisis.
        """
        try:
            self._logger.debug(f"Agregando signature {signature} a cola de análisis")

            # Verificar si la cola está llena
            if self._signatures_queue.full():
                self._logger.warning(f"Cola de signatures llena, no se puede agregar signature {signature}")
                return False

            # Usar put_nowait para evitar bloqueo
            try:
                self._signatures_queue.put_nowait(signature)
            except asyncio.QueueFull:
                self._logger.warning(f"Cola de signatures llena, no se puede agregar signature {signature}")
                return False

            self._logger.debug(f"Signature {signature} agregada a cola de análisis (tamaño: {self._signatures_queue.qsize()})")

            return True
        except Exception as e:
            self._logger.error(f"Error agregando signature {signature} a cola de análisis: {e}")
            return False

    async def remove_signatures(self) -> List[str]:
        """Remueve todas las signatures en análisis"""
        try:
            signatures: List[str] = []

            while not self._signatures_queue.empty():
                try:
                    signature = self._signatures_queue.get_nowait()
                    signatures.append(signature)
                except asyncio.QueueEmpty:
                    break

            self._logger.debug(f"Removidas {len(signatures)} signatures de análisis (tamaño: {self._signatures_queue.qsize()})")
            return signatures
        except Exception as e:
            self._logger.error(f"Error removiendo signatures de análisis: {e}")
            return []

    async def _add_pending_position(self, position: Position) -> bool:
        """
        Agrega una posición a la cola de pendientes de análisis.
        """
        try:
            if self.max_size is not None and len(self._pending_analysis_queue) >= self.max_size:
                self._logger.warning(f"Cola de pendientes llena. No se pudo añadir la posición {position.id}")
                return False

            async with self._lock:
                self._pending_analysis_queue.append(position)
                return True

        except Exception as e:
            self._logger.error(f"Error agregando posición a cola de pendientes de análisis: {e}")
            return False

    async def remove_pending_position_by_signature(self, signatures: List[str]) -> List[Position]:
        """
        Remueve una posición de la cola de pendientes de análisis por signature.
        """
        try:
            positions_removed: List[Position] = []
            async with self._lock:
                # Crear una lista de posiciones a remover para evitar modificar durante la iteración
                positions_to_remove = []
                for position in self._pending_analysis_queue:
                    if position.signature in signatures:
                        positions_to_remove.append(position)
                        positions_removed.append(position)

                # Remover las posiciones después de la iteración
                for position in positions_to_remove:
                    try:
                        self._pending_analysis_queue.remove(position)
                    except ValueError:
                        # La posición ya fue removida por otro proceso
                        pass

            return positions_removed
        except Exception as e:
            self._logger.error(f"Error removiendo posición de cola de pendientes de análisis: {e}")
            return []

    async def start_worker(self) -> None:
        try:
            if self._analysis_task and not self._analysis_task.done():
                self._logger.debug("Worker de análisis ya está ejecutándose")
                return

            if self._signatures_task and not self._signatures_task.done():
                self._logger.debug("Worker de signatures ya está ejecutándose")
                return

            self._analysis_task = asyncio.create_task(self._analysis_worker())
            self._logger.debug("Worker de análisis iniciado")

            self._signatures_task = asyncio.create_task(self._signatures_worker())
            self._logger.debug("Worker de signatures iniciado")
        except Exception as e:
            self._logger.error(f"Error iniciando worker de análisis: {e}")

    async def stop_worker(self) -> None:
        """Detiene los workers de análisis de trades y signatures."""
        try:
            # Detener worker de análisis
            if self._analysis_task and not self._analysis_task.done():
                self._logger.debug("Deteniendo worker de análisis")
                self._analysis_task.cancel()
                try:
                    await self._analysis_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self._logger.error(f"Error cancelando worker de análisis: {e}")
                finally:
                    self._analysis_task = None
                    self._logger.debug("Worker de análisis detenido")
            else:
                self._logger.debug("Worker de análisis no estaba ejecutándose")

            # Detener worker de signatures
            if self._signatures_task and not self._signatures_task.done():
                self._logger.debug("Deteniendo worker de signatures")
                self._signatures_task.cancel()
                try:
                    await self._signatures_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self._logger.error(f"Error cancelando worker de signatures: {e}")
                finally:
                    self._signatures_task = None
                    self._logger.debug("Worker de signatures detenido")
            else:
                self._logger.debug("Worker de signatures no estaba ejecutándose")

        except Exception as e:
            self._logger.error(f"Error deteniendo workers: {e}")

    async def _analysis_worker(self) -> None:
        self._logger.debug("Worker de análisis iniciado")
        while True:
            try:
                await self._process_analysis_queue()
                # Procesar continuamente sin intervalos
            except asyncio.CancelledError:
                self._logger.debug("Worker de análisis cancelado")
                break
            except Exception as e:
                self._logger.error(f"Error en worker de análisis: {e}")
                # Pequeña pausa solo en caso de error para evitar bucle infinito
                await asyncio.sleep(1)

    async def _signatures_worker(self) -> None:
        self._logger.debug("Worker de signatures iniciado")
        while True:
            try:
                await self._process_signatures_queue()
                # Procesar en intervalos
                await asyncio.sleep(self._signatures_interval)
            except asyncio.CancelledError:
                self._logger.debug("Worker de signatures cancelado")
                break
            except Exception as e:
                self._logger.error(f"Error en worker de signatures: {e}")
                # Pequeña pausa solo en caso de error para evitar bucle infinito
                await asyncio.sleep(1)

    async def _process_analysis_queue(self) -> None:
        try:
            self._logger.debug(f"Procesando cola de análisis - Tamaño: {self._analysis_queue.qsize()}")

            # Procesar una posición a la vez desde la cabeza de la cola
            # get() se quedará esperando indefinidamente hasta que llegue una posición
            position = await self._analysis_queue.get()

            # Implementar backoff exponencial con 3 reintentos
            max_retries = 3
            base_delay = 1.0  # 1 segundo base

            for attempt in range(max_retries):
                try:
                    self._logger.debug(f"Analizando posición {position.id} - Intento {attempt + 1}/{max_retries}")
                    success, transaction_analysis = await self._analyze_position(position)

                    if success and transaction_analysis and transaction_analysis.success:
                        self._logger.debug(f"Posición {position.id} analizada exitosamente en intento {attempt + 1}")
                        await self.remove_position_by_id(position.id)
                        await self._notify_analysis_finished(position, ProcessedAnalysisResult(
                            success=True,
                            error_kind=None,
                            error_message=None
                        ))
                        return

                    # Si no fue exitoso, verificar si es un error que no debe reintentarse
                    if transaction_analysis and transaction_analysis.error_kind in ["slippage", "insufficient_tokens", "insufficient_lamports", "transaction_not_found"]:
                        self._logger.debug(f"Posición {position.id} con error no reintentable: {transaction_analysis.error_kind}")
                        await self.remove_position_by_id(position.id)
                        await self._handle_error_position(
                            position=position,
                            error_kind=cast(
                                Literal["slippage", "insufficient_tokens", "insufficient_lamports", "transaction_not_found", "unknown"],
                                transaction_analysis.error_kind
                            ),
                            error_message=transaction_analysis.error_message
                        )
                        return

                    # Si es el último intento, manejar como error
                    if attempt == max_retries - 1:
                        self._logger.warning(f"Posición {position.id} falló después de {max_retries} intentos")
                        await self.remove_position_by_id(position.id)
                        error_kind = transaction_analysis.error_kind if transaction_analysis else "unknown"
                        message = transaction_analysis.error_message if transaction_analysis else "Error después de múltiples reintentos"

                        if error_kind not in ["slippage", "insufficient_tokens", "insufficient_lamports", "transaction_not_found"]:
                            error_kind = "unknown"

                        await self._handle_error_position(
                            position=position,
                            error_kind=cast(
                                Literal["slippage", "insufficient_tokens", "insufficient_lamports", "transaction_not_found", "unknown"],
                                error_kind
                            ),
                            error_message=message
                        )
                        return

                    # Calcular delay exponencial para el siguiente intento
                    delay = base_delay * (2 ** attempt)
                    self._logger.debug(f"Reintentando posición {position.id} en {delay} segundos")
                    await asyncio.sleep(delay)

                except Exception as e:
                    self._logger.error(f"Error en intento {attempt + 1} para posición {position.id}: {e}")

                    # Si es el último intento, manejar como error
                    if attempt == max_retries - 1:
                        self._logger.error(f"Posición {position.id} falló definitivamente después de {max_retries} intentos")
                        await self.remove_position_by_id(position.id)
                        await self._handle_error_position(
                            position=position,
                            error_kind="unknown",
                            error_message=f"Error después de {max_retries} reintentos: {str(e)}"
                        )
                        return

                    # Calcular delay exponencial para el siguiente intento
                    delay = base_delay * (2 ** attempt)
                    self._logger.debug(f"Reintentando posición {position.id} en {delay} segundos después de excepción")
                    await asyncio.sleep(delay)

        except Exception as e:
            self._logger.error(f"Error procesando cola de análisis: {e}")

    async def _process_signatures_queue(self) -> None:
        try:
            if self._signatures_queue.empty():
                return

            signatures = await self.remove_signatures()
            if not signatures:
                return

            signatures_with_statuses = await self.solana_analyzer.get_signatures_with_statuses(
                signatures=signatures
            )

            positions_removed = await self.remove_pending_position_by_signature(signatures)

            for position in positions_removed:
                if not position.signature:
                    continue

                position_analysis_status = signatures_with_statuses.data.get(position.signature)
                if position_analysis_status and (position_analysis_status.success or position_analysis_status.type_error == "unknown"): # TODO: Se incluyen a los analisis las posiciones con errores desconosidos momentaneamente para conoces mas detalles sobre ellos
                    await self._add_analysis_queue(position, no_wait=True)
                else:
                    type_error = position_analysis_status.type_error if position_analysis_status else "transaction_not_found"
                    await self._handle_error_position(
                        position=position,
                        error_kind=type_error or "unknown"
                    )

            self._logger.debug(f"Cola de signatures procesada con {len(positions_removed)} posiciones")
            self._logger.debug(f"Todos fueron exitosos: {signatures_with_statuses.all_success}")
            self._logger.debug(f"Todos existen: {signatures_with_statuses.all_exists}")

        except Exception as e:
            self._logger.error(f"Error procesando cola de signatures: {e}")

    async def _analyze_position(self, position: Position) -> Tuple[bool, Optional[TransactionAnalysis]]:
        """
        Analiza posiciones usando el procesador de análisis.
        """
        try:
            self._logger.debug(f"Iniciando análisis de posición {position.id}")
            if self.analysis_processor is None:
                self._logger.error("El procesador de analisis no esta inicializado")
                raise ValueError("El procesador de analisis no esta inicializado")

            success, transaction_analysis = await self.analysis_processor.analyze_position(position)
            if not success:
                self._logger.warning(f"Error en el análisis de posición {position.id}")
                return False, transaction_analysis

            self._logger.debug(f"Análisis de posición {position.id} completado exitosamente")
            return True, transaction_analysis
        except Exception as e:
            self._logger.error(f"Error analizando posición {position.id}: {e}")
            return False, None

    async def load_from_disk(self):
        try:
            if self.analysis_file.exists():
                self._logger.debug(f"Cargando cola de análisis desde {self.analysis_file}")
                async with aiofiles.open(self.analysis_file, 'r') as f:
                    content = await f.read()
                    if content.strip():
                        data: List[Dict[str, Any]] = json.loads(content)
                        # Limpiar la cola actual
                        while not self._analysis_queue.empty():
                            try:
                                self._analysis_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break

                        # Cargar posiciones desde disco
                        for position_data in data:
                            position = Position.from_dict(position_data)
                            try:
                                self._analysis_queue.put_nowait(position)
                            except asyncio.QueueFull:
                                self._logger.warning(f"No se pudo cargar posición {position.id} - cola llena")
                                break

                        self._logger.debug(f"Cargadas {self._analysis_queue.qsize()} posiciones de análisis desde disco")
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
            # Obtener todas las posiciones para guardar
            self._logger.debug("Guardando cola de análisis")
            positions = await self.get_analysis_positions()
            data = [p.to_dict() for p in positions]

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
                'analysis_queue_size': self._analysis_queue.qsize(),
                'analysis_max_size': self.max_size,
                'analysis_is_full': self._analysis_queue.full(),
                'analysis_is_empty': self._analysis_queue.empty(),
                'signatures_queue_size': self._signatures_queue.qsize(),
                'signatures_max_size': self.max_size,
                'signatures_is_full': self._signatures_queue.full(),
                'signatures_is_empty': self._signatures_queue.empty(),
                'signatures_interval': self._signatures_interval,
                'pending_analysis_queue_size': len(self._pending_analysis_queue),
                'pending_analysis_max_size': self.max_size,
                'pending_analysis_is_full': len(self._pending_analysis_queue) >= self.max_size if self.max_size else False,
                'pending_analysis_is_empty': len(self._pending_analysis_queue) == 0
            }
            self._logger.debug(f"Estadísticas de análisis: {stats}")
            return stats
        except Exception as e:
            self._logger.error(f"Error obteniendo estadísticas de análisis: {e}")
            return {}

    async def has_pending_open_analysis_for_token(self, token_address: str) -> bool:
        """
        Indica si existen posiciones ABIERTAS del token con análisis pendiente.
        """
        try:
            # Obtener todas las posiciones para verificar
            positions = await self.get_analysis_positions()
            for pos in positions:
                if isinstance(pos, OpenPosition) and pos.token_address == token_address and not pos.is_analyzed:
                    return True
            return False
        except Exception as e:
            self._logger.error(f"Error verificando análisis pendientes para token {token_address}: {e}")
            return True
