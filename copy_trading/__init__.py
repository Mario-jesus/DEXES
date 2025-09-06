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
]

# Mensaje de bienvenida
print("🎯 Módulo Copy Trading cargado")
print("   ✅ Integración directa con PumpFun")
print("   ✅ Replicación automática de trades")
print("   ✅ Gestión de posiciones FIFO")
print("   ✅ Validaciones configurables")
print("   ✅ Logging estructurado")
print("   ✅ Soporte Lightning y Local Trade")
print("   ✅ Sistema de notificaciones mejorado")
print("   ✅ Herramientas de diagnóstico")
print("   ✅ Diagnóstico de I/O de archivos")
print("   ✅ TokenTraderManager optimizado")
print("   ✅ Sistema de eventos desacoplado para posiciones")
