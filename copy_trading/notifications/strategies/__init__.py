# -*- coding: utf-8 -*-
"""
Módulo de estrategias de notificaciones para copy_trading
"""
from .console_strategy import ConsoleStrategy
from .telegram_strategy import TelegramStrategy
from .base_strategy import BaseNotificationStrategy

__all__ = [
    "BaseNotificationStrategy",
    "ConsoleStrategy",
    "TelegramStrategy"
]
