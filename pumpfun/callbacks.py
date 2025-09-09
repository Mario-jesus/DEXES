# -*- coding: utf-8 -*-
"""
PumpFun Callbacks - Funciones de callback para procesar eventos de PumpPortal
Proporciona funciones para formatear y mostrar diferentes tipos de eventos.
"""
from typing import Dict, Any, Final, Callable
import time
from datetime import datetime


def format_address(address: str, chars: int = 8) -> str:
    """Formatea una dirección para mostrar solo el inicio y final"""
    if len(address) <= chars * 2:
        return address
    return f"{address[:chars]}...{address[-chars:]}"


def format_sol_amount(amount: float) -> str:
    """Formatea un monto en SOL con el símbolo"""
    return f"{amount:.6f}"


def format_timestamp(timestamp: float) -> str:
    """Formatea un timestamp en fecha/hora legible"""
    dt = datetime.fromtimestamp(timestamp / 1000)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_market_cap(market_cap: float) -> str:
    """Formatea el market cap en SOL"""
    if market_cap >= 1000:
        return f"{market_cap/1000:.2f}K"
    return f"{market_cap:.2f}"


def print_separator(char: str = "═", length: int = 50) -> None:
    """Imprime una línea separadora"""
    print(f"\n{''.join([char for _ in range(length)])}\n")


def print_trade_event(data: Dict[str, Any]) -> None:
    """
    Procesa y muestra eventos de trading
    
    Args:
        data: Datos del evento de trading
    """
    # Extraer datos con valores por defecto
    tx_type = data.get('txType', 'unknown').lower()
    mint = data.get('mint', 'N/A')
    trader = data.get('traderPublicKey', data.get('user', 'N/A'))
    sol_amount = data.get('solAmount', 0)
    token_amount = data.get('tokenAmount', 0)
    timestamp = data.get('timestamp', time.time() * 1000)
    market_cap = data.get('marketCapSol', 0)
    signature = data.get('signature', 'N/A')

    # Determinar emoji y texto según tipo
    type_info = {
        'buy': ('🟢', 'COMPRA'),
        'sell': ('🔴', 'VENTA'),
        'create': ('🆕', 'CREACIÓN'),
        'migrate': ('🔄', 'MIGRACIÓN'),
    }.get(tx_type, ('🔵', tx_type.upper()))

    print(f"""
🎯═══════════════════════════════════════🎯
{type_info[0]} Tipo: {type_info[1]}
👤 Usuario: {format_address(trader)}
🪙 Token: {format_address(mint)}
💰 SOL: {format_sol_amount(sol_amount)}
🎲 Tokens: {token_amount:,.6f}
⏰ Timestamp: {format_timestamp(timestamp)}
📈 Market Cap: {format_market_cap(market_cap)}
📝 Signature: {format_address(signature)}
🎯═══════════════════════════════════════🎯
""")


def print_new_token_event(data: Dict[str, Any]) -> None:
    """
    Procesa y muestra eventos de creación de tokens
    
    Args:
        data: Datos del evento de nuevo token
    """
    # Extraer datos específicos de creación
    name = data.get('name', 'N/A')
    symbol = data.get('symbol', 'N/A')
    mint = data.get('mint', 'N/A')
    initial_buy = data.get('initialBuy', 0)
    sol_amount = data.get('solAmount', 0)
    market_cap = data.get('marketCapSol', 0)
    creator = data.get('traderPublicKey', 'N/A')

    print(f"""
✨═══════════════════════════════════════✨
🆕 NUEVO TOKEN CREADO
📛 Nombre: {name}
💎 Símbolo: {symbol}
🏦 Mint: {format_address(mint)}
👤 Creador: {format_address(creator)}
💫 Compra Inicial: {initial_buy:,.6f} tokens
💰 SOL Inicial: {format_sol_amount(sol_amount)}
📈 Market Cap: {format_market_cap(market_cap)}
✨═══════════════════════════════════════✨
""")


def print_migration_event(data: Dict[str, Any]) -> None:
    """
    Procesa y muestra eventos de migración
    
    Args:
        data: Datos del evento de migración
    """
    # Extraer datos específicos de migración
    old_mint = data.get('oldMint', 'N/A')
    new_mint = data.get('newMint', 'N/A')
    migrator = data.get('traderPublicKey', 'N/A')
    timestamp = data.get('timestamp', time.time() * 1000)

    print(f"""
🔄═══════════════════════════════════════🔄
♻️ MIGRACIÓN DE TOKEN
📤 Token Original: {format_address(old_mint)}
📥 Nuevo Token: {format_address(new_mint)}
👤 Migrador: {format_address(migrator)}
⏰ Timestamp: {format_timestamp(timestamp)}
🔄═══════════════════════════════════════🔄
""")


def default_callback(data: Dict[str, Any]) -> None:
    """
    Callback por defecto para eventos no manejados
    
    Args:
        data: Datos del evento
    """
    event_type = data.get('method', 'unknown')
    print(f"""
❓═══════════════════════════════════════❓
⚠️ EVENTO NO MANEJADO: {event_type}
📦 Datos: {data}
❓═══════════════════════════════════════❓
""")


# Mapa de callbacks por tipo de evento
EVENT_CALLBACKS: Final[Dict[str, Callable[[Dict[str, Any]], None]]] = {
    'subscribeTokenTrade': print_trade_event,
    'subscribeAccountTrade': print_trade_event,
    'subscribeNewToken': print_new_token_event,
    'subscribeMigration': print_migration_event,
    'default': default_callback
}
