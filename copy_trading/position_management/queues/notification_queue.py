# -*- coding: utf-8 -*-
"""
Cola de notificaciones de posiciones asíncrona para el sistema de Copy Trading.
Procesa notificaciones sin bloquear el flujo principal.
"""
import asyncio
from typing import Optional, Callable, Union
from datetime import datetime
from collections import deque

from logging_system import AppLogger
from ..models import OpenPosition, ClosePosition, SubClosePosition


class PositionNotificationQueue:
    """
    Cola FIFO asíncrona para procesar notificaciones de posiciones.
    Evalúa is_analyzed y procesa notificaciones sin bloquear el flujo principal.
    """

    def __init__(self, 
                    notification_callback: Optional[Callable] = None,
                    max_size: Optional[int] = None,
                    process_interval: float = 1.0):
        """
        Inicializa la cola de notificaciones.
        
        Args:
            notification_callback: Callback para procesar notificaciones
            max_size: Tamaño máximo de la cola (None = ilimitado)
            process_interval: Intervalo en segundos para procesar la cola
        """
        self.notification_callback = notification_callback
        self.max_size = max_size
        self._logger = AppLogger(self.__class__.__name__)
        self.process_interval = process_interval

        # Cola FIFO para posiciones pendientes de notificación
        self._queue: deque = deque()

        # Control del loop de procesamiento
        self._running = False
        self._process_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Set para rastrear tareas asíncronas creadas
        self._background_tasks: set[asyncio.Task] = set()

        # Métricas
        self.stats = {
            'total_received': 0,
            'total_processed': 0,
            'total_failed': 0,
            'current_queue_size': 0,
            'last_processed_time': None
        }

        self._logger.debug("PositionNotificationQueue inicializada")

    async def __aenter__(self):
        """Inicia el worker de procesamiento de notificaciones."""
        self._logger.debug("Entrando en context manager de PositionNotificationQueue")
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self._logger.debug("Saliendo del context manager de PositionNotificationQueue")
        await self.stop()

    async def start(self) -> None:
        """Inicia el loop de procesamiento de la cola"""
        if self._running:
            self._logger.warning("PositionNotificationQueue ya está ejecutándose")
            return

        self._logger.debug("Iniciando PositionNotificationQueue")
        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        self._logger.debug("Tarea de procesamiento de notificaciones creada")

    async def stop(self) -> None:
        """Detiene el worker de procesamiento de notificaciones."""
        if not self._running:
            self._logger.debug("PositionNotificationQueue ya está detenida")
            return

        self._logger.info("Deteniendo PositionNotificationQueue")
        self._running = False

        if self._process_task and not self._process_task.done():
            self._logger.debug("Cancelando tarea de procesamiento de notificaciones")
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                self._logger.debug("Tarea de procesamiento cancelada exitosamente")
            except Exception as e:
                self._logger.error(f"Error cancelando tarea de notificaciones: {e}")
            finally:
                self._process_task = None

        # Procesar elementos restantes
        await self._process_remaining_items()
        self._logger.debug("PositionNotificationQueue detenida correctamente")

    async def add_position(self, position: Union[OpenPosition, ClosePosition, SubClosePosition]) -> bool:
        """
        Añade una posición a la cola para notificación.
        
        Args:
            position: Posición a notificar
            
        Returns:
            bool: True si se añadió exitosamente
        """
        async with self._lock:
            # Verificar límite de tamaño si está configurado
            if self.max_size and len(self._queue) >= self.max_size:
                position_id = getattr(position, 'id', 'unknown')
                self._logger.warning(
                    f"Cola de notificaciones llena (max_size={self.max_size}), "
                    f"descartando posición {position_id}"
                )
                return False

            # Añadir a la cola con timestamp
            notification_item = {
                'position': position,
                'added_at': datetime.now(),
                'attempts': 0
            }

            self._queue.append(notification_item)
            self.stats['total_received'] += 1
            self.stats['current_queue_size'] = len(self._queue)

            position_id = getattr(position, 'id', 'unknown')
            self._logger.debug(f"Posición {position_id} añadida a cola de notificaciones (tamaño actual: {len(self._queue)})")

            return True

    async def _process_loop(self) -> None:
        """Loop principal de procesamiento asíncrono"""
        self._logger.debug("Iniciando loop de procesamiento de notificaciones")

        while self._running:
            try:
                await self._process_queue()
                await asyncio.sleep(self.process_interval)
            except Exception as e:
                self._logger.error(f"Error en loop de procesamiento de notificaciones: {e}", exc_info=True)
                await asyncio.sleep(self.process_interval * 2)  # Esperar más tiempo en caso de error

        self._logger.debug("Loop de procesamiento de notificaciones terminado")

    async def _process_queue(self) -> None:
        """Procesa elementos de la cola que estén analizados"""
        if not self._queue:
            return

        async with self._lock:
            # Procesar elementos de la cola
            items_to_remove = []
            processed_count = 0
            skipped_count = 0

            for i, item in enumerate(self._queue):
                position = item['position']

                # Verificar si la posición está analizada
                if not self._is_position_analyzed(position):
                    skipped_count += 1
                    continue  # Saltear si no está analizada

                # Procesar notificación
                success = await self._process_notification_item(item)

                if success:
                    items_to_remove.append(i)
                    self.stats['total_processed'] += 1
                    self.stats['last_processed_time'] = datetime.now()
                    processed_count += 1
                else:
                    # Incrementar intentos fallidos
                    item['attempts'] += 1
                    if item['attempts'] >= 3:  # Máximo 3 intentos
                        items_to_remove.append(i)
                        self.stats['total_failed'] += 1
                        position_id = getattr(position, 'id', 'unknown')
                        self._logger.error(f"Descartando notificación para posición {position_id} después de 3 intentos fallidos")

            # Remover elementos procesados (en orden reverso para no afectar índices)
            for i in reversed(items_to_remove):
                self._queue.popleft() if i == 0 else self._queue.remove(list(self._queue)[i])

            self.stats['current_queue_size'] = len(self._queue)

    def _is_position_analyzed(self, position: Union[OpenPosition, ClosePosition, SubClosePosition]) -> bool:
        """
        Verifica si una posición está analizada y lista para notificación.
        
        Args:
            position: Posición a verificar
            
        Returns:
            bool: True si está analizada
        """
        if isinstance(position, SubClosePosition):
            # Para cierres parciales, verificar la posición de cierre referenciada
            return position.close_position.get_is_analyzed()
        else:
            # Para posiciones normales, verificar directamente
            return position.get_is_analyzed()

    async def _process_notification_item(self, item: dict) -> bool:
        """
        Procesa un elemento de notificación.
        
        Args:
            item: Item de la cola con posición y metadata
            
        Returns:
            bool: True si se procesó exitosamente
        """
        try:
            if not self.notification_callback:
                self._logger.warning("No hay callback de notificación configurado")
                return True  # Considerar como exitoso para remover de la cola

            position = item['position']
            position_id = getattr(position, 'id', 'unknown')

            self._logger.debug(f"Procesando notificación para posición {position_id} (intento {item['attempts'] + 1})")

            # Llamar al callback de notificación
            await self.notification_callback(position)

            self._logger.debug(f"Notificación procesada exitosamente para posición {position_id}")
            return True

        except Exception as e:
            position_id = getattr(item['position'], 'id', 'unknown')
            self._logger.error(f"Error procesando notificación para posición {position_id}: {e}", exc_info=True)
            return False

    async def _process_remaining_items(self) -> None:
        """Procesa elementos restantes al detener la cola"""
        if not self._queue:
            self._logger.debug("No hay elementos restantes para procesar")
            return

        remaining_count = len(self._queue)
        self._logger.info(f"Procesando {remaining_count} elementos restantes en cola de notificaciones")

        # Procesar todos los elementos restantes sin verificar is_analyzed
        remaining_items = list(self._queue)
        self._queue.clear()

        processed_count = 0
        failed_count = 0

        for item in remaining_items:
            try:
                await self._process_notification_item(item)
                self.stats['total_processed'] += 1
                processed_count += 1
            except Exception as e:
                self.stats['total_failed'] += 1
                failed_count += 1
                position_id = getattr(item['position'], 'id', 'unknown')
                self._logger.error(f"Error procesando elemento restante {position_id}: {e}")

        self._logger.info(f"Procesamiento de elementos restantes completado: {processed_count} exitosos, {failed_count} fallidos")

    async def get_stats(self) -> dict:
        """Obtiene estadísticas de la cola"""
        async with self._lock:
            stats = {
                **self.stats,
                'is_running': self._running,
                'current_queue_size': len(self._queue)
            }
            self._logger.debug(f"Estadísticas obtenidas: {stats['total_processed']} procesadas, {stats['total_failed']} fallidas, {len(self._queue)} en cola")
            return stats

    async def get_queue_size(self) -> int:
        """Obtiene el tamaño actual de la cola"""
        size = len(self._queue)
        self._logger.debug(f"Tamaño actual de la cola: {size}")
        return size

    async def clear_queue(self) -> int:
        """
        Limpia la cola y retorna el número de elementos removidos.
        
        Returns:
            int: Número de elementos removidos
        """
        async with self._lock:
            count = len(self._queue)
            self._queue.clear()
            self.stats['current_queue_size'] = 0

            if count > 0:
                self._logger.debug(f"Cola de notificaciones limpiada: {count} elementos removidos")
            else:
                self._logger.debug("Cola de notificaciones ya estaba vacía")

            return count
