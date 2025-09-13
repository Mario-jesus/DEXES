# -*- coding: utf-8 -*-
"""
Estrategia de notificaciones para Telegram usando python-telegram-bot
Basada en el ejemplo proporcionado por el usuario
"""
import asyncio
import time
from typing import Optional
from telegram import Bot
from telegram.error import (
    TelegramError,
    RetryAfter,
    TimedOut,
    NetworkError,
    BadRequest,
    Forbidden,
)
from telegram.request import HTTPXRequest

from logging_system import AppLogger
from .base_strategy import BaseNotificationStrategy


class TelegramStrategy(BaseNotificationStrategy):
    """
    Estrategia de notificaciones para Telegram usando python-telegram-bot
    """

    def __init__(self, config: dict):
        """
        Inicializa la estrategia de Telegram
        
        Args:
            config: Diccionario con configuración que debe contener:
                - token: Token del bot de Telegram
                - chat_id: ID del chat donde enviar mensajes
                - messages_per_minute: Límite de mensajes por minuto (opcional, default: 30)
        """
        super().__init__(config)

        self._logger = AppLogger(self.__class__.__name__)

        # Configuración básica
        token = config.get('token')
        chat_id = config.get('chat_id')
        self.messages_per_minute = config.get('messages_per_minute', 30)
        self.max_retries = config.get('max_retries', 5)
        self.backoff_base_seconds = config.get('backoff_base_seconds', 1.0)
        self.connect_timeout = config.get('connect_timeout', 10.0)
        self.read_timeout = config.get('read_timeout', 20.0)
        self.write_timeout = config.get('write_timeout', 20.0)
        self.pool_timeout = config.get('pool_timeout', 10.0)

        if not token or not chat_id:
            raise ValueError("Token y chat_id son requeridos para TelegramStrategy")

        self.token: str = token
        self.chat_id: str = chat_id

        # Inicialización diferida - se hará en initialize()
        self.bot: Optional[Bot] = None
        self.message_queue: Optional[asyncio.Queue[Optional[str]]] = None
        self.message_timestamps: list = []
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._closing: bool = False
        self.shutdown_grace_seconds = float(config.get('shutdown_grace_seconds', 2.0))
        self._is_running = False

        # Reconexión basada en tasa de errores
        self.error_reconnect_threshold: int = int(config.get('error_reconnect_threshold', 3))
        self.error_reconnect_window_seconds: float = float(config.get('error_reconnect_window_seconds', 60.0))
        self.error_reconnect_cooldown_seconds: float = float(config.get('error_reconnect_cooldown_seconds', 120.0))
        self._error_timestamps: list[float] = []
        self._last_reconnect_time: float = 0.0

        self._logger.debug(f"TelegramStrategy configurada con chat_id: {self.chat_id}")

    @property
    def is_running(self) -> bool:
        """Indica si la estrategia está corriendo"""
        return self._is_running

    async def initialize(self) -> None:
        """
        Inicializa los componentes asíncronos de la estrategia de Telegram
        """
        try:
            if self._is_running:
                self._logger.warning("TelegramStrategy ya está corriendo, no se puede inicializar nuevamente")
                return

            # Inicializar bot con HTTPXRequest para controlar timeouts
            try:
                request = HTTPXRequest(
                    connect_timeout=self.connect_timeout,
                    read_timeout=self.read_timeout,
                    write_timeout=self.write_timeout,
                    pool_timeout=self.pool_timeout
                )
                self.bot = Bot(token=self.token, request=request)
            except Exception as e:
                # Fallback a inicialización simple si falla el request personalizado
                self._logger.warning(f"No se pudo inicializar HTTPXRequest personalizado: {e}. Usando configuración por defecto")
                self.bot = Bot(token=self.token)

            # Inicializar cola de mensajes
            self.message_queue = asyncio.Queue()
            self.message_timestamps = []

            # Inicializar worker
            self._worker_task = asyncio.create_task(self._telegram_worker())
            self._logger.debug("Worker de Telegram inicializado")

            self._is_running = True
            self._logger.debug(f"TelegramStrategy inicializada correctamente con chat_id: {self.chat_id}")
        except Exception as e:
            self._logger.error(f"Error al inicializar TelegramStrategy: {e}")
            raise

    async def shutdown(self) -> None:
        """Cierra la estrategia de Telegram (async) usando shutdown() y luego join()."""
        try:
            if not self._is_running:
                self._logger.warning("TelegramStrategy no está corriendo, no se puede cerrar")
                return

            # Marcar cierre para limitar reintentos pero permitir drenar cola
            self._closing = True
            self._logger.debug("Cerrando TelegramStrategy")

            # Cerrar la cola para que el worker reciba QueueShutDown
            if self._worker_task is not None and self.message_queue is not None:
                # Bloquear productores y cerrar la cola
                self.message_queue.shutdown()
                # Esperar a que se procese todo lo ya encolado
                await self.message_queue.join()
                # Esperar cierre limpio del worker
                try:
                    await self._worker_task
                finally:
                    self._worker_task = None

            self._is_running = False
            self._closing = False
            self._logger.debug("TelegramStrategy cerrada correctamente")
        except Exception as e:
            self._logger.error(f"Error al cerrar TelegramStrategy: {e}")

    async def _ensure_worker(self) -> None:
        """Asegura que el worker esté corriendo como tarea asyncio."""
        if not self._is_running:
            self._logger.warning("TelegramStrategy no está corriendo, no se puede asegurar worker")
            return

        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._telegram_worker())
            self._logger.debug("Worker de Telegram reinicializado (asyncio)")

    async def _telegram_worker(self):
        """Worker que procesa la cola de mensajes"""
        if self.message_queue is None:
            self._logger.error("Message queue no inicializada en worker")
            return

        self._logger.debug("Worker de Telegram iniciado")
        # Mantener el worker activo hasta que la cola emita QueueShutDown
        # para garantizar que todos los mensajes encolados se procesen.
        while True:
            try:
                # Espera bloqueante asíncrona hasta un mensaje
                message = await self.message_queue.get()
            except asyncio.QueueShutDown:
                self._logger.debug("Queue de Telegram cerrada; terminando worker")
                break
            except asyncio.CancelledError:
                self._logger.debug("Worker de Telegram cancelado")
                raise
            except Exception as e:
                self._logger.error(f"Error en worker de Telegram: {type(e).__name__}: {e}", exc_info=True)
                continue

            try:
                if message is not None:
                    await self._send_message(message)
            finally:
                if self.message_queue is not None:
                    self.message_queue.task_done()

        self._logger.info("Worker de Telegram terminado")

    async def _send_message(self, message: str):
        """
        Envía un mensaje a Telegram con rate limiting y reintentos con backoff exponencial.
        
        Args:
            message: Mensaje a enviar
        """
        if self.bot is None:
            self._logger.error("Bot de Telegram no inicializado")
            return

        try:
            # Si estamos en proceso de cierre y aún no hemos marcado stop del worker,
            # reducimos reintentos pero permitimos un intento de envío
            if not self._is_running and not self._closing:
                self._logger.debug("Envío a Telegram cancelado: estrategia detenida")
                return

            # Rate limiting
            current_time = time.time()
            self.message_timestamps = [
                t for t in self.message_timestamps 
                if current_time - t < 60
            ]

            if len(self.message_timestamps) >= self.messages_per_minute:
                sleep_time = 60 - (current_time - self.message_timestamps[0])
                if sleep_time > 0:
                    self._logger.warning(f"Rate limit alcanzado, esperando {sleep_time:.1f} segundos")
                    await asyncio.sleep(sleep_time)

            attempt_number = 1
            max_attempts = 1 if self._closing else self.max_retries
            while attempt_number <= max_attempts:
                try:
                    await self.bot.send_message(
                        chat_id=self.chat_id, 
                        text=message,
                        parse_mode='HTML'
                    )

                    self.message_timestamps.append(time.time())
                    self._logger.debug(f"Mensaje enviado a Telegram: {message[:50]}...")
                    # Éxito: limpiar ventana de errores reciente
                    self._error_timestamps.clear()
                    return

                except RetryAfter as e:
                    retry_seconds = float(e.retry_after) if isinstance(e.retry_after, (int, float)) else e.retry_after.total_seconds()
                    self._logger.warning(f"Límite de velocidad excedido. Esperando {retry_seconds} segundos")
                    await asyncio.sleep(retry_seconds)
                    # No incrementar intento en RetryAfter; el siguiente intento debería funcionar

                except (NetworkError, TimedOut) as e:
                    if self._closing:
                        self._logger.warning(f"Conexión a Telegram falló durante cierre ({type(e).__name__}: {e}). No se reintenta")
                        return
                    backoff_seconds = min(60.0, self.backoff_base_seconds * (2 ** (attempt_number - 1)))
                    self._logger.warning(
                        f"Conexión a Telegram falló ({type(e).__name__}: {e}). Reintentando en {backoff_seconds:.1f}s (intento {attempt_number}/{self.max_retries})"
                    )
                    await self._register_error_and_maybe_reconnect(e)
                    await asyncio.sleep(backoff_seconds)
                    attempt_number += 1

                except (BadRequest, Forbidden) as e:
                    # Errores fatales (token inválido, chat_id inválido, permisos)
                    self._logger.error(f"Error fatal de Telegram ({type(e).__name__}): {e}")
                    return

                except TelegramError as e:
                    # Manejar explícitamente Unauthorized si la clase existe en runtime
                    error_name = type(e).__name__
                    if error_name == 'Unauthorized' or 'unauthorized' in str(e).lower():
                        self._logger.error(f"Error fatal de Telegram (Unauthorized): {e}")
                        return
                    # Otros errores de Telegram: tratar como transitorios con reintento limitado
                    if self._closing:
                        self._logger.warning(f"TelegramError durante cierre: {e}. No se reintenta")
                        return
                    backoff_seconds = min(60.0, self.backoff_base_seconds * (2 ** (attempt_number - 1)))
                    self._logger.warning(
                        f"TelegramError: {e}. Reintentando en {backoff_seconds:.1f}s (intento {attempt_number}/{self.max_retries})"
                    )
                    await self._register_error_and_maybe_reconnect(e)
                    await asyncio.sleep(backoff_seconds)
                    attempt_number += 1

                except Exception as e:
                    # Fallback para errores no clasificados (p.ej., httpx.ConnectError)
                    if self._closing:
                        self._logger.warning(f"Error no clasificado durante cierre ({type(e).__name__}: {e}). No se reintenta")
                        return
                    backoff_seconds = min(60.0, self.backoff_base_seconds * (2 ** (attempt_number - 1)))
                    self._logger.warning(
                        f"Error no clasificado al enviar a Telegram ({type(e).__name__}: {e}). Reintentando en {backoff_seconds:.1f}s (intento {attempt_number}/{self.max_retries})",
                        exc_info=True
                    )
                    await self._register_error_and_maybe_reconnect(e)
                    await asyncio.sleep(backoff_seconds)
                    attempt_number += 1

            self._logger.error("Se alcanzó el máximo de reintentos al enviar mensaje a Telegram. Descartando mensaje.")

        except asyncio.CancelledError:
            self._logger.debug("Envío de mensaje a Telegram cancelado")
            raise
        except Exception as e:
            self._logger.error(f"Error inesperado al enviar mensaje: {type(e).__name__}: {e}", exc_info=True)

    async def _register_error_and_maybe_reconnect(self, err: Exception) -> None:
        """Registra un error en ventana móvil y fuerza reconexión del bot si se supera el umbral."""
        try:
            if self._closing or not self._is_running:
                return

            now = time.time()
            # Depurar ventana
            self._error_timestamps = [t for t in self._error_timestamps if now - t < self.error_reconnect_window_seconds]
            self._error_timestamps.append(now)

            count = len(self._error_timestamps)
            if count >= self.error_reconnect_threshold:
                if (now - self._last_reconnect_time) < self.error_reconnect_cooldown_seconds:
                    return
                self._logger.warning(
                    f"Demasiados errores de Telegram ({count}/{self.error_reconnect_threshold}) en {self.error_reconnect_window_seconds:.0f}s. Forzando reconexión del cliente..."
                )
                await self._force_reconnect_bot()
                self._last_reconnect_time = time.time()
                self._error_timestamps.clear()
        except Exception as e:
            self._logger.error(f"Error registrando ventana de errores/ciclo de reconexión: {e}")

    async def _force_reconnect_bot(self) -> None:
        """Recrea la instancia del Bot y su HTTPXRequest para limpiar el pool de conexiones."""
        try:
            # Recrear request y bot; no detenemos el worker ni la cola
            try:
                request = HTTPXRequest(
                    connect_timeout=self.connect_timeout,
                    read_timeout=self.read_timeout,
                    write_timeout=self.write_timeout,
                    pool_timeout=self.pool_timeout
                )
                self.bot = Bot(token=self.token, request=request)
            except Exception as e:
                self._logger.warning(f"Fallo recreando HTTPXRequest personalizado: {e}. Usando configuración por defecto")
                self.bot = Bot(token=self.token)

            # Ping ligero para confirmar
            try:
                await self.bot.get_me()
                self._logger.info("Reconexión de Telegram completada exitosamente")
            except Exception as e:
                self._logger.warning(f"getMe después de reconexión falló: {e}")
        except Exception as e:
            self._logger.error(f"Error forzando reconexión del Bot de Telegram: {e}")

    async def send_notification(self, message: str, notification_type: str = "info"):
        """
        Envía una notificación
        
        Args:
            message: Mensaje a enviar
            notification_type: Tipo de notificación (info, success, warning, error)
        """
        if not self._is_running:
            self._logger.warning("TelegramStrategy no está corriendo, no se puede enviar notificación")
            return

        if self.message_queue is None:
            self._logger.error("Message queue no inicializada, no se puede enviar notificación")
            return

        try:
            # Formatear mensaje según el tipo
            formatted_message = self._format_message(message, notification_type)

            # Asegurar worker y encolar de forma no bloqueante
            await self._ensure_worker()
            try:
                self.message_queue.put_nowait(formatted_message)
                self._logger.debug(f"Notificación agregada a cola: {notification_type}")
            except asyncio.QueueFull:
                self._logger.warning("Cola de mensajes llena, descartando notificación")
            except asyncio.QueueShutDown:
                self._logger.warning("Cola de mensajes cerrada; descartando notificación")
                return

        except asyncio.CancelledError:
            self._logger.debug("Notificación de Telegram cancelada")
            raise  # Re-lanzar para que el sistema maneje la cancelación
        except Exception as e:
            self._logger.error(f"Error al enviar notificación: {e}")
            # No re-lanzar la excepción para evitar que bloquee el sistema

    def _format_message(self, message: str, notification_type: str) -> str:
        """
        Formatea el mensaje según el tipo de notificación
        
        Args:
            message: Mensaje original
            notification_type: Tipo de notificación
            
        Returns:
            Mensaje formateado
        """
        # Si el mensaje ya trae formato HTML (encabezados en <b>, secciones, etc.),
        # no anteponer nada para evitar duplicar emojis/cabeceras.
        if "<b>" in message or "</b>" in message:
            return message

        # Para mensajes simples, anteponer emoji + tipo en negritas y un salto de línea
        emoji_map = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
            "trade": "💰",
            "system": "🔧"
        }
        label_map = {
            "info": "INFO",
            "success": "SUCCESS",
            "warning": "WARNING",
            "error": "ERROR",
            "trade": "TRADE",
            "system": "SYSTEM"
        }

        emoji = emoji_map.get(notification_type, "📢")
        label = label_map.get(notification_type, notification_type.upper())

        return f"{emoji} <b>{label}</b>\n{message}"
