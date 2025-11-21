# -*- coding: utf-8 -*-
"""
Utilidades para el cliente RPC de Solana.
"""
from typing import Optional
from decimal import Decimal, ROUND_DOWN, getcontext
from typing_extensions import Literal

getcontext().prec = 26


def lamports_to_sol_str(lamports: int) -> str:
    """Convierte lamports a SOL como string formateado.
    
    Args:
        lamports: Cantidad en lamports
        
    Returns:
        String con el balance en SOL formateado
    """
    sol = (Decimal(lamports) / Decimal(1_000_000_000)).quantize(
        Decimal("0.000000001"), rounding=ROUND_DOWN
    ).normalize()
    return format(sol, "f")


def calculate_price_sol_per_token(amount_sol: str, amount_tokens: str) -> Optional[str]:
    """
    Calcula el precio de SOL por token basado en los deltas.
    Siempre retorna un valor absoluto (positivo).
    
    Args:
        amount_sol: Cantidad de SOL
        amount_tokens: Cantidad de tokens

    Returns:
        Precio de SOL por token
    """
    try:
        amount_sol_dec = Decimal(amount_sol)
        amount_tokens_dec = Decimal(amount_tokens)
        if amount_sol_dec == 0 or amount_tokens_dec == 0:
            return None
        price = abs(amount_sol_dec) / abs(amount_tokens_dec)
        return format(price.quantize(Decimal("0.000000000000001"), rounding=ROUND_DOWN).normalize(), "f")
    except Exception:
        return None
