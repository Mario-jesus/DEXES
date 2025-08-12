# -*- coding: utf-8 -*-
"""
Módulo de callbacks para Copy Trading
"""
from .trade_processor_callback import TradeProcessorCallback
from .notification_callback import PositionNotificationCallback

__all__ = [
    'TradeProcessorCallback',
    'PositionNotificationCallback'
]
