# -*- coding: utf-8 -*-
"""
Entidades de dominio relacionadas con transacciones.

Contiene las entidades que representan transacciones de swap,
que son el input principal del sistema de backtest.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Literal
from datetime import datetime


@dataclass
class SwapTransaction:
    """
    Entidad de dominio: Representa una transacción de swap normalizada.
    
    Esta entidad es independiente de la fuente de datos (Moralis, BitQuery, etc.)
    y proporciona una estructura unificada para trabajar con transacciones de swap.
    Es el objeto principal que se procesa durante el backtest.
    """
    # Identificación
    signature: str  # Hash/ID único de la transacción
    block_number: int
    block_timestamp: datetime

    # Tipo de operación
    side: Literal['buy', 'sell']  # Tipo de operación: compra o venta

    # Token base (el que se está tradeando)
    base_token_address: str  # Dirección del token base
    base_token_symbol: str  # Símbolo del token base

    # Cantidades
    sol_amount: Decimal  # Cantidad de SOL involucrada
    token_amount: Decimal  # Cantidad de tokens involucrada

    # Exchange/Pool
    exchange_address: Optional[str] = None  # Dirección del programa del exchange
    exchange_name: Optional[str] = None  # Nombre interno normalizado
    native_exchange_name: Optional[str] = None  # Nombre original del exchange según la fuente

    # Metadatos adicionales (opcional, para compatibilidad y debugging)
    source: Optional[str] = None  # 'moralis', 'bitquery', 'system', etc.
    raw_data: Optional[dict] = None  # Datos originales para debugging/validación

    def __repr__(self):
        exchange_display = (
            self.exchange_name 
            or self.native_exchange_name 
            or self.exchange_address 
            or 'N/A'
        )
        return (f"SwapTransaction(signature={self.signature[:8]}..., "
                f"side={self.side}, token={self.base_token_symbol}, "
                f"sol={float(self.sol_amount):.6f}, "
                f"tokens={float(self.token_amount):.6f}, "
                f"exchange={exchange_display}, "
                f"source={self.source or 'unknown'})")
