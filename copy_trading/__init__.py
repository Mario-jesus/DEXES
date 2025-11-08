# -*- coding: utf-8 -*-
"""
Módulo Copy Trading - Sistema de copy trading
"""

from .core import CopyTrading
from .config import CopyTradingConfig, TraderInfo, NicknameGenerator, AmountMode, TransactionType, TraderConfig
from .data_management import TokenTraderManager
from .position_management.models import PositionTraderTradeData, Position, OpenPosition, ClosePosition, SubClosePosition
from .position_management.queues import (
    PendingPositionQueue,
    AnalysisPositionQueue,
    OpenPositionQueue,
    PositionNotificationQueue
)
from .position_management.managers import PositionQueueManager
from .callbacks import TradeProcessorCallback, PositionNotificationCallback
from .notifications import NotificationManager, ConsoleStrategy, TelegramStrategy
from .events import (
    PositionEventBus,
    BasePositionEvent,
    PositionCreatedEvent,
    PositionQueuedEvent,
    PositionExecutionStartedEvent,
    PositionExecutedEvent,
    PositionExecutionFailedEvent,
    PositionAnalysisEvent,
    PositionAnalysisFinishedEvent,
    PositionOpenedEvent,
    PositionUpdatedEvent,
    PositionCloseRequestedEvent,
    PositionClosedEvent,
)
from .position_timeout import PositionTimeoutManager

__version__ = "1.0.0"

__all__ = [
    # Clases principales
    "CopyTrading",
    "CopyTradingConfig",
    "TraderInfo",
    "NicknameGenerator",
    "AmountMode",
    "TransactionType",
    "TokenTraderManager",
    "TraderConfig",

    # Modelos de posiciones
    "PositionTraderTradeData",
    "Position", 
    "OpenPosition",
    "ClosePosition",
    "SubClosePosition",

    # Colas
    "PositionQueueManager",
    "PendingPositionQueue",
    "AnalysisPositionQueue",
    "OpenPositionQueue",
    "PositionNotificationQueue",

    # Callbacks
    "TradeProcessorCallback",
    "PositionNotificationCallback",

    # Notificaciones
    "NotificationManager",
    "ConsoleStrategy",
    "TelegramStrategy",

    # Eventos
    "PositionEventBus",
    "BasePositionEvent",
    "PositionCreatedEvent",
    "PositionQueuedEvent",
    "PositionExecutionStartedEvent",
    "PositionExecutedEvent",
    "PositionExecutionFailedEvent",
    "PositionAnalysisEvent",
    "PositionAnalysisFinishedEvent",
    "PositionOpenedEvent",
    "PositionUpdatedEvent",
    "PositionCloseRequestedEvent",
    "PositionClosedEvent",

    # Timeout de posiciones
    "PositionTimeoutManager",
]
