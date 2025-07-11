# -*- coding: utf-8 -*-
"""
Estrategia de notificaciones para Telegram usando python-telegram-bot
Basada en el ejemplo proporcionado por el usuario
"""
import asyncio
import threading
import queue
import time
from telegram import Bot
from telegram.error import TelegramError, RetryAfter
from .base_strategy import BaseNotificationStrategy


class TelegramStrategy(BaseNotificationStrategy):
    """
    Estrategia de notificaciones para Telegram usando python-telegram-bot
    """

    def __init__(self, config: dict, logger=None):
        """
        Inicializa la estrategia de Telegram
        
        Args:
            config: Diccionario con configuración que debe contener:
                - token: Token del bot de Telegram
                - chat_id: ID del chat donde enviar mensajes
                - messages_per_minute: Límite de mensajes por minuto (opcional, default: 30)
            logger: Logger opcional para registrar eventos
        """
        super().__init__(config)
    
        # Guardar logger
        self.logger = logger

        # Configuración básica
        self.token = config.get('token')
        self.chat_id = config.get('chat_id')
        self.messages_per_minute = config.get('messages_per_minute', 30)

        if not self.token or not self.chat_id:
            raise ValueError("Token y chat_id son requeridos para TelegramStrategy")

        # Inicializar bot
        self.bot = Bot(token=self.token)

        # Sistema de cola para mensajes
        self.message_queue = queue.Queue()
        self.message_timestamps = []

        # Sistema de threading para manejo asíncrono
        self.loop = None
        self.telegram_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.telegram_thread.start()

        if self.logger:
            self.logger.info(f"✅ TelegramStrategy inicializada con chat_id: {self.chat_id}")
        else:
            print(f"✅ TelegramStrategy inicializada con chat_id: {self.chat_id}")

    def _log(self, message: str, level: str = "info"):
        """Helper para logging uniforme"""
        if self.logger:
            if level == "error":
                self.logger.error(message)
            elif level == "warning":
                self.logger.warning(message)
            else:
                self.logger.info(message)
        else:
            print(message)

    def _run_event_loop(self):
        """Ejecuta el loop de eventos en un hilo separado"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._telegram_worker())

    async def _telegram_worker(self):
        """Worker que procesa la cola de mensajes"""
        while True:
            try:
                message = self.message_queue.get_nowait()
                if message is None:  # Señal de shutdown
                    break
                await self._send_message(message)
                self.message_queue.task_done()
            except queue.Empty:
                await asyncio.sleep(0.1)

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
                    await asyncio.sleep(sleep_time)

            # Enviar mensaje
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text=message,
                parse_mode='HTML'
            )

            self.message_timestamps.append(time.time())
            self._log(f"✅ Mensaje enviado a Telegram: {message[:50]}...", "info")

        except RetryAfter as e:
            self._log(f"⏳ Límite de velocidad excedido. Esperando {e.retry_after} segundos.", "warning")
            await asyncio.sleep(e.retry_after)
            await self._send_message(message)  # Reintentar

        except TelegramError as e:
            self._log(f"❌ Error al enviar mensaje a Telegram: {e}", "error")
            raise
        except Exception as e:
            self._log(f"❌ Error inesperado al enviar mensaje: {e}", "error")
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

            # Agregar a la cola
            self.message_queue.put(formatted_message)

        except Exception as e:
            self._log(f"❌ Error al enviar notificación: {e}", "error")
            raise

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
            # Enviar señal de shutdown
            self.message_queue.put(None)

            # Esperar a que termine el hilo
            if self.telegram_thread.is_alive():
                self.telegram_thread.join(timeout=5)

            # Cerrar el loop
            if self.loop and not self.loop.is_closed():
                self.loop.close()

            self._log("✅ TelegramStrategy cerrada correctamente", "info")

        except Exception as e:
            self._log(f"❌ Error al cerrar TelegramStrategy: {e}", "error")


class TelegramPrintBot:
    """
    Clase compatible con el ejemplo del usuario
    Wrapper para mantener compatibilidad con código existente
    """

    def __init__(self, token, chat_id, messages_per_minute=30, use_telegram=False):
        self.token = token
        self.chat_id = chat_id
        self.bot = Bot(token)
        self.use_telegram = use_telegram
        self.message_queue = queue.Queue()
        self.messages_per_minute = messages_per_minute
        self.message_timestamps = []
        self.loop = None
        self.telegram_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.telegram_thread.start()

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._telegram_worker())

    async def _telegram_worker(self):
        while True:
            try:
                message = self.message_queue.get_nowait()
                if message is None:
                    break
                await self._send_message(message)
                self.message_queue.task_done()
            except queue.Empty:
                await asyncio.sleep(0.1)

    async def _send_message(self, message):
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
            print(f"Límite de velocidad excedido. Esperando {e.retry_after} segundos.")
            await asyncio.sleep(e.retry_after)
            await self._send_message(message) 
        except TelegramError as e:
            print(f"Error al enviar mensaje a Telegram: {e}")

    def flexible_print(self, *args, **kwargs):
        message = ' '.join(map(str, args))
        if self.use_telegram:
            self.message_queue.put(message)

    def set_use_telegram(self, use_telegram):
        self.use_telegram = use_telegram

    def shutdown(self):
        self.message_queue.put(None)
        self.telegram_thread.join()
        if self.loop:
            self.loop.close()
