# -*- coding: utf-8 -*-
"""
Validación de monto máximo de SOL por exchange
"""
from typing import Dict, Optional, Any
from decimal import Decimal

from .models import BaseValidation, ValidationResult
from ..entities.transactions import SwapTransaction
from ..services.exchange_registry import get_internal_name_by_address


class MaxSolAmountValidation(BaseValidation):
    """Validación de monto máximo de SOL por exchange"""

    def __init__(self, 
                    exchange_thresholds: Optional[Dict[str, str]] = None,
                    enabled: bool = True):
        """
        Args:
            exchange_thresholds: Diccionario con umbrales máximos por exchange
            enabled: Si True, la validación está activa
        """
        super().__init__(enabled)
        self.exchange_thresholds = exchange_thresholds or {}

    @property
    def name(self) -> str:
        return "max_sol_amount"

    def _get_threshold(self, exchange_address: Optional[str], exchange_name: Optional[str]) -> Optional[str]:
        """
        Obtiene el umbral máximo para un exchange.
        
        Busca primero por nombre interno, luego por dirección si no encuentra.
        """
        # Prioridad 1: Buscar por nombre interno
        if exchange_name:
            exchange_normalized = exchange_name.strip()
            # Coincidencia exacta
            if exchange_normalized in self.exchange_thresholds:
                return self.exchange_thresholds[exchange_normalized]
            # Coincidencia case-insensitive
            exchange_lower = exchange_normalized.lower()
            for key, threshold in self.exchange_thresholds.items():
                if key.lower() == exchange_lower:
                    return threshold

        # Prioridad 2: Si hay dirección, obtener nombre interno y buscar
        if exchange_address:
            internal_name = get_internal_name_by_address(exchange_address)
            if internal_name and internal_name in self.exchange_thresholds:
                return self.exchange_thresholds[internal_name]

        return None

    def validate(self, transaction: SwapTransaction, context: Dict[str, Any]) -> ValidationResult:
        """Valida el monto máximo de SOL"""
        if not self.enabled:
            return ValidationResult(
                is_valid=True,
                validation_name=self.name,
                message="Validación deshabilitada"
            )

        if transaction.side == 'sell':
            # Las ventas no se validan por monto máximo
            return ValidationResult(
                is_valid=True,
                validation_name=self.name,
                message="Venta no requiere validación de monto máximo"
            )

        # Usar dirección y nombre interno para buscar el umbral
        threshold = self._get_threshold(
            exchange_address=transaction.exchange_address,
            exchange_name=transaction.exchange_name
        )

        # Para mensajes de log, usar nombre interno o dirección
        exchange_display = transaction.exchange_name or transaction.exchange_address or 'Unknown'

        if threshold is None:
            return ValidationResult(
                is_valid=True,
                validation_name=self.name,
                message=f"No hay umbral configurado para exchange '{exchange_display}'"
            )

        sol_amount = transaction.sol_amount
        threshold_decimal = Decimal(str(threshold))
        is_valid = sol_amount <= threshold_decimal

        if is_valid:
            self._logger.debug(f"[{self.name}] OK: {sol_amount} <= {threshold_decimal} "
                                f"exchange={exchange_display} tx={transaction.signature[:10]}")
        else:
            self._record_rejection()
            self._logger.debug(f"[{self.name}] FALLO: {sol_amount} > {threshold_decimal} "
                                f"exchange={exchange_display} tx={transaction.signature[:10]}")

        return ValidationResult(
            is_valid=is_valid,
            validation_name=self.name,
            message=f"Monto {sol_amount} {'<=' if is_valid else '>'} umbral {threshold_decimal}",
            details={
                "sol_amount": float(sol_amount),
                "threshold": threshold,
                "exchange": exchange_display,
                "exchange_address": transaction.exchange_address
            }
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Retorna las métricas de esta validación"""
        base_metrics = super().get_metrics()
        base_metrics.update({
            'exchange_thresholds': self.exchange_thresholds.copy()
        })
        return base_metrics
