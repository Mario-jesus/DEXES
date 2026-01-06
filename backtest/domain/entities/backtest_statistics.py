# -*- coding: utf-8 -*-
"""
Entidades de dominio relacionadas con estadísticas y métricas.

Contiene las entidades que representan estadísticas calculadas del backtest,
incluyendo métricas generales, por exchange, y de validación.
"""
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import List, Optional, Dict, Any

from .positions import ClosedTrade, Position


@dataclass
class PoolStats:
    """
    Entidad de dominio: Estadísticas agregadas por pool/exchange.
    
    Contiene métricas de rendimiento calculadas para un exchange específico.
    """
    exchange_address: str  # Dirección del programa del exchange
    exchange_name: Optional[str] = None  # Nombre interno normalizado
    total_trades: int = 0
    profitable_trades: int = 0
    losing_trades: int = 0
    break_even_trades: int = 0
    total_profit_sol: Decimal = Decimal('0')
    total_loss_sol: Decimal = Decimal('0')
    net_profit_sol: Decimal = Decimal('0')
    total_sol_invested: Decimal = Decimal('0')
    total_sol_recovered: Decimal = Decimal('0')
    win_rate: Decimal = Decimal('0')
    avg_profit_per_trade: Decimal = Decimal('0')
    avg_profit_per_winning_trade: Decimal = Decimal('0')
    avg_loss_per_losing_trade: Decimal = Decimal('0')
    roi: Decimal = Decimal('0')
    profit_factor: Decimal = Decimal('0')
    gain_expectancy: Decimal = Decimal('0')
    gain_expectancy_adjusted: Decimal = Decimal('0')
    sharpe_ratio: Decimal = Decimal('0')
    sortino_ratio: Decimal = Decimal('0')
    best_trade: Optional[ClosedTrade] = None
    worst_trade: Optional[ClosedTrade] = None


@dataclass
class ValidationMetrics:
    """
    Entidad de dominio: Métricas agregadas de validaciones.
    
    Contiene información sobre cuántas transacciones fueron validadas
    y cuántas fueron rechazadas durante el proceso de backtest.
    """
    total_buy_transactions: int = 0
    accepted_buy_transactions: int = 0
    filtered_transactions: int = 0
    filter_acceptance_rate: Decimal = Decimal('0')
    validation_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class BacktestStats:
    """
    Entidad de dominio: Estadísticas agregadas del backtest completo.
    
    Contiene todas las métricas calculadas después de ejecutar un backtest,
    incluyendo métricas generales, por exchange, y de validación.
    """
    total_trades: int = 0
    profitable_trades: int = 0
    losing_trades: int = 0
    break_even_trades: int = 0
    total_profit_sol: Decimal = Decimal('0')
    total_loss_sol: Decimal = Decimal('0')
    net_profit_sol: Decimal = Decimal('0')
    total_sol_invested: Decimal = Decimal('0')
    total_sol_recovered: Decimal = Decimal('0')
    win_rate: Decimal = Decimal('0')
    avg_profit_per_trade: Decimal = Decimal('0')
    avg_profit_per_winning_trade: Decimal = Decimal('0')
    avg_loss_per_losing_trade: Decimal = Decimal('0')
    best_trade: Optional[ClosedTrade] = None
    worst_trade: Optional[ClosedTrade] = None
    roi: Decimal = Decimal('0')
    profit_factor: Decimal = Decimal('0')
    gain_expectancy: Decimal = Decimal('0')
    gain_expectancy_adjusted: Decimal = Decimal('0')
    sharpe_ratio: Decimal = Decimal('0')
    sortino_ratio: Decimal = Decimal('0')
    closed_trades: List[ClosedTrade] = field(default_factory=list)
    open_positions: List[Position] = field(default_factory=list)
    # Métricas de validación (opcional, solo si se usó un validador)
    validation_metrics: Optional[ValidationMetrics] = None
    # Métricas por pool/exchange
    pool_stats: Dict[str, PoolStats] = field(default_factory=dict)
    # Métricas de filtrado por fecha
    date_range_start: Optional[str] = None  # Fecha de inicio del rango (ISO format)
    date_range_end: Optional[str] = None  # Fecha de fin del rango (ISO format)
    total_transactions_before_date_filter: int = 0
    date_filtered_transactions: int = 0
    # Métricas de tiempo en los datos (rango completo sin filtros)
    min_timestamp: Optional[str] = None  # Timestamp mínimo (ISO format)
    max_timestamp: Optional[str] = None  # Timestamp máximo (ISO format)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convierte la entidad a diccionario.
        
        Returns:
            Diccionario con todos los campos de la entidad
        """
        return asdict(self)
