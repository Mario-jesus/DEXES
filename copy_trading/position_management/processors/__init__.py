# -*- coding: utf-8 -*-
"""
Procesadores para Copy Trading.
"""
from .position_closure_processor import PositionClosureProcessor
from .trade_analysis_processor import TradeAnalysisProcessor

__all__ = [
    'PositionClosureProcessor',
    'TradeAnalysisProcessor'
]
