# -*- coding: utf-8 -*-
"""
Caso de uso: Comparación y emparejamiento de BacktestStats.

Compara dos BacktestStats (trader vs sistema) y empareja los closed_trades
por token_address para calcular estadísticas comparables.
"""
import logging
from typing import Tuple, Optional
from datetime import datetime, timedelta
from collections import defaultdict, deque

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
        matched_trader_trades, matched_system_trades = self._match_trades_by_token(
            system_trades=system_trades_sorted,
            trader_trades=trader_trades_sorted
        )

        # Validar que se encontraron todos los trades del sistema
        if not matched_system_trades or not matched_trader_trades:
            raise ValueError("No se pudieron emparejar trades del trader y del sistema")

        # Recalcular estadísticas para el trader con trades emparejados
        trader_stats_matched = self.metrics_calculator.calculate_stats(
            trades=matched_trader_trades,
            open_positions=trader_stats.open_positions,
            validation_metrics=trader_stats.validation_metrics
        )

        # Recalcular estadísticas para el sistema usando solo los trades emparejados
        system_stats_matched = self.metrics_calculator.calculate_stats(
            trades=matched_system_trades,
            open_positions=system_stats.open_positions,
            validation_metrics=system_stats.validation_metrics
        )

        logger.info(
            f"Trades emparejados: Trader={len(matched_trader_trades)}, Sistema={len(matched_system_trades)}"
        )

        return (trader_stats_matched, system_stats_matched)

    @staticmethod
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

    def _sort_trades_by_buy_timestamp(self, trades: list[ClosedTrade]) -> list[ClosedTrade]:
        """
        Ordena los trades por buy_timestamp (fecha de compra).
        
        Args:
            trades: Lista de trades a ordenar
        
        Returns:
            Lista de trades ordenada por buy_timestamp ascendente
        """
        return sorted(trades, key=lambda t: self.parse_timestamp(t.buy_timestamp))

    def _get_system_time_range(
        self,
        system_trades: list[ClosedTrade]
    ) -> Tuple[datetime, datetime]:
        """
        Calcula el rango de tiempo del sistema (primer y último trade).
        
        Args:
            system_trades: Lista ordenada de trades del sistema
        
        Returns:
            Tupla (min_timestamp, max_timestamp) del rango del sistema
        """
        if not system_trades:
            raise ValueError("No hay trades del sistema para calcular rango")

        first_trade = system_trades[0]
        last_trade = system_trades[-1]

        min_timestamp = self.parse_timestamp(first_trade.buy_timestamp)
        max_timestamp = self.parse_timestamp(last_trade.buy_timestamp)

        return (min_timestamp, max_timestamp)

    def _filter_trader_trades_by_system_time_range(
        self,
        trader_trades: list[ClosedTrade],
        system_trades: list[ClosedTrade],
        time_window_seconds: int = 60
    ) -> list[ClosedTrade]:
        """
        Filtra los trades del trader que están dentro del rango de tiempo del sistema
        con una ventana de tolerancia.
        
        El sistema replica trades del trader, por lo que solo debemos considerar
        trades del trader que estén cerca temporalmente del rango del sistema.
        
        Args:
            trader_trades: Lista de trades del trader
            system_trades: Lista ordenada de trades del sistema
            time_window_seconds: Ventana de tiempo en segundos antes del primer trade
                                y después del último trade del sistema (default: 1 minuto)
        
        Returns:
            Lista de trades del trader filtrados
        """
        if not system_trades:
            return []

        min_timestamp, max_timestamp = self._get_system_time_range(system_trades)

        # Expandir el rango con la ventana de tolerancia
        window = timedelta(seconds=time_window_seconds)
        min_allowed = min_timestamp - window
        max_allowed = max_timestamp + window

        trades_filtered: list[ClosedTrade] = []

        for trade in trader_trades:
            trade_timestamp = self.parse_timestamp(trade.buy_timestamp)

            # Incluir trades dentro del rango expandido
            if min_allowed <= trade_timestamp <= max_allowed:
                trades_filtered.append(trade)

        logger.debug(
            f"Filtrado temporal: {len(trades_filtered)}/{len(trader_trades)} trades del trader "
            f"dentro del rango del sistema ({min_timestamp} a {max_timestamp})"
        )

        return trades_filtered

    def _match_trades_by_token(
        self,
        system_trades: list[ClosedTrade],
        trader_trades: list[ClosedTrade],
        max_time_diff_seconds: int = 60
    ) -> Tuple[list[ClosedTrade], list[ClosedTrade]]:
        """
        Empareja los trades del trader con los del sistema por token_address y proximidad temporal.
        
        El sistema replica trades del trader en milésimas de segundo después, por lo que:
        - El trade del trader SIEMPRE debe ser anterior (menor timestamp) al trade del sistema
        - Ambos deben tener el mismo token_address
        - Se mantiene el orden cronológico
        
        Args:
            system_trades: Lista ordenada de trades del sistema
            trader_trades: Lista ordenada de trades del trader
            max_time_diff_seconds: Máxima diferencia de tiempo permitida en segundos
                                (default: 1 minuto). El trade del trader debe ser
                                anterior al trade del sistema dentro de esta ventana.
        
        Returns:
            Tupla con (matched_trader_trades, matched_system_trades) - ambos listas de trades emparejados
        """
        # PASO 1: Filtrar trades del trader por rango temporal del sistema
        trader_trades_filtered = self._filter_trader_trades_by_system_time_range(
            trader_trades=trader_trades,
            system_trades=system_trades,
            time_window_seconds=max_time_diff_seconds
        )

        # PASO 2: Indexar trades del trader por token_address (O(m))
        # Normalizar a lowercase para evitar problemas de case-sensitivity
        trader_trades_by_token: defaultdict[str, deque[ClosedTrade]] = defaultdict(deque)

        for trade in trader_trades_filtered:
            token_key = trade.token_address.lower()
            trader_trades_by_token[token_key].append(trade)

        # PASO 3: Emparejar trades del sistema con los del trader (O(n))
        matched_trader_trades: list[ClosedTrade] = []
        matched_system_trades: list[ClosedTrade] = []

        for system_trade in system_trades:
            token_key = system_trade.token_address.lower()
            system_timestamp = self.parse_timestamp(system_trade.buy_timestamp)

            # Obtener la cola de trades disponibles para este token
            available_trades = trader_trades_by_token.get(token_key)

            if not available_trades or len(available_trades) == 0:
                logger.warning(
                    f"No se encontró trade del trader para sistema: "
                    f"{system_trade.token_symbol} ({system_trade.token_address}) "
                    f"en {system_trade.buy_timestamp}"
                )
                continue

            # Buscar el mejor match: trade del trader que sea ANTERIOR al del sistema
            # El sistema replica trades en milésimas de segundo después del trader
            matched = False
            best_match: Optional[ClosedTrade] = None
            best_time_diff: float = float('inf')

            # Iterar sobre los trades disponibles (ya están ordenados cronológicamente)
            # Solo considerar trades que sean ANTERIORES al trade del sistema
            while len(available_trades) > 0:
                head_trade = available_trades[0]
                trader_timestamp = self.parse_timestamp(head_trade.buy_timestamp)

                # Calcular diferencia de tiempo (positiva si trader es anterior)
                time_diff = (system_timestamp - trader_timestamp).total_seconds()

                # Si el trade del trader es posterior o igual al del sistema, descartar
                if time_diff <= 0:
                    # El trade del trader es posterior o igual, descartar
                    # (el sistema siempre replica después, nunca antes o al mismo tiempo)
                    available_trades.popleft()
                    continue

                # Si el trade del trader es anterior pero fuera de la ventana, descartar
                if time_diff > max_time_diff_seconds:
                    # El trade del trader es demasiado anterior, descartar
                    available_trades.popleft()
                    continue

                # El trade del trader es anterior y dentro de la ventana: candidato válido
                # Buscar el más cercano (menor diferencia de tiempo)
                if time_diff < best_time_diff:
                    best_match = head_trade
                    best_time_diff = time_diff

                # Continuar buscando para encontrar el trade más cercano
                available_trades.popleft()

            # Si encontramos un match válido (trade anterior dentro de la ventana)
            if best_match is not None:
                matched_trader_trades.append(best_match)
                matched_system_trades.append(system_trade)  # Agregar también el trade del sistema emparejado
                matched = True
                logger.debug(
                    f"Emparejado: Sistema trade {system_trade.token_symbol} "
                    f"({system_trade.buy_timestamp}) con Trader trade "
                    f"({best_match.buy_timestamp}), diff={best_time_diff:.3f}s "
                    f"(trader anterior al sistema)"
                )

            if not matched:
                logger.warning(
                    f"No se encontró trade del trader para sistema: "
                    f"{system_trade.token_symbol} ({system_trade.token_address}) "
                    f"en {system_trade.buy_timestamp}"
                )

        return (matched_trader_trades, matched_system_trades)
