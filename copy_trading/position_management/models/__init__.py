# -*- coding: utf-8 -*-
"""
Modelos de posiciones de trading refactorizados.
"""

from .enums import PositionStatus, ClosePositionStatus
from .base_models import Position, TraderTradeData, PositionTraderTradeData
from .position_models import OpenPosition, ClosePosition, SubClosePosition
from .serialization import serialize_for_json

__all__ = [
    # Enums
    'PositionStatus',
    'ClosePositionStatus',
    
    # Modelos base
    'Position',
    'TraderTradeData',
    'PositionTraderTradeData',
    
    # Modelos de posición
    'OpenPosition',
    'ClosePosition',
    'SubClosePosition',
    
    # Utilidades de serialización
    'serialize_for_json',
]
