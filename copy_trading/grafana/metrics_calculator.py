# -*- coding: utf-8 -*-
"""
Calculador de métricas de trading.
Maneja acumulación de PnL en memoria y genera métricas.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal

from logging_system import AppLogger


class TradingMetricsCalculator:
    """Calcula métricas de trading a partir de datos leídos."""

    def __init__(self):
        self._logger = AppLogger(self.__class__.__name__)

        # Estado en memoria para acumulación
        self.cumulative_pnl_by_trader: Dict[str, Decimal] = {}
        self.last_pnl_timestamp: Optional[datetime] = None

        # Capital en memoria
        self.initial_capital: Optional[Decimal] = None
        self.current_capital: Optional[Decimal] = None

        # Tracking de capital máximo histórico para drawdown
        self.max_capital_by_trader: Dict[str, Decimal] = {}
        self.max_capital_total: Optional[Decimal] = None

    def set_initial_capital(self, initial_capital: Decimal) -> None:
        """
        Establece el capital inicial del sistema.
        
        Args:
            initial_capital: Capital inicial en SOL
        """
        self.initial_capital = initial_capital
        # Inicializar capital actual con el capital inicial
        self.current_capital = initial_capital
        # Inicializar máximo total con el capital inicial
        self.max_capital_total = initial_capital
        self._logger.debug(f"Capital inicial establecido: {initial_capital} SOL")

    def reset_state(self) -> None:
        """Resetea el estado acumulado."""
        self.cumulative_pnl_by_trader = {}
        self.last_pnl_timestamp = None
        self.initial_capital = None
        self.current_capital = None
        self.max_capital_by_trader = {}
        self.max_capital_total = None
        self._logger.debug("Estado del calculador reseteado")

    def process_pnl_data(
        self,
        pnl_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Procesa datos de PnL y genera métricas acumuladas.

        Cada registro de PnL debe incluir su trader_wallet. Si es None (liquidaciones),
        se usa "UNKNOWN_TRADER" para agrupar.

        Args:
            pnl_data: Lista de diccionarios con timestamp, trader_wallet, 
            pnl_without_cost_sol, pnl_with_cost_sol

        Returns:
            Lista de métricas generadas
        """
        if not pnl_data:
            return []

        metrics = []

        for pnl_record in pnl_data:
            timestamp = pnl_record["timestamp"]
            trader_wallet = pnl_record.get("trader_wallet")

            # Usar "UNKNOWN_TRADER" para liquidaciones sin trader
            trader_key = trader_wallet if trader_wallet else "UNKNOWN_TRADER"

            # Inicializar acumulador si no existe
            if trader_key not in self.cumulative_pnl_by_trader:
                self.cumulative_pnl_by_trader[trader_key] = Decimal("0.0")

            pnl_with_cost = pnl_record.get("pnl_with_cost_sol") or Decimal("0.0")
            pnl_without_cost = pnl_record.get("pnl_without_cost_sol") or Decimal("0.0")

            # Usar PnL con costos por defecto
            pnl_value = pnl_with_cost if pnl_with_cost else pnl_without_cost

            # Acumular PnL por trader específico
            self.cumulative_pnl_by_trader[trader_key] += pnl_value

            # Actualizar último timestamp
            if self.last_pnl_timestamp is None or timestamp > self.last_pnl_timestamp:
                self.last_pnl_timestamp = timestamp

            # Calcular drawdown individual basado en el máximo PnL del trader
            # El drawdown individual representa la caída desde el máximo PnL alcanzado
            trader_pnl = self.cumulative_pnl_by_trader[trader_key]

            # Actualizar máximo PnL histórico del trader
            if trader_key not in self.max_capital_by_trader:
                # Inicializar con el PnL actual (puede ser negativo)
                self.max_capital_by_trader[trader_key] = trader_pnl
            else:
                # Actualizar máximo si el PnL actual es mayor
                if trader_pnl > self.max_capital_by_trader[trader_key]:
                    self.max_capital_by_trader[trader_key] = trader_pnl

            # Calcular drawdown individual (diferencia entre máximo PnL y PnL actual)
            max_trader_pnl = self.max_capital_by_trader[trader_key]
            drawdown_individual = max_trader_pnl - trader_pnl

            # Solo generar métrica si hay drawdown (PnL actual < máximo PnL)
            if drawdown_individual > 0:
                metrics.append({
                    "timestamp": timestamp,
                    "metric_name": "Drawdown_Individual",
                    "metric_value": float(drawdown_individual),
                    "trader": trader_key,
                })

            # Generar métrica de PnL acumulado individual
            metrics.append({
                "timestamp": timestamp,
                "metric_name": "PNL_Individual_Cumulative",
                "metric_value": float(self.cumulative_pnl_by_trader[trader_key]),
                "trader": trader_key,
            })

        # Calcular PnL total acumulado (suma de todos los traders, excluyendo "ALL_TRADERS" si existe)
        # Filtrar traders reales (no "ALL_TRADERS" que es solo una métrica calculada)
        traders_only = {
            k: v for k, v in self.cumulative_pnl_by_trader.items() 
            if k != "ALL_TRADERS"
        }
        total_pnl = sum(traders_only.values())

        # Agregar métrica de PnL total acumulado (usando el último timestamp)
        if pnl_data:
            last_timestamp = pnl_data[-1]["timestamp"]
            metrics.append({
                "timestamp": last_timestamp,
                "metric_name": "PNL_Total_Cumulative",
                "metric_value": float(total_pnl),
                "trader": "ALL_TRADERS",
            })

            # Calcular y actualizar capital actual
            if self.initial_capital is not None:
                self.current_capital = self.initial_capital + total_pnl

                # Actualizar máximo histórico total
                if self.max_capital_total is None:
                    self.max_capital_total = self.current_capital
                else:
                    if self.current_capital > self.max_capital_total:
                        self.max_capital_total = self.current_capital

                # Calcular drawdown total
                drawdown_total = self.max_capital_total - self.current_capital

                # Agregar métrica de Capital_Current
                metrics.append({
                    "timestamp": last_timestamp,
                    "metric_name": "Capital_Current",
                    "metric_value": float(self.current_capital),
                    "trader": "ALL_TRADERS",
                })

                # Agregar métrica de Drawdown_Total
                metrics.append({
                    "timestamp": last_timestamp,
                    "metric_name": "Drawdown_Total",
                    "metric_value": float(drawdown_total),
                    "trader": "ALL_TRADERS",
                })

        self._logger.debug(
            f"Procesados {len(pnl_data)} registros de PnL, "
            f"generadas {len(metrics)} métricas"
        )

        return metrics

    def get_current_metrics(
        self,
        *,
        current_timestamp: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Genera métricas actuales con los valores acumulados más recientes.

        Args:
            current_timestamp: Timestamp a usar (por defecto datetime.now())

        Returns:
            Lista de métricas actuales
        """
        if not self.cumulative_pnl_by_trader:
            return []

        timestamp = current_timestamp or datetime.now()
        metrics = []

        # PnL acumulado por trader (excluyendo "ALL_TRADERS" que es solo una métrica calculada)
        traders_only = {
            k: v for k, v in self.cumulative_pnl_by_trader.items() 
            if k != "ALL_TRADERS"
        }

        for trader, pnl in traders_only.items():
            metrics.append({
                "timestamp": timestamp,
                "metric_name": "PNL_Individual_Cumulative",
                "metric_value": float(pnl),
                "trader": trader,
            })

        # PnL total acumulado (suma de todos los traders reales)
        total_pnl = sum(traders_only.values())
        metrics.append({
            "timestamp": timestamp,
            "metric_name": "PNL_Total_Cumulative",
            "metric_value": float(total_pnl),
            "trader": "ALL_TRADERS",
        })

        # Calcular y agregar métrica de Capital_Current si tenemos capital inicial
        if self.initial_capital is not None:
            self.current_capital = self.initial_capital + total_pnl

            # Actualizar máximo histórico total si es necesario
            if self.max_capital_total is None:
                self.max_capital_total = self.current_capital
            else:
                if self.current_capital > self.max_capital_total:
                    self.max_capital_total = self.current_capital

            # Calcular drawdown total
            drawdown_total = self.max_capital_total - self.current_capital

            metrics.append({
                "timestamp": timestamp,
                "metric_name": "Capital_Current",
                "metric_value": float(self.current_capital),
                "trader": "ALL_TRADERS",
            })

            # Agregar métrica de Drawdown_Total
            metrics.append({
                "timestamp": timestamp,
                "metric_name": "Drawdown_Total",
                "metric_value": float(drawdown_total),
                "trader": "ALL_TRADERS",
            })

            # Calcular y agregar Drawdown_Individual para cada trader
            for trader, pnl in traders_only.items():
                # Actualizar máximo PnL histórico del trader si es necesario
                if trader not in self.max_capital_by_trader:
                    self.max_capital_by_trader[trader] = pnl
                else:
                    if pnl > self.max_capital_by_trader[trader]:
                        self.max_capital_by_trader[trader] = pnl

                # Calcular drawdown individual (diferencia entre máximo PnL y PnL actual)
                max_trader_pnl = self.max_capital_by_trader[trader]
                drawdown_individual = max_trader_pnl - pnl

                # Solo generar métrica si hay drawdown
                if drawdown_individual > 0:
                    metrics.append({
                        "timestamp": timestamp,
                        "metric_name": "Drawdown_Individual",
                        "metric_value": float(drawdown_individual),
                        "trader": trader,
                    })

        return metrics

    def get_last_pnl_timestamp(self) -> Optional[datetime]:
        """Obtiene el último timestamp de PnL procesado."""
        return self.last_pnl_timestamp

    def get_current_capital(self) -> Optional[Decimal]:
        """
        Obtiene el capital actual del sistema.
        
        Returns:
            Capital actual (initial_capital + total_pnl) o None si no hay capital inicial
        """
        if self.initial_capital is None:
            return None

        # Calcular capital actual si no está actualizado
        traders_only = {
            k: v for k, v in self.cumulative_pnl_by_trader.items() 
            if k != "ALL_TRADERS"
        }
        total_pnl = sum(traders_only.values()) if traders_only else Decimal("0.0")
        self.current_capital = self.initial_capital + total_pnl

        return self.current_capital
