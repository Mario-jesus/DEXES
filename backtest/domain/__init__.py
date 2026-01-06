# -*- coding: utf-8 -*-
"""
Capa de Dominio - Entidades, Puertos, Servicios y Validaciones

Esta capa contiene:
- Entidades de dominio puras (sin dependencias externas)
- Puertos (interfaces) que definen las operaciones necesarias del dominio
- Servicios de dominio (lógica de negocio que no pertenece a una entidad)
- Validaciones (reglas de negocio para validar transacciones)
"""

from .entities import (
    SwapTransaction,
    Position,
    ClosedTrade,
    PoolStats,
    BacktestStats,
    ValidationMetrics
)

__all__ = [
    'SwapTransaction',
    'Position',
    'ClosedTrade',
    'PoolStats',
    'BacktestStats',
    'ValidationMetrics',
]
