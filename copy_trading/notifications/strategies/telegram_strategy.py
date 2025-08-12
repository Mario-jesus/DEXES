# -*- coding: utf-8 -*-
"""
Estrategia de notificaciones para Telegram usando python-telegram-bot
Basada en el ejemplo proporcionado por el usuario
"""
import asyncio
import threading
import queue
import time
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError, RetryAfter

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

        if not token or not chat_id:
            raise ValueError("Token y chat_id son requeridos para TelegramStrategy")

        self.token: str = token
        self.chat_id: str = chat_id

        # Inicializar bot
        self.bot = Bot(token=self.token)

        # Sistema de cola para mensajes
        self.message_queue = queue.Queue()
        self.message_timestamps = []

        # Sistema de threading para manejo asíncrono
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.telegram_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.telegram_thread.start()

        self._logger.debug(f"TelegramStrategy inicializada con chat_id: {self.chat_id}")

    def _log(self, message: str, level: str = "info"):
        """Helper para logging uniforme"""
        if level == "error":
            self._logger.error(message)
        elif level == "warning":
            self._logger.warning(message)
        else:
            self._logger.info(message)

    def _run_event_loop(self):
        """Ejecuta el loop de eventos en un hilo separado"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._telegram_worker())
        except Exception as e:
            self._logger.error(f"Error en el loop de eventos de Telegram: {e}")

    async def _telegram_worker(self):
        """Worker que procesa la cola de mensajes"""
        try:
            self._logger.debug("Worker de Telegram iniciado")
            while True:
                try:
                    message = self.message_queue.get_nowait()
                    if message is None:  # Señal de shutdown
                        self._logger.debug("Señal de shutdown recibida en worker de Telegram")
                        break
                    await self._send_message(message)
                    self.message_queue.task_done()
                except queue.Empty:
                    await asyncio.sleep(0.1)
        except Exception as e:
            self._logger.error(f"Error en worker de Telegram: {e}")

    async def _send_message(self, message: str):
        """
        Envía un mensaje a Telegram con rate limiting
        
        Args:
            message: Mensaje a enviar
        """
        try:
            # Rate limiting
            current_time = time.time()
            self.message_timestamps = [
                t for t in self.message_timestamps 
                if current_time - t < 60
            ]

            if len(self.message_timestamps) >= self.messages_per_minute:
                sleep_time = 60 - (current_time - self.message_timestamps[0])
                if sleep_time > 0:
                    self._logger.debug(f"Rate limit alcanzado, esperando {sleep_time:.1f} segundos")
                    await asyncio.sleep(sleep_time)

            # Enviar mensaje
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text=message,
                parse_mode='HTML'
            )

            self.message_timestamps.append(time.time())
            self._logger.debug(f"Mensaje enviado a Telegram: {message[:50]}...")

        except RetryAfter as e:
            retry_seconds = float(e.retry_after) if isinstance(e.retry_after, (int, float)) else e.retry_after.total_seconds()
            self._logger.warning(f"Límite de velocidad excedido. Esperando {retry_seconds} segundos")
            await asyncio.sleep(retry_seconds)
            await self._send_message(message)  # Reintentar

        except TelegramError as e:
            self._logger.error(f"Error al enviar mensaje a Telegram: {e}")
            raise
        except Exception as e:
            self._logger.error(f"Error inesperado al enviar mensaje: {e}")
            raise

    async def send_notification(self, message: str, notification_type: str = "info"):
        """
        Envía una notificación
        
        Args:
            message: Mensaje a enviar
            notification_type: Tipo de notificación (info, success, warning, error)
        """
        try:
            # Formatear mensaje según el tipo
            formatted_message = self._format_message(message, notification_type)

            # Agregar a la cola con timeout
            try:
                # Usar put_nowait para evitar bloqueos
                self.message_queue.put_nowait(formatted_message)
                self._logger.debug(f"Notificación agregada a cola: {notification_type}")
            except queue.Full:
                self._logger.warning("Cola de mensajes llena, descartando notificación")
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
        # Emojis según el tipo de notificación
        emoji_map = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
            "trade": "💰",
            "system": "🔧"
        }

        emoji = emoji_map.get(notification_type, "📢")

        # Formatear con HTML básico
        formatted = f"{emoji} <b>{notification_type.upper()}</b>\n\n{message}"

        return formatted

    def shutdown(self):
        """Cierra la estrategia de Telegram"""
        try:
            self._logger.info("Cerrando TelegramStrategy")

            # Enviar señal de shutdown
            self.message_queue.put(None)

            # Esperar a que termine el hilo
            if self.telegram_thread.is_alive():
                self.telegram_thread.join(timeout=5)

            # Cerrar el loop
            if self.loop and not self.loop.is_closed():
                self.loop.close()

            self._logger.debug("TelegramStrategy cerrada correctamente")

        except Exception as e:
            self._logger.error(f"Error al cerrar TelegramStrategy: {e}")


class TelegramPrintBot:
    """
    Clase compatible con el ejemplo del usuario
    Wrapper para mantener compatibilidad con código existente
    """

    def __init__(self, token: str, chat_id: str, messages_per_minute: int = 30, use_telegram: bool = False):
        self.token = token
        self.chat_id = chat_id
        self.bot = Bot(token)
        self.use_telegram = use_telegram
        self.message_queue = queue.Queue()
        self.messages_per_minute = messages_per_minute
        self.message_timestamps = []
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.telegram_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.telegram_thread.start()

    def _run_event_loop(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._telegram_worker())
        except Exception as e:
            print(f"Error en el loop de eventos de TelegramPrintBot: {e}")

    async def _telegram_worker(self):
        try:
            while True:
                try:
                    message = self.message_queue.get_nowait()
                    if message is None:
                        break
                    await self._send_message(message)
                    self.message_queue.task_done()
                except queue.Empty:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Error en worker de TelegramPrintBot: {e}")

    async def _send_message(self, message: str):
        try:
            current_time = time.time()
            self.message_timestamps = [t for t in self.message_timestamps if current_time - t < 60]
            if len(self.message_timestamps) >= self.messages_per_minute:
                sleep_time = 60 - (current_time - self.message_timestamps[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
            await self.bot.send_message(chat_id=self.chat_id, text=message)
            self.message_timestamps.append(time.time())
        except RetryAfter as e:
            retry_seconds = float(e.retry_after) if isinstance(e.retry_after, (int, float)) else e.retry_after.total_seconds()
            print(f"Límite de velocidad excedido. Esperando {retry_seconds} segundos.")
            await asyncio.sleep(retry_seconds)
            await self._send_message(message) 
        except TelegramError as e:
            print(f"Error al enviar mensaje a Telegram: {e}")

    def flexible_print(self, *args, **kwargs):
        message = ' '.join(map(str, args))
        if self.use_telegram:
            self.message_queue.put(message)

    def set_use_telegram(self, use_telegram: bool):
        self.use_telegram = use_telegram

    def shutdown(self):
        try:
            self.message_queue.put(None)
            self.telegram_thread.join()
            if self.loop:
                self.loop.close()
        except Exception as e:
            print(f"Error al cerrar TelegramPrintBot: {e}")
