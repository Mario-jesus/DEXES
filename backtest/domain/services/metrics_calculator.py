# -*- coding: utf-8 -*-
"""
Servicio: Cálculo de métricas y estadísticas.

Implementa la lógica de cálculo de métricas de rendimiento,
incluyendo métricas básicas, avanzadas y por exchange/pool.
"""
import logging
from collections import defaultdict
from typing import List, Dict, Optional
from decimal import Decimal

from ...domain.entities.positions import Position
from ...domain.entities.backtest_statistics import (
    ClosedTrade,
    BacktestStats,
    PoolStats,
    ValidationMetrics
)

logger = logging.getLogger(__name__)


class MetricsCalculator:
    """
    Servicio de dominio: Cálculo de métricas de rendimiento.
    
    Calcula estadísticas agregadas del backtest, incluyendo métricas básicas,
    avanzadas (Sharpe, Sortino, etc.) y métricas por exchange/pool.
    """

    def __init__(self, get_exchange_name_func=None):
        """
        Inicializa el calculador de métricas.
        
        Args:
            get_exchange_name_func: Función opcional para obtener nombre interno
                                    del exchange por dirección. Si es None, se
                                    usará el nombre del trade directamente.
        """
        self.get_exchange_name = get_exchange_name_func

    def calculate_stats(
        self,
        trades: List[ClosedTrade],
        open_positions: List[Position],
        validation_metrics: Optional[ValidationMetrics] = None
    ) -> BacktestStats:
        """
        Calcula estadísticas agregadas del backtest completo.
        
        Args:
            trades: Lista de trades cerrados
            open_positions: Lista de posiciones abiertas
            validation_metrics: Métricas de validación opcionales
        
        Returns:
            BacktestStats con todas las estadísticas calculadas
        
        Raises:
            ValueError: Si no hay trades para calcular estadísticas
        """
        if not trades:
            raise ValueError("No se pueden calcular estadísticas sin trades cerrados")

        total_trades = len(trades)
        profitable = [t for t in trades if t.profit_loss_sol > 0]
        losing = [t for t in trades if t.profit_loss_sol < 0]
        break_even = [t for t in trades if t.profit_loss_sol == 0]

        total_profit = sum((t.profit_loss_sol for t in profitable), Decimal('0'))
        total_loss = sum((abs(t.profit_loss_sol) for t in losing), Decimal('0'))
        net_profit = sum((t.profit_loss_sol for t in trades), Decimal('0'))

        total_invested = sum((t.sol_invested for t in trades), Decimal('0'))
        total_recovered = sum((t.sol_recovered for t in trades), Decimal('0'))

        win_rate = (
            Decimal(len(profitable)) / Decimal(total_trades) * 100 
            if total_trades > 0 
            else Decimal('0')
        )
        win_rate_decimal = (
            Decimal(len(profitable)) / Decimal(total_trades) 
            if total_trades > 0 
            else Decimal('0')
        )

        avg_profit_per_trade = (
            net_profit / Decimal(total_trades) 
            if total_trades > 0 
            else Decimal('0')
        )
        avg_profit_winning = (
            total_profit / Decimal(len(profitable)) 
            if profitable 
            else Decimal('0')
        )
        avg_loss_losing = (
            -total_loss / Decimal(len(losing)) 
            if losing 
            else Decimal('0')
        )

        best_trade = max(trades, key=lambda t: t.profit_loss_sol) if trades else None
        worst_trade = min(trades, key=lambda t: t.profit_loss_sol) if trades else None

        roi = (
            (net_profit / total_invested * 100) 
            if total_invested > 0 
            else Decimal('0')
        )

        # Calcular métricas avanzadas
        advanced_metrics = self.calculate_advanced_metrics(
            trades=trades,
            total_profit=total_profit,
            total_loss=total_loss,
            win_rate_decimal=win_rate_decimal,
            avg_profit_winning=avg_profit_winning,
            avg_loss_losing=avg_loss_losing
        )

        # Calcular métricas por pool/exchange
        pool_stats_dict = self.calculate_pool_stats(trades)

        return BacktestStats(
            total_trades=total_trades,
            profitable_trades=len(profitable),
            losing_trades=len(losing),
            break_even_trades=len(break_even),
            total_profit_sol=total_profit,
            total_loss_sol=total_loss,
            net_profit_sol=net_profit,
            total_sol_invested=total_invested,
            total_sol_recovered=total_recovered,
            win_rate=win_rate,
            avg_profit_per_trade=avg_profit_per_trade,
            avg_profit_per_winning_trade=avg_profit_winning,
            avg_loss_per_losing_trade=avg_loss_losing,
            best_trade=best_trade,
            worst_trade=worst_trade,
            roi=roi,
            profit_factor=advanced_metrics['profit_factor'],
            gain_expectancy=advanced_metrics['gain_expectancy'],
            gain_expectancy_adjusted=advanced_metrics['gain_expectancy_adjusted'],
            sharpe_ratio=advanced_metrics['sharpe_ratio'],
            sortino_ratio=advanced_metrics['sortino_ratio'],
            closed_trades=trades.copy(),
            open_positions=open_positions.copy(),
            validation_metrics=validation_metrics,
            pool_stats=pool_stats_dict
        )

    def calculate_advanced_metrics(
        self,
        trades: List[ClosedTrade],
        total_profit: Decimal,
        total_loss: Decimal,
        win_rate_decimal: Decimal,
        avg_profit_winning: Decimal,
        avg_loss_losing: Decimal
    ) -> Dict[str, Decimal]:
        """
        Calcula métricas avanzadas de riesgo y retorno.
        
        Args:
            trades: Lista de trades cerrados
            total_profit: Suma total de ganancias
            total_loss: Suma total de pérdidas (valor absoluto)
            win_rate_decimal: Win rate como decimal (0-1)
            avg_profit_winning: Promedio de ganancias por trade ganador
            avg_loss_losing: Promedio de pérdidas por trade perdedor (negativo)
        
        Returns:
            Diccionario con las métricas calculadas:
            - profit_factor
            - gain_expectancy
            - gain_expectancy_adjusted
            - sharpe_ratio
            - sortino_ratio
        """
        if not trades:
            return {
                'profit_factor': Decimal('0'),
                'gain_expectancy': Decimal('0'),
                'gain_expectancy_adjusted': Decimal('0'),
                'sharpe_ratio': Decimal('0'),
                'sortino_ratio': Decimal('0')
            }

        # 1. PROFIT FACTOR
        profit_factor = (
            total_profit / total_loss 
            if total_loss > 0 
            else Decimal('0')
        )

        # 2. GAIN EXPECTANCY
        loss_rate = Decimal('1') - win_rate_decimal
        gain_expectancy = (
            (win_rate_decimal * avg_profit_winning) - 
            (loss_rate * abs(avg_loss_losing))
        )

        # Obtener retornos porcentuales para cálculos estadísticos
        returns = [t.profit_loss_pct for t in trades]

        # 3. GAIN EXPECTANCY ADJUSTED, SHARPE RATIO, SORTINO RATIO
        # Calcular desviación estándar de retornos
        if len(returns) > 1:
            mean_return = sum(returns) / Decimal(len(returns))

            # Varianza (usando n-1 para muestra)
            variance = sum((r - mean_return) ** 2 for r in returns) / Decimal(len(returns) - 1)
            std_dev = variance.sqrt() if variance >= 0 else Decimal('0')

            # Gain Expectancy Adjusted
            gain_expectancy_adjusted = (
                gain_expectancy / std_dev 
                if std_dev > 0 
                else Decimal('0')
            )

            # Sharpe Ratio (Risk Free Rate = 0)
            sharpe_ratio = (
                mean_return / std_dev 
                if std_dev > 0 
                else Decimal('0')
            )

            # Sortino Ratio (Target Return = 0)
            # Downside deviation: solo retornos negativos
            negative_returns = [r for r in returns if r < 0]
            if negative_returns and len(negative_returns) > 1:
                downside_mean = sum(negative_returns) / Decimal(len(negative_returns))
                downside_variance = sum(
                    (r - downside_mean) ** 2 for r in negative_returns
                ) / Decimal(len(negative_returns) - 1)
                downside_deviation = (
                    downside_variance.sqrt() 
                    if downside_variance >= 0 
                    else Decimal('0')
                )
                sortino_ratio = (
                    mean_return / downside_deviation 
                    if downside_deviation > 0 
                    else Decimal('0')
                )
            elif negative_returns and len(negative_returns) == 1:
                # Solo un retorno negativo, usar su valor absoluto como desviación
                downside_deviation = abs(negative_returns[0])
                sortino_ratio = (
                    mean_return / downside_deviation 
                    if downside_deviation > 0 
                    else Decimal('0')
                )
            else:
                # No hay retornos negativos
                sortino_ratio = Decimal('0')
        else:
            # Solo un trade o menos, no se puede calcular desviación
            gain_expectancy_adjusted = Decimal('0')
            sharpe_ratio = Decimal('0')
            sortino_ratio = Decimal('0')

        return {
            'profit_factor': profit_factor,
            'gain_expectancy': gain_expectancy,
            'gain_expectancy_adjusted': gain_expectancy_adjusted,
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio
        }

    def calculate_pool_stats(self, trades: List[ClosedTrade]) -> Dict[str, PoolStats]:
        """
        Calcula estadísticas por exchange/pool.
        
        Args:
            trades: Lista de trades cerrados
        
        Returns:
            Diccionario que mapea exchange_address -> PoolStats
        """
        pool_stats_dict: Dict[str, PoolStats] = {}

        # Agrupar trades por exchange_address (dirección del programa)
        trades_by_exchange: Dict[str, List[ClosedTrade]] = defaultdict(list)
        for trade in trades:
            # Usar exchange_address como clave principal, fallback a "Unknown" si no hay
            exchange_key = trade.exchange_address or "Unknown"
            trades_by_exchange[exchange_key].append(trade)

        # Calcular estadísticas para cada exchange
        for exchange_address_key, exchange_trades in trades_by_exchange.items():
            if not exchange_trades:
                continue

            exchange_profitable = [t for t in exchange_trades if t.profit_loss_sol > 0]
            exchange_losing = [t for t in exchange_trades if t.profit_loss_sol < 0]
            exchange_break_even = [t for t in exchange_trades if t.profit_loss_sol == 0]

            exchange_total_profit = sum(
                (t.profit_loss_sol for t in exchange_profitable), 
                Decimal('0')
            )
            exchange_total_loss = sum(
                (abs(t.profit_loss_sol) for t in exchange_losing), 
                Decimal('0')
            )
            exchange_net_profit = sum(
                (t.profit_loss_sol for t in exchange_trades), 
                Decimal('0')
            )
            
            exchange_total_invested = sum(
                (t.sol_invested for t in exchange_trades), 
                Decimal('0')
            )
            exchange_total_recovered = sum(
                (t.sol_recovered for t in exchange_trades), 
                Decimal('0')
            )

            exchange_win_rate = (
                Decimal(len(exchange_profitable)) / Decimal(len(exchange_trades)) * 100 
                if exchange_trades 
                else Decimal('0')
            )
            exchange_win_rate_decimal = (
                Decimal(len(exchange_profitable)) / Decimal(len(exchange_trades)) 
                if exchange_trades 
                else Decimal('0')
            )
            exchange_avg_profit_per_trade = (
                exchange_net_profit / Decimal(len(exchange_trades)) 
                if exchange_trades 
                else Decimal('0')
            )
            exchange_avg_profit_winning = (
                exchange_total_profit / Decimal(len(exchange_profitable)) 
                if exchange_profitable 
                else Decimal('0')
            )
            exchange_avg_loss_losing = (
                -exchange_total_loss / Decimal(len(exchange_losing)) 
                if exchange_losing 
                else Decimal('0')
            )
            exchange_roi = (
                (exchange_net_profit / exchange_total_invested * 100) 
                if exchange_total_invested > 0 
                else Decimal('0')
            )

            # Calcular métricas avanzadas para este exchange
            exchange_advanced_metrics = self.calculate_advanced_metrics(
                trades=exchange_trades,
                total_profit=exchange_total_profit,
                total_loss=exchange_total_loss,
                win_rate_decimal=exchange_win_rate_decimal,
                avg_profit_winning=exchange_avg_profit_winning,
                avg_loss_losing=exchange_avg_loss_losing
            )

            exchange_best_trade = (
                max(exchange_trades, key=lambda t: t.profit_loss_sol) 
                if exchange_trades 
                else None
            )
            exchange_worst_trade = (
                min(exchange_trades, key=lambda t: t.profit_loss_sol) 
                if exchange_trades 
                else None
            )

            # Obtener el nombre interno normalizado para display
            exchange_internal_name = None
            if exchange_address_key != "Unknown":
                if self.get_exchange_name:
                    exchange_internal_name = self.get_exchange_name(exchange_address_key)
                # Si no hay función o no devuelve nada, usar el nombre del primer trade como fallback
                if not exchange_internal_name and exchange_trades:
                    exchange_internal_name = exchange_trades[0].exchange_name
            else:
                # Si es Unknown, usar el nombre del primer trade si está disponible
                if exchange_trades:
                    exchange_internal_name = exchange_trades[0].exchange_name

            pool_stats_dict[exchange_address_key] = PoolStats(
                exchange_address=exchange_address_key,
                exchange_name=exchange_internal_name,
                total_trades=len(exchange_trades),
                profitable_trades=len(exchange_profitable),
                losing_trades=len(exchange_losing),
                break_even_trades=len(exchange_break_even),
                total_profit_sol=exchange_total_profit,
                total_loss_sol=exchange_total_loss,
                net_profit_sol=exchange_net_profit,
                total_sol_invested=exchange_total_invested,
                total_sol_recovered=exchange_total_recovered,
                win_rate=exchange_win_rate,
                avg_profit_per_trade=exchange_avg_profit_per_trade,
                avg_profit_per_winning_trade=exchange_avg_profit_winning,
                avg_loss_per_losing_trade=exchange_avg_loss_losing,
                roi=exchange_roi,
                profit_factor=exchange_advanced_metrics['profit_factor'],
                gain_expectancy=exchange_advanced_metrics['gain_expectancy'],
                gain_expectancy_adjusted=exchange_advanced_metrics['gain_expectancy_adjusted'],
                sharpe_ratio=exchange_advanced_metrics['sharpe_ratio'],
                sortino_ratio=exchange_advanced_metrics['sortino_ratio'],
                best_trade=exchange_best_trade,
                worst_trade=exchange_worst_trade
            )

        return pool_stats_dict
