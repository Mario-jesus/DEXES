# -*- coding: utf-8 -*-
"""
Protocol para ejecutores de transacciones en Copy Trading.
Define la interfaz común entre implementaciones reales y simuladas (Dry Run).
"""
from __future__ import annotations

from typing import Protocol, Tuple, Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..position_management.models import PositionTraderTradeData
    from ..position_management.managers.position_queue_manager import PositionQueueManager


class TransactionExecutorProtocol(Protocol):
    """
    Protocol para ejecutores de transacciones.
    
    Implementaciones:
        - TransactionExecutor (real, ejecuta on-chain)
        - DryRunTransactionExecutor (simulado, calcula con Moralis)
    """

    async def execute_trade(
        self,
        trade_data: "PositionTraderTradeData"
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Ejecuta (o simula) un trade.
        
        Args:
            trade_data: Datos del trade a ejecutar
            
        Returns:
            Tuple de (success, signature, error_message)
        """
        ...

    def get_transaction_type_info(self) -> Dict[str, Any]:
        """
        Obtiene información sobre el tipo de transacción/modo.
        
        Returns:
            Dict con información del ejecutor
        """
        ...


class LiquidationsProtocol(Protocol):
    """
    Protocol para sistemas de liquidaciones.
    
    Implementaciones:
        - Liquidations (real, obtiene balances on-chain)
        - DryRunLiquidations (simulado, obtiene balances de OpenPositionQueue)
    """

    async def run(self) -> None:
        """
        Ejecuta el proceso de liquidación.
        
        Obtiene balances de tokens y liquida aquellos con balance >= 1.
        """
        ...

    async def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas del sistema de liquidaciones.
        
        Returns:
            Dict con estadísticas del sistema
        """
        ...
