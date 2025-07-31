# -*- coding: utf-8 -*-
"""
Módulo PumpFun - Herramientas para interactuar con Pump.fun
Incluye análisis de tokens, monitoreo de precios y trading
"""

from .pump_price_fetcher import PumpFunPriceFetcher, PumpTokenPrice, PumpCurveState
from .transactions import PumpFunTransactions
from .token_creator import PumpFunTokenCreator, TokenMetadata
from .wallet_manager import PumpFunWalletManager, WalletData, PumpFunWalletCreator, PumpFunWalletStorage
from .subscriptions import PumpFunSubscriptions
from .api_client import PumpFunApiClient, ApiType, RequestMethod
from .pumpfun_trade_analyzer import (
    PumpFunTradeAnalyzer,
    TokenBalanceInfo,
    InstructionAnalysis,
    BalanceChangeInfo,
    TradeAnalysisResult
)

__all__ = [
    # Funcionalidades originales
    'PumpFunPriceFetcher',
    'PumpTokenPrice', 
    'PumpCurveState',
    'PumpFunTransactions',
    'PumpFunTokenCreator',
    'TokenMetadata',
    'PumpFunWalletManager',
    'WalletData',
    'PumpFunWalletCreator',
    'PumpFunWalletStorage',
    'PumpFunSubscriptions',
    'PumpFunApiClient',
    'ApiType',
    'RequestMethod',
    'PumpFunTradeAnalyzer',
    'TokenBalanceInfo',
    'InstructionAnalysis',
    'BalanceChangeInfo',
    'TradeAnalysisResult'
]

__version__ = "2.3.0"
__author__ = "Mario Jesús Arias Hernández"
__description__ = "PumpFun integration with centralized API client, API key support for PumpSwap data, Lightning transactions and async transaction parser"
