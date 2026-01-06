# -*- coding: utf-8 -*-
"""
Capa de Aplicación - Casos de Uso

Esta capa contiene los casos de uso que orquestan los servicios para ejecutar
operaciones de negocio complejas.
"""

from .use_cases import BacktestRunner, BacktestOptimizer, BacktestComparator
from .helpers import (
    build_min_sol_amount_validator,
    build_in_range_sol_amount_validator,
    build_outside_range_sol_amount_validator,
    build_trade_activity_validator,
    generate_min_sol_amount_params,
    generate_range_sol_amount_params,
    generate_trade_activity_params,
    generate_monthly_date_ranges
)
from .types import BacktestDataEntry, PoolData, ParameterSearchConfig

__all__ = [
    'BacktestRunner',
    'BacktestOptimizer',
    'BacktestComparator',
    'build_min_sol_amount_validator',
    'build_in_range_sol_amount_validator',
    'build_outside_range_sol_amount_validator',
    'build_trade_activity_validator',
    'generate_min_sol_amount_params',
    'generate_range_sol_amount_params',
    'generate_trade_activity_params',
    'generate_monthly_date_ranges',
    'BacktestDataEntry',
    'PoolData',
    'ParameterSearchConfig',
]
