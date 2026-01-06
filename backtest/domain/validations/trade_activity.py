# -*- coding: utf-8 -*-
"""
Validación de actividad de trading con ventana de tiempo
"""
from typing import Dict, Any

from .models import BaseValidation, ValidationResult
from ..entities.transactions import SwapTransaction


class TradeActivityValidation(BaseValidation):
    """Validación de actividad de trading con ventana de tiempo"""

    def __init__(self,
                    min_trade_count_threshold: int = 3,
                    activity_window_seconds: int = 60,
                    enabled: bool = True):
        """
        Args:
            min_trade_count_threshold: Número mínimo de trades requeridos
            activity_window_seconds: Ventana de tiempo en segundos
            enabled: Si True, la validación está activa
        """
        super().__init__(enabled)
        self.min_trade_count_threshold = min_trade_count_threshold
        self.activity_window_seconds = activity_window_seconds

    @property
    def name(self) -> str:
        return "trade_activity"

    def validate(self, transaction: SwapTransaction, context: Dict[str, Any]) -> ValidationResult:
        """Valida la actividad de trading"""
        if not self.enabled:
            return ValidationResult(
                is_valid=True,
                validation_name=self.name,
                message="Validación deshabilitada"
            )

        if transaction.side == 'sell':
            return ValidationResult(
                is_valid=True,
                validation_name=self.name,
                message="Venta no requiere validación de actividad"
            )

        token_address = transaction.base_token_address

        # Obtener estado de actividad del contexto
        token_activity_state = context.get('token_activity_state', {})

        tx_timestamp = transaction.block_timestamp

        state = token_activity_state.get(token_address)

        # Si no hay estado, iniciar con count=1
        if not state:
            token_activity_state[token_address] = {
                "count": 1,
                "initial_ts": tx_timestamp
            }
            is_valid = 1 >= self.min_trade_count_threshold
            if not is_valid:
                self._record_rejection()
            self._logger.debug(f"[{self.name}] Nuevo token {token_address[:8]}... count=1 "
                                f"valid={is_valid} threshold={self.min_trade_count_threshold}")
            return ValidationResult(
                is_valid=is_valid,
                validation_name=self.name,
                message=f"Primer trade del token, count=1",
                details={
                    "count": 1,
                    "threshold": self.min_trade_count_threshold,
                    "is_first": True
                }
            )

        initial_ts = state.get("initial_ts")
        count = state.get("count", 0)

        if not initial_ts:
            token_activity_state[token_address] = {
                "count": 1,
                "initial_ts": tx_timestamp
            }
            is_valid = 1 >= self.min_trade_count_threshold
            if not is_valid:
                self._record_rejection()
            return ValidationResult(
                is_valid=is_valid,
                validation_name=self.name,
                message="Estado sin initial_ts, reseteado",
                details={"count": 1, "threshold": self.min_trade_count_threshold}
            )

        delta_seconds = (tx_timestamp - initial_ts).total_seconds()

        if delta_seconds <= self.activity_window_seconds:
            # Dentro de la ventana: incrementar count
            count += 1
            token_activity_state[token_address] = {
                "count": count,
                "initial_ts": initial_ts
            }
            is_valid = count >= self.min_trade_count_threshold
            if not is_valid:
                self._record_rejection()
            self._logger.debug(f"[{self.name}] Dentro ventana token={token_address[:8]}... "
                                f"delta={delta_seconds:.2f}s count={count}/{self.min_trade_count_threshold} "
                                f"valid={is_valid}")
            return ValidationResult(
                is_valid=is_valid,
                validation_name=self.name,
                message=f"Dentro de ventana, count={count}",
                details={
                    "count": count,
                    "threshold": self.min_trade_count_threshold,
                    "delta_seconds": delta_seconds,
                    "window_seconds": self.activity_window_seconds
                }
            )

        # Fuera de ventana: resetear estado
        token_activity_state[token_address] = {
            "count": 1,
            "initial_ts": tx_timestamp
        }
        is_valid = 1 >= self.min_trade_count_threshold
        if not is_valid:
            self._record_rejection()
        self._logger.debug(f"[{self.name}] Fuera ventana token={token_address[:8]}... "
                            f"delta={delta_seconds:.2f}s reset count=1 valid={is_valid}")
        return ValidationResult(
            is_valid=is_valid,
            validation_name=self.name,
            message=f"Fuera de ventana, reseteado a count=1",
            details={
                "count": 1,
                "threshold": self.min_trade_count_threshold,
                "delta_seconds": delta_seconds,
                "window_seconds": self.activity_window_seconds,
                "was_reset": True
            }
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Retorna las métricas de esta validación"""
        base_metrics = super().get_metrics()
        base_metrics.update({
            'min_trade_count_threshold': self.min_trade_count_threshold,
            'activity_window_seconds': self.activity_window_seconds
        })
        return base_metrics
