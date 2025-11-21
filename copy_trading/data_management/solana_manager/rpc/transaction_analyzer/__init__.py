# -*- coding: utf-8 -*-
"""
Paquete de análisis de transacciones de Solana.

Este paquete contiene módulos especializados para diferentes aspectos del análisis:
- analyzer: Clase principal orquestadora
- balance_parser: Parsing de balances de tokens
- transaction_extractor: Extracción de datos de transacciones
- transaction_detector: Detección de características (op_type, errors)
- counterparty_detector: Detección de contrapartes (bonding curves y AMMs)
- transaction_calculator: Cálculos de métricas financieras
"""
from .analyzer import SolanaTxAnalyzer
from .balance_parser import BalanceParser

__all__ = [
    'SolanaTxAnalyzer',
    'BalanceParser',
]
