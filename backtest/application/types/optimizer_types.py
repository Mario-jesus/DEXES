# -*- coding: utf-8 -*-
"""
Tipos de datos comunes para optimización de backtest.
"""
from typing import Dict, Any, Optional, TypedDict, NotRequired, List, Callable, TYPE_CHECKING
from decimal import Decimal

if TYPE_CHECKING:
    from ...domain.services.backtest_validator import BacktestValidator


class BacktestDataEntry(TypedDict):
    """
    Tipo para representar un registro de datos de backtest.
    """
    filter_type: str
    filter_params: Dict[str, Any]
    has_available_data: bool
    date_start: Optional[str]
    date_end: Optional[str]
    total_trades: NotRequired[int]
    total_sol_invested: NotRequired[Decimal]
    total_sol_recovered: NotRequired[Decimal]
    net_profit_sol: NotRequired[Decimal]
    win_rate: NotRequired[Decimal]
    roi: NotRequired[Decimal]
    profit_factor: NotRequired[Decimal]
    gain_expectancy: NotRequired[Decimal]
    gain_expectancy_adjusted: NotRequired[Decimal]
    sharpe_ratio: NotRequired[Decimal]
    sortino_ratio: NotRequired[Decimal]
    pump_fun: NotRequired['PoolData']
    pump_swap: NotRequired['PoolData']


class PoolData(TypedDict):
    """
    Tipo para representar datos de un pool/exchange.
    """
    total_trades: int
    total_sol_invested: Decimal
    total_sol_recovered: Decimal
    net_profit_sol: Decimal
    win_rate: Decimal
    roi: Decimal
    profit_factor: Decimal
    gain_expectancy: Decimal
    gain_expectancy_adjusted: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal


class ParameterSearchConfig(TypedDict):
    """
    Configuración para una búsqueda de parámetros optimizados en backtests.
    
    Define una estrategia de búsqueda con su tipo de filtro, los parámetros
    a probar y la función para construir los validadores correspondientes.
    """
    filter_type: str
    filter_params: List[Dict[str, Any]]
    build_validator: Callable[[Dict[str, Any]], 'BacktestValidator']
