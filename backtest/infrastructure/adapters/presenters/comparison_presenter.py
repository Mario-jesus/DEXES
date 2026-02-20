# -*- coding: utf-8 -*-
"""
Presentador de comparación de estadísticas para consola.

Formatea y muestra la comparación entre dos BacktestStats (trader vs sistema)
en la consola de manera legible, incluyendo métricas avanzadas y diferencias.
"""
from decimal import Decimal

from ....domain.entities.backtest_statistics import BacktestStats


def _out(s: str, lines: list[str] | None) -> None:
    """Emit line: append to list or print."""
    if lines is not None:
        lines.append(s)
    else:
        print(s)


def show_comparison(
    trader_stats: BacktestStats, system_stats: BacktestStats, return_string: bool = False
) -> str | None:
    """
    Muestra la comparación entre las estadísticas del trader y del sistema.
    
    Incluye métricas avanzadas (profit_factor, win_rate, gain_expectancy, etc.)
    y calcula las diferencias entre ambas métricas.
    
    Args:
        trader_stats: BacktestStats del trader (repositorio pumpportal)
        system_stats: BacktestStats del sistema (repositorio system)
        return_string: Si True, devuelve el texto formateado en lugar de imprimirlo.
            Por defecto False (imprime en consola).
    
    Returns:
        Si return_string es True, el string con el reporte; si no, None.
    """
    lines: list[str] | None = [] if return_string else None

    _out("\n" + "=" * 100, lines)
    _out("COMPARACIÓN TRADER vs SISTEMA", lines)
    _out("=" * 100, lines)

    # Información básica
    _out(f"\n📊 INFORMACIÓN GENERAL", lines)
    _out("-" * 100, lines)
    _out(f"Trader - Total trades: {trader_stats.total_trades}", lines)
    _out(f"Sistema - Total trades: {system_stats.total_trades}", lines)
    _out(f"Diferencia: {trader_stats.total_trades - system_stats.total_trades}", lines)

    # Métricas financieras básicas (valores absolutos para referencia)
    _out(f"\n💰 ANÁLISIS FINANCIERO (Valores absolutos - referencia)", lines)
    _out("-" * 100, lines)
    _out(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}", lines)
    _out("-" * 100, lines)

    _print_comparison_row(
        "Total SOL invertido",
        trader_stats.total_sol_invested,
        system_stats.total_sol_invested,
        format_type="sol",
        lines=lines,
    )
    _print_comparison_row(
        "Total SOL recuperado",
        trader_stats.total_sol_recovered,
        system_stats.total_sol_recovered,
        format_type="sol",
        lines=lines,
    )
    _print_comparison_row(
        "Beneficio neto (SOL)",
        trader_stats.net_profit_sol,
        system_stats.net_profit_sol,
        format_type="sol",
        lines=lines,
    )

    # Métricas porcentuales y ratios (comparables)
    _out(f"\n📈 MÉTRICAS COMPARABLES (Porcentajes y Ratios)", lines)
    _out("-" * 100, lines)
    _out(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}", lines)
    _out("-" * 100, lines)

    _print_comparison_row(
        "ROI (%)",
        trader_stats.roi,
        system_stats.roi,
        format_type="percentage",
        lines=lines,
    )

    # Calcular ratio de recuperación (SOL recuperado / SOL invertido)
    trader_recovery_ratio = Decimal(
        (float(trader_stats.total_sol_recovered) / float(trader_stats.total_sol_invested) * 100)
        if trader_stats.total_sol_invested > 0
        else 0
    )
    system_recovery_ratio = Decimal(
        (float(system_stats.total_sol_recovered) / float(system_stats.total_sol_invested) * 100)
        if system_stats.total_sol_invested > 0
        else 0
    )
    _print_comparison_row(
        "Ratio de Recuperación (%)",
        trader_recovery_ratio,
        system_recovery_ratio,
        format_type="percentage",
        lines=lines,
    )

    # Métricas avanzadas
    _out(f"\n📈 MÉTRICAS AVANZADAS", lines)
    _out("-" * 100, lines)
    _out(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}", lines)
    _out("-" * 100, lines)

    _print_comparison_row(
        "Profit Factor",
        trader_stats.profit_factor,
        system_stats.profit_factor,
        format_type="decimal_4",
        lines=lines,
    )
    _print_comparison_row(
        "Win Rate (%)",
        trader_stats.win_rate,
        system_stats.win_rate,
        format_type="percentage",
        lines=lines,
    )
    _print_comparison_row(
        "Gain Expectancy",
        trader_stats.gain_expectancy,
        system_stats.gain_expectancy,
        format_type="decimal_6",
        lines=lines,
    )
    _print_comparison_row(
        "Gain Expectancy Adjusted",
        trader_stats.gain_expectancy_adjusted,
        system_stats.gain_expectancy_adjusted,
        format_type="decimal_6",
        lines=lines,
    )
    _print_comparison_row(
        "Sharpe Ratio",
        trader_stats.sharpe_ratio,
        system_stats.sharpe_ratio,
        format_type="decimal_4",
        lines=lines,
    )
    _print_comparison_row(
        "Sortino Ratio",
        trader_stats.sortino_ratio,
        system_stats.sortino_ratio,
        format_type="decimal_4",
        lines=lines,
    )

    # Detalles de Gain Expectancy (ratios y porcentajes)
    _out(f"\n🔍 DETALLES DE GAIN EXPECTANCY", lines)
    _out("-" * 100, lines)
    _out(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}", lines)
    _out("-" * 100, lines)

    # Calcular ratio Win/Loss (Average Win / Average Loss en valor absoluto)
    trader_win_loss_ratio = Decimal(
        (abs(float(trader_stats.avg_profit_per_winning_trade)) / abs(float(trader_stats.avg_loss_per_losing_trade)))
        if trader_stats.avg_loss_per_losing_trade != 0 and trader_stats.avg_profit_per_winning_trade != 0
        else 0
    )
    system_win_loss_ratio = Decimal(
        (abs(float(system_stats.avg_profit_per_winning_trade)) / abs(float(system_stats.avg_loss_per_losing_trade)))
        if system_stats.avg_loss_per_losing_trade != 0 and system_stats.avg_profit_per_winning_trade != 0
        else 0
    )
    _print_comparison_row(
        "Ratio Win/Loss (Avg Win / Avg Loss)",
        trader_win_loss_ratio,
        system_win_loss_ratio,
        format_type="decimal_4",
        lines=lines,
    )

    # Average Win como porcentaje del promedio invertido
    trader_avg_invested = (
        trader_stats.total_sol_invested / trader_stats.total_trades
        if trader_stats.total_trades > 0
        else Decimal('0')
    )
    system_avg_invested = (
        system_stats.total_sol_invested / system_stats.total_trades
        if system_stats.total_trades > 0
        else Decimal('0')
    )

    trader_avg_win_pct = Decimal(
        (float(trader_stats.avg_profit_per_winning_trade) / float(trader_avg_invested) * 100)
        if trader_avg_invested > 0
        else 0
    )
    system_avg_win_pct = Decimal(
        (float(system_stats.avg_profit_per_winning_trade) / float(system_avg_invested) * 100)
        if system_avg_invested > 0
        else 0
    )
    _print_comparison_row(
        "Average Win (% del promedio invertido)",
        trader_avg_win_pct,
        system_avg_win_pct,
        format_type="percentage",
        lines=lines,
    )
    
    trader_avg_loss_pct = Decimal(
        (abs(float(trader_stats.avg_loss_per_losing_trade)) / float(trader_avg_invested) * 100)
        if trader_avg_invested > 0
        else 0
    )
    system_avg_loss_pct = Decimal(
        (abs(float(system_stats.avg_loss_per_losing_trade)) / float(system_avg_invested) * 100)
        if system_avg_invested > 0
        else 0
    )
    _print_comparison_row(
        "Average Loss (% del promedio invertido)",
        trader_avg_loss_pct,
        system_avg_loss_pct,
        format_type="percentage",
        lines=lines,
    )

    trader_avg_per_trade_pct = Decimal(
        (float(trader_stats.avg_profit_per_trade) / float(trader_avg_invested) * 100)
        if trader_avg_invested > 0
        else 0
    )
    system_avg_per_trade_pct = Decimal(
        (float(system_stats.avg_profit_per_trade) / float(system_avg_invested) * 100)
        if system_avg_invested > 0
        else 0
    )
    _print_comparison_row(
        "Promedio por trade (% del promedio invertido)",
        trader_avg_per_trade_pct,
        system_avg_per_trade_pct,
        format_type="percentage",
        lines=lines,
    )

    # Desglose de trades (porcentajes)
    _out(f"\n📊 DESGLOSE DE TRADES", lines)
    _out("-" * 100, lines)
    _out(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}", lines)
    _out("-" * 100, lines)

    _print_comparison_row(
        "Trades rentables (cantidad)",
        trader_stats.profitable_trades,
        system_stats.profitable_trades,
        format_type="integer",
        lines=lines,
    )

    # Porcentaje de trades rentables
    trader_profitable_pct = Decimal(
        (trader_stats.profitable_trades / trader_stats.total_trades * 100)
        if trader_stats.total_trades > 0
        else 0
    )
    system_profitable_pct = Decimal(
        (system_stats.profitable_trades / system_stats.total_trades * 100)
        if system_stats.total_trades > 0
        else 0
    )
    _print_comparison_row(
        "Trades rentables (%)",
        trader_profitable_pct,
        system_profitable_pct,
        format_type="percentage",
        lines=lines,
    )
    
    _print_comparison_row(
        "Trades con pérdida (cantidad)",
        trader_stats.losing_trades,
        system_stats.losing_trades,
        format_type="integer",
        lines=lines,
    )

    # Porcentaje de trades con pérdida
    trader_losing_pct = Decimal(
        (trader_stats.losing_trades / trader_stats.total_trades * 100)
        if trader_stats.total_trades > 0
        else 0
    )
    system_losing_pct = Decimal(
        (system_stats.losing_trades / system_stats.total_trades * 100)
        if system_stats.total_trades > 0
        else 0
    )
    _print_comparison_row(
        "Trades con pérdida (%)",
        trader_losing_pct,
        system_losing_pct,
        format_type="percentage",
        lines=lines,
    )

    _print_comparison_row(
        "Trades break-even (cantidad)",
        trader_stats.break_even_trades,
        system_stats.break_even_trades,
        format_type="integer",
        lines=lines,
    )

    # Ratio de ganancias/pérdidas (como porcentaje del total invertido)
    trader_profit_ratio = Decimal(
        (float(trader_stats.total_profit_sol) / float(trader_stats.total_sol_invested) * 100)
        if trader_stats.total_sol_invested > 0
        else 0
    )
    system_profit_ratio = Decimal(
        (float(system_stats.total_profit_sol) / float(system_stats.total_sol_invested) * 100)
        if system_stats.total_sol_invested > 0
        else 0
    )
    _print_comparison_row(
        "Ganancias totales (% del invertido)",
        trader_profit_ratio,
        system_profit_ratio,
        format_type="percentage",
        lines=lines,
    )

    trader_loss_ratio = Decimal(
        (float(trader_stats.total_loss_sol) / float(trader_stats.total_sol_invested) * 100)
        if trader_stats.total_sol_invested > 0
        else 0
    )
    system_loss_ratio = Decimal(
        (float(system_stats.total_loss_sol) / float(system_stats.total_sol_invested) * 100)
        if system_stats.total_sol_invested > 0
        else 0
    )
    _print_comparison_row(
        "Pérdidas totales (% del invertido)",
        trader_loss_ratio,
        system_loss_ratio,
        format_type="percentage",
        lines=lines,
    )

    # Mejor y peor trade
    if trader_stats.best_trade and system_stats.best_trade:
        _out(f"\n🏆 MEJOR TRADE", lines)
        _out("-" * 100, lines)
        _out(f"Trader: {trader_stats.best_trade.token_symbol} - "
                f"{float(trader_stats.best_trade.profit_loss_sol):.6f} SOL "
                f"({float(trader_stats.best_trade.profit_loss_pct):.2f}%)", lines)
        _out(f"Sistema: {system_stats.best_trade.token_symbol} - "
                f"{float(system_stats.best_trade.profit_loss_sol):.6f} SOL "
                f"({float(system_stats.best_trade.profit_loss_pct):.2f}%)", lines)
    
    if trader_stats.worst_trade and system_stats.worst_trade:
        _out(f"\n📉 PEOR TRADE", lines)
        _out("-" * 100, lines)
        _out(f"Trader: {trader_stats.worst_trade.token_symbol} - "
                f"{float(trader_stats.worst_trade.profit_loss_sol):.6f} SOL "
                f"({float(trader_stats.worst_trade.profit_loss_pct):.2f}%)", lines)
        _out(f"Sistema: {system_stats.worst_trade.token_symbol} - "
                f"{float(system_stats.worst_trade.profit_loss_sol):.6f} SOL "
                f"({float(system_stats.worst_trade.profit_loss_pct):.2f}%)", lines)

    # Posiciones abiertas
    if trader_stats.open_positions or system_stats.open_positions:
        _out(f"\n⚠️  POSICIONES ABIERTAS", lines)
        _out("-" * 100, lines)
        _out(f"Trader: {len(trader_stats.open_positions)} posiciones abiertas", lines)
        _out(f"Sistema: {len(system_stats.open_positions)} posiciones abiertas", lines)

    _out(f"\n{'=' * 100}\n", lines)

    if return_string and lines is not None:
        return "\n".join(lines)
    return None


