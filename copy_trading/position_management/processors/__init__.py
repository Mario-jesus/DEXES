# -*- coding: utf-8 -*-
"""
Procesadores para Copy Trading.
"""
from .position_closure_processor import PositionClosureProcessor
from .trade_analysis_processor import TradeAnalysisProcessor
from .dry_run_analysis_processor import DryRunAnalysisProcessor
from .protocols import AnalysisProcessorProtocol

__all__ = [
    'PositionClosureProcessor',
    'TradeAnalysisProcessor',
    'DryRunAnalysisProcessor',
    'AnalysisProcessorProtocol'
]
