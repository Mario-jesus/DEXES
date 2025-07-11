# -*- coding: utf-8 -*-
"""
Copy Trading Mini - Sistema simplificado de copy trading para Pump.fun
Integración directa con solana_manager y pumpfun

Componentes principales:
- CopyTradingMini: Sistema principal
- CopyTradingCallback: Callback para replicación automática
- ValidationEngine: Motor de validaciones
- PositionQueue: Cola de posiciones FIFO
- CopyTradingLogger: Sistema de logging estructurado
"""

from .core import CopyTrading
from .callback import CopyTradingCallback
from .validation import ValidationEngine
from .position_queue import PositionQueue
from .logger import CopyTradingLogger
from .config import CopyTradingConfig, AmountMode, TransactionType, TraderConfig

print("🎯 Módulo Copy Trading Mini cargado")
print("🚀 Sistema simplificado de copy trading")
print("   ✅ Integración directa con PumpFun")
print("   ✅ Replicación automática de trades")
print("   ✅ Gestión de posiciones FIFO")
print("   ✅ Validaciones configurables")
print("   ✅ Logging estructurado")
print("   ✅ Soporte Lightning y Local Trade")

__all__ = [
    'CopyTrading',
    'CopyTradingCallback',
    'ValidationEngine',
    'PositionQueue',
    'CopyTradingLogger',
    'CopyTradingConfig',
    'AmountMode',
    'TransactionType',
    'TraderConfig'
]

__version__ = "1.0.0"
__author__ = "DEXES Team"
__description__ = "Simplified copy trading system for Pump.fun with automatic trade replication"
