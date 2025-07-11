# -*- coding: utf-8 -*-
"""
Módulo PumpFun - Herramientas para interactuar con Pump.fun
Incluye análisis de tokens, monitoreo de precios y trading
"""

# Importaciones originales
from .pump_price_fetcher import PumpFunPriceFetcher, PumpTokenPrice, PumpCurveState
from .transactions import PumpFunTransactions
from .token_creator import PumpFunTokenCreator, TokenMetadata
from .wallet_manager import PumpFunWalletManager, WalletData, PumpFunWalletCreator, PumpFunWalletStorage
from .subscriptions import PumpFunSubscriptions
from .api_client import PumpFunApiClient, ApiType, RequestMethod

# Importaciones del nuevo parser de transacciones
from .transaction_parser import PumpFunTransactionParser, PumpFunTradeInfo

print("🎯 Módulo PumpFun cargado")
print("🚀 Funcionalidades disponibles:")
print("   - Fetcher de precios directo de bonding curve")
print("   - Análisis de estado de curve")
print("   - Cálculo de progreso de bonding")
print("   - Precios en tiempo real desde Pump.fun")
print("   - Cliente API centralizado con WebSocket y HTTP")
print("   - Trading con APIs Lightning y Local")
print("   - Gestión de wallets Lightning")
print("   - Creación de tokens")
print("   - Soporte para API key en WebSocket (PumpSwap data)")
print("   - Parser asíncrono de transacciones de Pump.fun")
print("   - Análisis de actividad de traders")
print("   - Patrón Singleton y Context Manager")

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
    
    # Nuevas funcionalidades del parser
    'PumpFunTransactionParser',
    'PumpFunTradeInfo'
]

__version__ = "2.3.0"
__author__ = "Mario Jesús Arias Hernández"
__description__ = "PumpFun integration with centralized API client, API key support for PumpSwap data, Lightning transactions and async transaction parser"
