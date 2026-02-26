# -*- coding: utf-8 -*-
"""
Calculador de métricas de trading.
Maneja acumulación de PnL en memoria y genera métricas.
"""
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from logging_system import AppLogger


class TradingMetricsCalculator:
    """Calcula métricas de trading a partir de datos leídos."""

    def __init__(self, max_trader_idle_days: Optional[float] = None):
        """
        Args:
            max_trader_idle_days: Si está definido, se eliminan de memoria los traders
                que no hayan aparecido en un snapshot en tantos días. Reduce memoria
                a costa de: en el ciclo siguiente a una poda, el total agregado puede
                subestimar hasta que se re-incorporan desde BD. Por defecto None (sin TTL).
        """
        self._logger = AppLogger(self.__class__.__name__)
        self._max_trader_idle_days = max_trader_idle_days

        # Estado en memoria para acumulación
        self.cumulative_pnl_by_trader: Dict[str, Decimal] = {}
        self.last_pnl_timestamp: Optional[datetime] = None
        self._last_seen_by_trader: Dict[str, datetime] = {}

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
        self._last_seen_by_trader = {}
        self.initial_capital = None
        self.current_capital = None
        self.max_capital_by_trader = {}
        self.max_capital_total = None
        self._logger.debug("Estado del calculador reseteado")

    def process_pnl_snapshot(
        self,
        pnl_data: List[Dict[str, Any]],
        *,
        current_timestamp: datetime,
        current_capital_onchain: Optional[Decimal] = None,
    ) -> List[Dict[str, Any]]:
        """
        Procesa un snapshot de PnL acumulado por trader y genera métricas.

        Compara los valores actuales con los valores en memoria y genera métricas
        solo cuando hay cambios. Los datos ya vienen acumulados desde PNLRealizedTrader.

        Args:
            pnl_data: Lista de diccionarios con trader_wallet, pnl_with_cost_sol
            current_timestamp: Timestamp a usar para las métricas generadas
            current_capital_onchain: Capital actual obtenido on-chain (balance SOL de la wallet)

        Returns:
            Lista de métricas generadas
        """
        if not pnl_data:
            return []

        metrics = []
        has_changes = False

        # Procesar cada trader del snapshot
        keys_in_snapshot = set()
        for pnl_record in pnl_data:
            trader_wallet = pnl_record.get("trader_wallet")
            if not trader_wallet:
                continue

            trader_key = trader_wallet
            keys_in_snapshot.add(trader_key)

            # Obtener PnL acumulado del snapshot
            pnl_with_cost = pnl_record.get("pnl_with_cost_sol")
            if pnl_with_cost is None:
                continue

            current_pnl = Decimal(str(pnl_with_cost))

            # Obtener PnL anterior en memoria (si existe)
            previous_pnl = self.cumulative_pnl_by_trader.get(trader_key, Decimal("0.0"))

            # Solo generar métricas si el valor cambió
            if current_pnl != previous_pnl:
                has_changes = True
                # Actualizar valor en memoria
                self.cumulative_pnl_by_trader[trader_key] = current_pnl
                self._last_seen_by_trader[trader_key] = current_timestamp

                # Actualizar máximo PnL histórico del trader
                if trader_key not in self.max_capital_by_trader:
                    self.max_capital_by_trader[trader_key] = current_pnl
                else:
                    if current_pnl > self.max_capital_by_trader[trader_key]:
                        self.max_capital_by_trader[trader_key] = current_pnl

                # Calcular drawdown individual
                # El drawdown se calcula desde el máximo entre 0 y el máximo histórico del trader
                # - Si el trader ha tenido ganancias: drawdown desde el máximo histórico
                # - Si el trader nunca ha tenido ganancias: drawdown desde 0 (pérdidas desde inicio)
                max_trader_pnl = self.max_capital_by_trader[trader_key]
                reference_point = max(Decimal("0.0"), max_trader_pnl)
                drawdown_individual = reference_point - current_pnl

                # Generar métrica de PnL acumulado individual
                metrics.append({
                    "timestamp": current_timestamp,
                    "metric_name": "PNL_Individual_Cumulative",
                    "metric_value": float(current_pnl),
                    "trader": trader_key,
                })

                # Generar métrica de drawdown si hay drawdown (diferencia positiva)
                if drawdown_individual > 0:
                    metrics.append({
                        "timestamp": current_timestamp,
                        "metric_name": "Drawdown_Individual",
                        "metric_value": float(drawdown_individual),
                        "trader": trader_key,
                    })

        # Si hubo cambios, calcular y generar métricas agregadas
        if has_changes:
            # Actualizar último timestamp
            if self.last_pnl_timestamp is None or current_timestamp > self.last_pnl_timestamp:
                self.last_pnl_timestamp = current_timestamp

            # Calcular PnL total acumulado (suma de todos los traders, excluyendo "ALL_TRADERS")
            traders_only = {
                k: v for k, v in self.cumulative_pnl_by_trader.items() 
                if k != "ALL_TRADERS"
            }
            total_pnl = sum(traders_only.values()) if traders_only else Decimal("0.0")

            # Agregar métrica de PnL total acumulado
            metrics.append({
                "timestamp": current_timestamp,
                "metric_name": "PNL_Total_Cumulative",
                "metric_value": float(total_pnl),
                "trader": "ALL_TRADERS",
            })

            # Calcular y actualizar capital actual
            # Usar capital on-chain si está disponible, de lo contrario calcular desde PnL
            if current_capital_onchain is not None:
                self.current_capital = current_capital_onchain
            elif self.initial_capital is not None:
                self.current_capital = self.initial_capital + total_pnl
            else:
                self.current_capital = None

            if self.current_capital is not None:
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
                    "timestamp": current_timestamp,
                    "metric_name": "Capital_Current",
                    "metric_value": float(self.current_capital),
                    "trader": "ALL_TRADERS",
                })

                # Agregar métrica de Drawdown_Total
                metrics.append({
                    "timestamp": current_timestamp,
                    "metric_name": "Drawdown_Total",
                    "metric_value": float(drawdown_total),
                    "trader": "ALL_TRADERS",
                })

        # Poda de memoria: solo mantener traders que vienen en el snapshot (alineado con BD)
        for key in list(self.cumulative_pnl_by_trader.keys()):
            if key == "ALL_TRADERS":
                continue
            if key not in keys_in_snapshot:
                self.cumulative_pnl_by_trader.pop(key, None)
                self.max_capital_by_trader.pop(key, None)
                self._last_seen_by_trader.pop(key, None)

        # Poda opcional por TTL: eliminar traders inactivos hace más de N días
        if self._max_trader_idle_days is not None and self._max_trader_idle_days > 0:
            cutoff = current_timestamp - timedelta(days=self._max_trader_idle_days)
            for key in list(self.cumulative_pnl_by_trader.keys()):
                if key == "ALL_TRADERS":
                    continue
                last_seen = self._last_seen_by_trader.get(key)
                if last_seen is not None and last_seen < cutoff:
                    self.cumulative_pnl_by_trader.pop(key, None)
                    self.max_capital_by_trader.pop(key, None)
                    self._last_seen_by_trader.pop(key, None)
                    self._logger.debug(f"Trader {key[:8]}... podado por TTL ({self._max_trader_idle_days} días)")

        self._logger.debug(
            f"Procesado snapshot de {len(pnl_data)} traders, "
            f"generadas {len(metrics)} métricas"
        )

        return metrics

    def get_current_metrics(
        self,
        *,
        current_timestamp: Optional[datetime] = None,
        current_capital_onchain: Optional[Decimal] = None,
    ) -> List[Dict[str, Any]]:
        """
        Genera métricas actuales con los valores acumulados más recientes.

        Args:
            current_timestamp: Timestamp a usar (por defecto datetime.now())
            current_capital_onchain: Capital actual obtenido on-chain (balance SOL de la wallet)

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

        # Calcular y agregar métrica de Capital_Current
        # Usar capital on-chain si está disponible, de lo contrario calcular desde PnL
        if current_capital_onchain is not None:
            self.current_capital = current_capital_onchain
        elif self.initial_capital is not None:
            self.current_capital = self.initial_capital + total_pnl
        else:
            self.current_capital = None

        if self.current_capital is not None:
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

                # Calcular drawdown individual
                # El drawdown se calcula desde el máximo entre 0 y el máximo histórico del trader
                # - Si el trader ha tenido ganancias: drawdown desde el máximo histórico
                # - Si el trader nunca ha tenido ganancias: drawdown desde 0 (pérdidas desde inicio)
                max_trader_pnl = self.max_capital_by_trader[trader]
                reference_point = max(Decimal("0.0"), max_trader_pnl)
                drawdown_individual = reference_point - pnl

                # Solo generar métrica si hay drawdown (diferencia positiva)
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
            Capital actual (ya calculado desde on-chain o PnL) o None si no hay capital
        """
        return self.current_capital
