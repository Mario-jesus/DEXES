# -*- coding: utf-8 -*-
"""
Servicios de dominio.

Contiene servicios que encapsulan lógica de negocio que no pertenece
naturalmente a una entidad específica.
"""

from .exchange_registry import (
    get_internal_name_by_address,
    get_address_by_internal_name,
    get_internal_name_by_source_name,
    normalize_exchange,
    get_display_name
)
from .backtest_validator import BacktestValidator
from .fifo_matcher import FIFOMatcher
from .metrics_calculator import MetricsCalculator

__all__ = [
    'get_internal_name_by_address',
    'get_address_by_internal_name',
    'get_internal_name_by_source_name',
    'normalize_exchange',
    'get_display_name',
    'BacktestValidator',
    'FIFOMatcher',
    'MetricsCalculator',
]
