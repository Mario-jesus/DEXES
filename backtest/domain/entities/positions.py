# -*- coding: utf-8 -*-
"""
Entidades de dominio relacionadas con posiciones y trades.

Contiene las entidades que representan posiciones abiertas y trades cerrados
en el sistema de backtest.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class Position:
    """
    Entidad de dominio: Representa una posición abierta (compra de tokens).
    
    Una posición se crea cuando se ejecuta una transacción de compra (buy)
    y permanece abierta hasta que se venden todos los tokens.
    """
    token_address: str
    token_symbol: str
    buy_hash: str
    buy_timestamp: str
    buy_block: int
    original_sol_invested: Decimal  # SOL invertido originalmente
    original_token_amount: Decimal  # Cantidad de tokens comprados originalmente
    remaining_sol_invested: Decimal  # SOL invertido restante
    remaining_token_amount: Decimal  # Cantidad de tokens restante
    exchange_address: Optional[str] = None  # Dirección del programa del exchange
    exchange_name: Optional[str] = None  # Nombre interno normalizado

    def __repr__(self):
        exchange_display = self.exchange_name or self.exchange_address or 'Unknown'
        return (f"Position({self.token_symbol}, buy={self.buy_hash[:8]}..., "
                f"original_sol={float(self.original_sol_invested):.6f}, "
                f"original_tokens={float(self.original_token_amount):.6f}, "
                f"remaining_sol={float(self.remaining_sol_invested):.6f}, "
                f"remaining_tokens={float(self.remaining_token_amount):.6f}, "
                f"exchange={exchange_display})")


@dataclass
class ClosedTrade:
    """
    Entidad de dominio: Representa un trade cerrado (buy + sell matched).
    
    Se crea cuando se empareja una compra con una venta usando estrategia FIFO.
    Puede representar el cierre completo o parcial de una posición.
    """
    token_address: str
    token_symbol: str
    buy_hash: str
    sell_hash: str
    buy_timestamp: str
    sell_timestamp: str
    buy_block: int
    sell_block: int
    original_sol_invested: Decimal  # SOL invertido original de la posición
    original_token_amount: Decimal  # Cantidad de tokens original de la posición
    sol_invested: Decimal  # SOL invertido proporcional de esta venta
    sol_recovered: Decimal  # SOL recuperado en esta venta
    token_amount_sold: Decimal  # Cantidad de tokens vendidos en esta venta
    profit_loss_sol: Decimal
    profit_loss_pct: Decimal
    duration_seconds: Optional[int] = None
    exchange_address: Optional[str] = None  # Dirección del programa del exchange
    exchange_name: Optional[str] = None  # Nombre interno normalizado

    def __repr__(self):
        pnl_sign = "+" if self.profit_loss_sol >= 0 else ""
        exchange_display = self.exchange_name or self.exchange_address or 'Unknown'
        return (f"ClosedTrade({self.token_symbol}, "
                f"original_sol={float(self.original_sol_invested):.6f}, "
                f"original_tokens={float(self.original_token_amount):.6f}, "
                f"SOL invested={float(self.sol_invested):.6f}, "
                f"SOL recovered={float(self.sol_recovered):.6f}, "
                f"tokens sold={float(self.token_amount_sold):.6f}, "
                f"PnL={pnl_sign}{float(self.profit_loss_sol):.6f} SOL "
                f"({pnl_sign}{float(self.profit_loss_pct):.2f}%), "
                f"exchange={exchange_display})")
