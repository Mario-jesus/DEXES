# -*- coding: utf-8 -*-
"""
Validación de pools/exchanges permitidos
"""
from typing import Dict, List, Optional, Any

from .models import BaseValidation, ValidationResult
from ..entities.transactions import SwapTransaction
from ..services.exchange_registry import get_internal_name_by_address


class AllowedPoolsValidation(BaseValidation):
    """Validación que permite solo transacciones de pools/exchanges específicos"""

    def __init__(self, 
                    allowed_pools: Optional[List[str]] = None,
                    enabled: bool = True):
        """
        Args:
            allowed_pools: Lista de nombres de pools/exchanges permitidos
            enabled: Si True, la validación está activa
        """
        super().__init__(enabled)
        self.allowed_pools = allowed_pools or []
        # Normalizar a minúsculas para comparación case-insensitive
        self._allowed_pools_lower = [pool.lower().strip() for pool in self.allowed_pools if pool]

    @property
    def name(self) -> str:
        return "allowed_pools"

    def _is_pool_allowed(self, exchange_address: Optional[str], exchange_name: Optional[str]) -> bool:
        """
        Verifica si un pool/exchange está en la lista de permitidos.
        
        Busca primero por nombre interno, luego por dirección si no encuentra.
        
        Args:
            exchange_address: Dirección del programa del exchange
            exchange_name: Nombre interno normalizado del exchange
        
        Returns:
            True si el exchange está permitido, False en caso contrario
        """
        if not self.allowed_pools:
            # Si no hay pools permitidos configurados, rechazar todas
            return False

        # Prioridad 1: Buscar por nombre interno
        if exchange_name:
            exchange_normalized = exchange_name.strip().lower()
            # Verificar coincidencia exacta (case-insensitive)
            if exchange_normalized in self._allowed_pools_lower:
                return True

        # Prioridad 2: Si hay dirección, obtener nombre interno y buscar
        if exchange_address:
            internal_name = get_internal_name_by_address(exchange_address)
            if internal_name and internal_name.lower() in self._allowed_pools_lower:
                return True

        return False

    def validate(self, transaction: SwapTransaction, context: Dict[str, Any]) -> ValidationResult:
        """Valida que el pool/exchange esté en la lista de permitidos"""
        if not self.enabled:
            return ValidationResult(
                is_valid=True,
                validation_name=self.name,
                message="Validación deshabilitada"
            )

        if transaction.side == 'sell':
            # Las ventas no se validan por pool permitido
            return ValidationResult(
                is_valid=True,
                validation_name=self.name,
                message="Venta no requiere validación de pool permitido"
            )

        # Usar dirección y nombre interno para verificar si está permitido
        is_allowed = self._is_pool_allowed(
            exchange_address=transaction.exchange_address,
            exchange_name=transaction.exchange_name
        )

        # Para mensajes de log, usar nombre interno o dirección
        exchange_display = transaction.exchange_name or transaction.exchange_address or 'Unknown'

        if is_allowed:
            self._logger.debug(f"[{self.name}] OK: exchange '{exchange_display}' está permitido "
                                f"tx={transaction.signature[:10]}")
        else:
            self._record_rejection()
            self._logger.debug(f"[{self.name}] FALLO: exchange '{exchange_display}' no está en lista permitida "
                                f"tx={transaction.signature[:10]}")

        return ValidationResult(
            is_valid=is_allowed,
            validation_name=self.name,
            message=f"Exchange '{exchange_display}' {'está permitido' if is_allowed else 'no está en la lista de permitidos'}",
            details={
                "exchange": exchange_display,
                "exchange_address": transaction.exchange_address,
                "allowed_pools": self.allowed_pools.copy(),
                "is_allowed": is_allowed
            }
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Retorna las métricas de esta validación"""
        base_metrics = super().get_metrics()
        base_metrics.update({
            'allowed_pools': self.allowed_pools.copy()
        })
        return base_metrics
