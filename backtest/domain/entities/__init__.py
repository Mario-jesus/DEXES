# -*- coding: utf-8 -*-
"""
Entidades de dominio del módulo backtest.

Exporta todas las entidades organizadas por categoría:
- Transacciones: SwapTransaction
- Posiciones: Position, ClosedTrade
- Estadísticas: PoolStats, ValidationMetrics, BacktestStats
"""

from .transactions import SwapTransaction
from .positions import Position, ClosedTrade
from .backtest_statistics import PoolStats, ValidationMetrics, BacktestStats

__all__ = [
    # Entidades de transacciones
    'SwapTransaction',
    # Entidades de posiciones
    'Position',
    'ClosedTrade',
    # Entidades de estadísticas
    'PoolStats',
    'ValidationMetrics',
    'BacktestStats',
]
