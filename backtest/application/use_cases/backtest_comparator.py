# -*- coding: utf-8 -*-
"""
Caso de uso: Comparación y emparejamiento de BacktestStats.

Compara dos BacktestStats (trader vs sistema) y empareja los closed_trades
por token_address para calcular estadísticas comparables.
"""
import logging
from typing import Tuple, Set
from datetime import datetime

from ...domain.entities.backtest_statistics import BacktestStats
from ...domain.entities.positions import ClosedTrade
from ...domain.services.metrics_calculator import MetricsCalculator

logger = logging.getLogger(__name__)


class BacktestComparator:
    """
    Caso de uso: Comparación de estadísticas de backtest.
    
    Empareja los trades cerrados de dos BacktestStats (trader vs sistema)
    por token_address, filtrando los trades del trader para que coincidan
    con los del sistema. Luego recalcula las estadísticas para ambos.
    """

    def __init__(self, metrics_calculator: MetricsCalculator):
        """
        Inicializa el comparador de backtest.
        
        Args:
            metrics_calculator: Calculador de métricas para recalcular estadísticas
        """
        self.metrics_calculator = metrics_calculator
        logger.debug("BacktestComparator inicializado")

    def compare_and_match_stats(
        self,
        trader_stats: BacktestStats,
        system_stats: BacktestStats
    ) -> Tuple[BacktestStats, BacktestStats]:
        """
        Compara y empareja dos BacktestStats por token_address.
        
        Filtra los trades del trader para que coincidan con los del sistema,
        manteniendo el orden cronológico. Luego recalcula las estadísticas
        para ambos con los trades emparejados.
        
        Args:
            trader_stats: Estadísticas del trader (repositorio pumpportal)
            system_stats: Estadísticas del sistema (repositorio system)
        
        Returns:
            Tupla con (trader_stats_matched, system_stats_matched) con trades emparejados
        
        Raises:
            ValueError: Si no hay trades en el sistema (no se puede emparejar)
        """
        if not system_stats.closed_trades:
            raise ValueError("No se pueden emparejar estadísticas: el sistema no tiene trades cerrados")

        # Ordenar trades por buy_timestamp para mantener orden cronológico
        system_trades_sorted = self._sort_trades_by_buy_timestamp(system_stats.closed_trades)
        trader_trades_sorted = self._sort_trades_by_buy_timestamp(trader_stats.closed_trades)

        # Emparejar trades del trader con los del sistema
        matched_trader_trades = self._match_trades_by_token(
            system_trades=system_trades_sorted,
            trader_trades=trader_trades_sorted
        )

        # Validar que se encontraron todos los trades del sistema
        if len(matched_trader_trades) != len(system_trades_sorted):
            missing_count = len(system_trades_sorted) - len(matched_trader_trades)
            logger.warning(
                f"No se pudieron emparejar {missing_count} trades del sistema. "
                f"Sistema: {len(system_trades_sorted)} trades, Trader emparejados: {len(matched_trader_trades)}"
            )

        # Recalcular estadísticas para el trader con trades emparejados
        trader_stats_matched = self.metrics_calculator.calculate_stats(
            trades=matched_trader_trades,
            open_positions=trader_stats.open_positions,
            validation_metrics=trader_stats.validation_metrics
        )

        # Recalcular estadísticas para el sistema (usar los mismos trades ya ordenados)
        system_stats_matched = self.metrics_calculator.calculate_stats(
            trades=system_trades_sorted,
            open_positions=system_stats.open_positions,
            validation_metrics=system_stats.validation_metrics
        )

        logger.info(
            f"Trades emparejados: Trader={len(matched_trader_trades)}, Sistema={len(system_trades_sorted)}"
        )

        return (trader_stats_matched, system_stats_matched)

    def _sort_trades_by_buy_timestamp(self, trades: list[ClosedTrade]) -> list[ClosedTrade]:
        """
        Ordena los trades por buy_timestamp (fecha de compra).
        
        Args:
            trades: Lista de trades a ordenar
        
        Returns:
            Lista de trades ordenada por buy_timestamp ascendente
        """
        def parse_timestamp(timestamp_str: str) -> datetime:
            """Parsea un timestamp ISO a datetime."""
            try:
                # Intentar parsear como ISO 8601
                if timestamp_str.endswith('Z'):
                    timestamp_str = timestamp_str[:-1] + '+00:00'
                return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # Si falla, intentar otros formatos comunes
                try:
                    return datetime.fromisoformat(timestamp_str)
                except ValueError:
                    logger.warning(f"No se pudo parsear timestamp: {timestamp_str}, usando datetime mínimo")
                    return datetime.min

        return sorted(trades, key=lambda t: parse_timestamp(t.buy_timestamp))

    def _match_trades_by_token(
        self,
        system_trades: list[ClosedTrade],
        trader_trades: list[ClosedTrade]
    ) -> list[ClosedTrade]:
        """
        Empareja los trades del trader con los del sistema por token_address.
        
        Para cada trade del sistema, busca el primer trade del trader con el mismo
        token_address que aún no haya sido usado, manteniendo el orden cronológico.
        
        Args:
            system_trades: Lista ordenada de trades del sistema
            trader_trades: Lista ordenada de trades del trader
        
        Returns:
            Lista de trades del trader emparejados con los del sistema
        """
        matched_trader_trades: list[ClosedTrade] = []
        used_trader_indices: Set[int] = set()

        for system_trade in system_trades:
            # Buscar el primer trade del trader con el mismo token_address no usado
            matched = False
            for idx, trader_trade in enumerate(trader_trades):
                if idx in used_trader_indices:
                    continue

                # Emparejar por token_address (no importa el monto)
                if trader_trade.token_address.lower() == system_trade.token_address.lower():
                    matched_trader_trades.append(trader_trade)
                    used_trader_indices.add(idx)
                    matched = True
                    logger.debug(
                        f"Emparejado: Sistema trade {system_trade.token_symbol} "
                        f"({system_trade.buy_timestamp}) con Trader trade "
                        f"({trader_trade.buy_timestamp})"
                    )
                    break

            if not matched:
                logger.warning(
                    f"No se encontró trade del trader para sistema: "
                    f"{system_trade.token_symbol} ({system_trade.token_address}) "
                    f"en {system_trade.buy_timestamp}"
                )

        return matched_trader_trades
