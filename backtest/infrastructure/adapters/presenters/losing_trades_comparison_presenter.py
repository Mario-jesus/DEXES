# -*- coding: utf-8 -*-
"""
Presentador de comparación de trades con pérdidas del sistema.

Formatea y muestra la comparación trade por trade de los trades donde el sistema
tuvo pérdidas contra los mismos trades del trader, con métricas porcentuales.
"""
from decimal import Decimal
from typing import Dict, Optional

from ....domain.entities.backtest_statistics import BacktestStats
from ....domain.entities.positions import ClosedTrade


def _out(s: str, lines: list[str] | None) -> None:
    """Emit line: append to list or print."""
    if lines is not None:
        lines.append(s)
    else:
        print(s)


def show_losing_trades_comparison(
    trader_stats: BacktestStats, system_stats: BacktestStats, return_string: bool = False
) -> str | None:
    """
    Muestra la comparación trade por trade de los trades con pérdidas del sistema.
    
    Los datos ya deben estar filtrados y emparejados por token_address.
    Compara cada trade del sistema que tuvo pérdidas con el trade correspondiente
    del trader, mostrando métricas porcentuales.
    
    Args:
        trader_stats: BacktestStats del trader (repositorio pumpportal) - trades emparejados
        system_stats: BacktestStats del sistema (repositorio system) - solo trades con pérdidas
        return_string: Si True, devuelve el texto formateado en lugar de imprimirlo.
            Por defecto False (imprime en consola).
    
    Returns:
        Si return_string es True, el string con el reporte; si no, None.
    """
    # Validar que hay trades
    if not system_stats.closed_trades:
        msg = "⚠️  No hay trades en el sistema para comparar"
        if return_string:
            return msg
        print(msg)
        return None

    if not trader_stats.closed_trades:
        msg = "⚠️  No hay trades en el trader para comparar"
        if return_string:
            return msg
        print(msg)
        return None

    # Filtrar trades con pérdidas del sistema
    system_losing_trades = [t for t in system_stats.closed_trades if t.profit_loss_sol < 0]

    if not system_losing_trades:
        msg = "\n✅ El sistema no tuvo trades con pérdidas para comparar"
        if return_string:
            return msg
        print(msg)
        return None

    lines: list[str] | None = [] if return_string else None

    # Crear diccionario de trades del trader por token_address para búsqueda rápida
    trader_trades_by_token: Dict[str, ClosedTrade] = {}
    for trade in trader_stats.closed_trades:
        trader_trades_by_token[trade.token_address.lower()] = trade

    _out("\n" + "=" * 120, lines)
    _out("COMPARACIÓN TRADE POR TRADE: TRADES CON PÉRDIDAS DEL SISTEMA", lines)
    _out("=" * 120, lines)
    _out(f"\n📉 Total de trades con pérdidas en el sistema: {len(system_losing_trades)}", lines)

    # Tabla de comparación trade por trade
    _out(f"\n{'=' * 120}", lines)
    _out(f"{'Token':<15} {'Trader PnL %':<18} {'Sistema PnL %':<18} {'Diferencia %':<18} "
            f"{'Trader ROI %':<18} {'Sistema ROI %':<18} {'Mejor':<10}", lines)
    _out(f"{'-' * 120}", lines)

    matched_count = 0
    trader_better_count = 0
    system_better_count = 0
    matched_system_trades = []
    matched_trader_trades_list = []

    for system_trade in system_losing_trades:
        trader_trade = trader_trades_by_token.get(system_trade.token_address.lower())

        if not trader_trade:
            # Trade del sistema sin match en trader
            token_display = system_trade.token_symbol[:14] if len(system_trade.token_symbol) > 14 else system_trade.token_symbol
            _out(f"{token_display:<15} {'N/A':<18} {float(system_trade.profit_loss_pct):>17.2f}% {'N/A':<18} "
                    f"{'N/A':<18} {_calculate_roi_percentage(system_trade):>17.2f}% {'N/A':<10}", lines)
            continue

        matched_count += 1
        matched_system_trades.append(system_trade)
        matched_trader_trades_list.append(trader_trade)

        # Calcular ROI porcentual para cada trade
        system_roi_pct = _calculate_roi_percentage(system_trade)
        trader_roi_pct = _calculate_roi_percentage(trader_trade)

        # Diferencia en PnL porcentual
        pnl_diff_pct = float(trader_trade.profit_loss_pct) - float(system_trade.profit_loss_pct)

        # Determinar quién tuvo mejor rendimiento
        better = ""
        if trader_trade.profit_loss_pct > system_trade.profit_loss_pct:
            better = "Trader ✅"
            trader_better_count += 1
        elif trader_trade.profit_loss_pct < system_trade.profit_loss_pct:
            better = "Sistema"
            system_better_count += 1
        else:
            better = "Igual"

        token_display = trader_trade.token_symbol[:14] if len(trader_trade.token_symbol) > 14 else trader_trade.token_symbol

        _out(f"{token_display:<15} {float(trader_trade.profit_loss_pct):>17.2f}% "
                f"{float(system_trade.profit_loss_pct):>17.2f}% {pnl_diff_pct:>+17.2f}% "
                f"{trader_roi_pct:>17.2f}% {system_roi_pct:>17.2f}% {better:<10}", lines)

    _out(f"{'=' * 120}", lines)

    # Resumen
    _out(f"\n📊 RESUMEN", lines)
    _out(f"{'-' * 120}", lines)
    _out(f"Total trades con pérdidas en sistema: {len(system_losing_trades)}", lines)
    _out(f"Trades emparejados: {matched_count}", lines)
    _out(f"Trades donde el trader fue mejor: {trader_better_count}", lines)
    _out(f"Trades donde el sistema fue mejor: {system_better_count}", lines)
    if matched_count > 0:
        trader_better_pct = (trader_better_count / matched_count) * 100
        _out(f"Porcentaje donde el trader fue mejor: {trader_better_pct:.2f}%", lines)

    # Comparación agregada
    _out(f"\n💰 COMPARACIÓN AGREGADA", lines)
    _out(f"{'-' * 120}", lines)

    if matched_count > 0:
        # Calcular métricas agregadas solo de los trades emparejados
        system_total_invested = sum(t.sol_invested for t in matched_system_trades)
        system_total_recovered = sum(t.sol_recovered for t in matched_system_trades)
        system_total_pnl = sum(t.profit_loss_sol for t in matched_system_trades)

        trader_total_invested = sum(t.sol_invested for t in matched_trader_trades_list)
        trader_total_recovered = sum(t.sol_recovered for t in matched_trader_trades_list)
        trader_total_pnl = sum(t.profit_loss_sol for t in matched_trader_trades_list)

        # ROI agregado
        system_aggregate_roi = (Decimal(system_total_recovered) / Decimal(system_total_invested) * Decimal('100')) if system_total_invested > 0 else Decimal('0')
        trader_aggregate_roi = (Decimal(trader_total_recovered) / Decimal(trader_total_invested) * Decimal('100')) if trader_total_invested > 0 else Decimal('0')

        # PnL promedio porcentual
        system_avg_pnl_pct = sum(float(t.profit_loss_pct) for t in matched_system_trades) / matched_count
        trader_avg_pnl_pct = sum(float(t.profit_loss_pct) for t in matched_trader_trades_list) / matched_count

        # Calcular winrate
        system_profitable_count = sum(1 for t in matched_system_trades if t.profit_loss_sol > 0)
        trader_profitable_count = sum(1 for t in matched_trader_trades_list if t.profit_loss_sol > 0)
        system_winrate = (system_profitable_count / matched_count * 100) if matched_count > 0 else 0
        trader_winrate = (trader_profitable_count / matched_count * 100) if matched_count > 0 else 0

        _out(f"{'Métrica':<35} {'Trader':>25} {'Sistema':>25} {'Diferencia':>25}", lines)
        _out(f"{'-' * 110}", lines)
        _out(f"{'PnL promedio (%):':<35} {trader_avg_pnl_pct:>24.2f}% {system_avg_pnl_pct:>24.2f}% {(trader_avg_pnl_pct - system_avg_pnl_pct):>+24.2f}%", lines)
        _out(f"{'ROI agregado (%):':<35} {float(trader_aggregate_roi):>24.2f}% {float(system_aggregate_roi):>24.2f}% {(float(trader_aggregate_roi) - float(system_aggregate_roi)):>+24.2f}%", lines)
        _out(f"{'Win Rate (%):':<35} {trader_winrate:>24.2f}% {system_winrate:>24.2f}% {(trader_winrate - system_winrate):>+24.2f}%", lines)
        _out(f"{'SOL invertido total:':<35} {float(trader_total_invested):>24.6f} {float(system_total_invested):>24.6f} {float(trader_total_invested - system_total_invested):>+24.6f}", lines)
        _out(f"{'SOL recuperado total:':<35} {float(trader_total_recovered):>24.6f} {float(system_total_recovered):>24.6f} {float(trader_total_recovered - system_total_recovered):>+24.6f}", lines)
        _out(f"{'PnL total (SOL):':<35} {float(trader_total_pnl):>24.6f} {float(system_total_pnl):>24.6f} {float(trader_total_pnl - system_total_pnl):>+24.6f}", lines)
        recovery_ratio_system = (float(system_total_recovered) / float(system_total_invested) * 100) if system_total_invested > 0 else 0
        recovery_ratio_trader = (float(trader_total_recovered) / float(trader_total_invested) * 100) if trader_total_invested > 0 else 0
        _out(f"{'Ratio recuperación (%):':<35} {recovery_ratio_trader:>24.2f}% {recovery_ratio_system:>24.2f}% {(recovery_ratio_trader - recovery_ratio_system):>+24.2f}%", lines)

    # Detalles trade por trade
    if matched_count > 0:
        _out(f"\n📋 DETALLES TRADE POR TRADE", lines)
        _out(f"{'=' * 120}", lines)

        for idx, (system_trade, trader_trade) in enumerate(zip(matched_system_trades, matched_trader_trades_list), 1):
            # Calcular precios de ejecución
            # Precio de compra: SOL invertido / tokens vendidos (proporcional)
            system_buy_price = float(system_trade.sol_invested / system_trade.token_amount_sold) if system_trade.token_amount_sold > 0 else 0
            trader_buy_price = float(trader_trade.sol_invested / trader_trade.token_amount_sold) if trader_trade.token_amount_sold > 0 else 0

            # Precio de venta: SOL recuperado / tokens vendidos
            system_sell_price = float(system_trade.sol_recovered / system_trade.token_amount_sold) if system_trade.token_amount_sold > 0 else 0
            trader_sell_price = float(trader_trade.sol_recovered / trader_trade.token_amount_sold) if trader_trade.token_amount_sold > 0 else 0

            token_display = trader_trade.token_symbol[:20] if len(trader_trade.token_symbol) > 20 else trader_trade.token_symbol

            _out(f"\n{idx}. {token_display}", lines)
            _out(f"{'-' * 130}", lines)
            _out(f"{'Métrica':<30} {'Trader':>32} {'Sistema':>32} {'Diferencia':>32}", lines)
            _out(f"{'-' * 130}", lines)
            _out(f"{'SOL invertido:':<30} {float(trader_trade.sol_invested):>31.6f} {float(system_trade.sol_invested):>31.6f} {float(trader_trade.sol_invested - system_trade.sol_invested):>+31.6f}", lines)
            _out(f"{'SOL recuperado:':<30} {float(trader_trade.sol_recovered):>31.6f} {float(system_trade.sol_recovered):>31.6f} {float(trader_trade.sol_recovered - system_trade.sol_recovered):>+31.6f}", lines)
            _out(f"{'PnL (SOL):':<30} {float(trader_trade.profit_loss_sol):>31.6f} {float(system_trade.profit_loss_sol):>31.6f} {float(trader_trade.profit_loss_sol - system_trade.profit_loss_sol):>+31.6f}", lines)
            _out(f"{'PnL (%):':<30} {float(trader_trade.profit_loss_pct):>30.2f}% {float(system_trade.profit_loss_pct):>30.2f}% {(float(trader_trade.profit_loss_pct) - float(system_trade.profit_loss_pct)):>+30.2f}%", lines)
            _out(f"{'Tokens vendidos:':<30} {float(trader_trade.token_amount_sold):>31.2f} {float(system_trade.token_amount_sold):>31.2f} {float(trader_trade.token_amount_sold - system_trade.token_amount_sold):>+31.2f}", lines)
            _out(f"{'Precio compra (SOL/token):':<30} {trader_buy_price:>31.15f} {system_buy_price:>31.15f} {(trader_buy_price - system_buy_price):>+31.15f}", lines)
            _out(f"{'Precio venta (SOL/token):':<30} {trader_sell_price:>31.15f} {system_sell_price:>31.15f} {(trader_sell_price - system_sell_price):>+31.15f}", lines)
            system_roi = _calculate_roi_percentage(system_trade)
            trader_roi = _calculate_roi_percentage(trader_trade)
            _out(f"{'ROI (%):':<30} {trader_roi:>30.2f}% {system_roi:>30.2f}% {(trader_roi - system_roi):>+30.2f}%", lines)

    _out(f"\n{'=' * 120}\n", lines)

    if return_string and lines is not None:
        return "\n".join(lines)
    return None


def _calculate_roi_percentage(trade: ClosedTrade) -> float:
    """
    Calcula el ROI porcentual de un trade (SOL recuperado / SOL invertido * 100).
    
    Args:
        trade: Trade cerrado
    
    Returns:
        ROI porcentual
    """
    if trade.sol_invested > 0:
        roi_pct = float(trade.sol_recovered / trade.sol_invested * Decimal('100'))
        return roi_pct
    return 0.0