def _print_comparison_row(
    label: str,
    trader_value: Decimal | int,
    system_value: Decimal | int,
    format_type: str = "decimal",
    lines: list[str] | None = None,
) -> None:
    """
    Imprime una fila de comparación con formato consistente.
    
    Args:
        label: Etiqueta de la métrica
        trader_value: Valor del trader
        system_value: Valor del sistema
        format_type: Tipo de formato ('sol', 'percentage', 'decimal_4', 'decimal_6', 'integer')
        lines: Si se pasa, se añade la línea a esta lista en lugar de imprimir.
    """
    # Formatear valores según el tipo
    if format_type == "sol":
        trader_str = f"{float(trader_value):.6f} SOL"
        system_str = f"{float(system_value):.6f} SOL"
        diff = float(trader_value) - float(system_value)
        diff_str = f"{diff:+.6f} SOL"
    elif format_type == "percentage":
        trader_str = f"{float(trader_value):.2f}%"
        system_str = f"{float(system_value):.2f}%"
        diff = float(trader_value) - float(system_value)
        diff_str = f"{diff:+.2f}%"
    elif format_type == "decimal_4":
        trader_str = f"{float(trader_value):.4f}"
        system_str = f"{float(system_value):.4f}"
        diff = float(trader_value) - float(system_value)
        diff_str = f"{diff:+.4f}"
    elif format_type == "decimal_6":
        trader_str = f"{float(trader_value):.6f}"
        system_str = f"{float(system_value):.6f}"
        diff = float(trader_value) - float(system_value)
        diff_str = f"{diff:+.6f}"
    elif format_type == "integer":
        trader_str = f"{int(trader_value)}"
        system_str = f"{int(system_value)}"
        diff = int(trader_value) - int(system_value)
        diff_str = f"{diff:+d}"
    else:
        trader_str = str(trader_value)
        system_str = str(system_value)
        diff = float(trader_value) - float(system_value)
        diff_str = f"{diff:+.6f}"

    _out(f"{label:<40} {trader_str:<25} {system_str:<25} {diff_str:<25}", lines)
