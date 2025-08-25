# -*- coding: utf-8 -*-
"""
Models for the analysis.
"""
from typing import Optional, Literal, NamedTuple


class ProcessedAnalysisResult(NamedTuple):
    """
    Resultado del procesamiento de análisis de una posición.
    """
    success: bool
    error_kind: Optional[Literal["slippage", "insufficient_tokens", "insufficient_lamports", "transaction_not_found", "insufficient_funds_for_rent", "unknown"]]
    error_message: Optional[str]
