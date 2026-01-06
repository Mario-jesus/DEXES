# -*- coding: utf-8 -*-
"""
Helpers y builders para casos de uso de backtest.

Contiene funciones auxiliares que facilitan la construcción de validadores
y generación de parámetros para optimización de backtests.
"""

from .validator_builders import (
    build_min_sol_amount_validator,
    build_in_range_sol_amount_validator,
    build_outside_range_sol_amount_validator,
    build_trade_activity_validator
)
from .param_generators import (
    generate_min_sol_amount_params,
    generate_range_sol_amount_params,
    generate_trade_activity_params,
    generate_monthly_date_ranges
)

__all__ = [
    'build_min_sol_amount_validator',
    'build_in_range_sol_amount_validator',
    'build_outside_range_sol_amount_validator',
    'build_trade_activity_validator',
    'generate_min_sol_amount_params',
    'generate_range_sol_amount_params',
    'generate_trade_activity_params',
    'generate_monthly_date_ranges',
]
