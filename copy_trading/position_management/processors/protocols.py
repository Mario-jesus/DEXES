# -*- coding: utf-8 -*-
"""
Protocol para procesadores de análisis en Copy Trading.
Define la interfaz común entre implementaciones reales y simuladas (Dry Run).
"""
from __future__ import annotations

from typing import Protocol, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Position
    from ...data_management.models import TransactionAnalysis


class AnalysisProcessorProtocol(Protocol):
    """
    Protocol para procesadores de análisis de transacciones.
    
    Implementaciones:
        - TradeAnalysisProcessor (real, analiza tx on-chain)
        - DryRunAnalysisProcessor (simulado, calcula con Moralis)
    """

    async def analyze_position(
        self,
        position: "Position"
    ) -> Tuple[bool, Optional["TransactionAnalysis"]]:
        """
        Analiza una posición de trading.
        
        Args:
            position: La posición a analizar
            
        Returns:
            Tuple de (success, analysis_result)
        """
        ...

