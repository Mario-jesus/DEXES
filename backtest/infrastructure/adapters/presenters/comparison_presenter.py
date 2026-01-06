# -*- coding: utf-8 -*-
"""
Presentador de comparación de estadísticas para consola.

Formatea y muestra la comparación entre dos BacktestStats (trader vs sistema)
en la consola de manera legible, incluyendo métricas avanzadas y diferencias.
"""
from decimal import Decimal

from ....domain.entities.backtest_statistics import BacktestStats


def show_comparison(trader_stats: BacktestStats, system_stats: BacktestStats) -> None:
    """
    Muestra la comparación entre las estadísticas del trader y del sistema.
    
    Incluye métricas avanzadas (profit_factor, win_rate, gain_expectancy, etc.)
    y calcula las diferencias entre ambas métricas.
    
    Args:
        trader_stats: BacktestStats del trader (repositorio pumpportal)
        system_stats: BacktestStats del sistema (repositorio system)
    """
    print("\n" + "=" * 100)
    print("COMPARACIÓN TRADER vs SISTEMA")
    print("=" * 100)

    # Información básica
    print(f"\n📊 INFORMACIÓN GENERAL")
    print("-" * 100)
    print(f"Trader - Total trades: {trader_stats.total_trades}")
    print(f"Sistema - Total trades: {system_stats.total_trades}")
    print(f"Diferencia: {trader_stats.total_trades - system_stats.total_trades}")

    # Métricas financieras básicas (valores absolutos para referencia)
    print(f"\n💰 ANÁLISIS FINANCIERO (Valores absolutos - referencia)")
    print("-" * 100)
    print(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}")
    print("-" * 100)

    _print_comparison_row(
        "Total SOL invertido",
        trader_stats.total_sol_invested,
        system_stats.total_sol_invested,
        format_type="sol"
    )
    _print_comparison_row(
        "Total SOL recuperado",
        trader_stats.total_sol_recovered,
        system_stats.total_sol_recovered,
        format_type="sol"
    )
    _print_comparison_row(
        "Beneficio neto (SOL)",
        trader_stats.net_profit_sol,
        system_stats.net_profit_sol,
        format_type="sol"
    )

    # Métricas porcentuales y ratios (comparables)
    print(f"\n📈 MÉTRICAS COMPARABLES (Porcentajes y Ratios)")
    print("-" * 100)
    print(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}")
    print("-" * 100)

    _print_comparison_row(
        "ROI (%)",
        trader_stats.roi,
        system_stats.roi,
        format_type="percentage"
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
        format_type="percentage"
    )

    # Métricas avanzadas
    print(f"\n📈 MÉTRICAS AVANZADAS")
    print("-" * 100)
    print(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}")
    print("-" * 100)

    _print_comparison_row(
        "Profit Factor",
        trader_stats.profit_factor,
        system_stats.profit_factor,
        format_type="decimal_4"
    )
    _print_comparison_row(
        "Win Rate (%)",
        trader_stats.win_rate,
        system_stats.win_rate,
        format_type="percentage"
    )
    _print_comparison_row(
        "Gain Expectancy",
        trader_stats.gain_expectancy,
        system_stats.gain_expectancy,
        format_type="decimal_6"
    )
    _print_comparison_row(
        "Gain Expectancy Adjusted",
        trader_stats.gain_expectancy_adjusted,
        system_stats.gain_expectancy_adjusted,
        format_type="decimal_6"
    )
    _print_comparison_row(
        "Sharpe Ratio",
        trader_stats.sharpe_ratio,
        system_stats.sharpe_ratio,
        format_type="decimal_4"
    )
    _print_comparison_row(
        "Sortino Ratio",
        trader_stats.sortino_ratio,
        system_stats.sortino_ratio,
        format_type="decimal_4"
    )

    # Detalles de Gain Expectancy (ratios y porcentajes)
    print(f"\n🔍 DETALLES DE GAIN EXPECTANCY")
    print("-" * 100)
    print(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}")
    print("-" * 100)

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
        format_type="decimal_4"
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
        format_type="percentage"
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
        format_type="percentage"
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
        format_type="percentage"
    )

    # Desglose de trades (porcentajes)
    print(f"\n📊 DESGLOSE DE TRADES")
    print("-" * 100)
    print(f"{'Métrica':<40} {'Trader':<25} {'Sistema':<25} {'Diferencia':<25}")
    print("-" * 100)

    _print_comparison_row(
        "Trades rentables (cantidad)",
        trader_stats.profitable_trades,
        system_stats.profitable_trades,
        format_type="integer"
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
        format_type="percentage"
    )
    
    _print_comparison_row(
        "Trades con pérdida (cantidad)",
        trader_stats.losing_trades,
        system_stats.losing_trades,
        format_type="integer"
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
        format_type="percentage"
    )

    _print_comparison_row(
        "Trades break-even (cantidad)",
        trader_stats.break_even_trades,
        system_stats.break_even_trades,
        format_type="integer"
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
        format_type="percentage"
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
        format_type="percentage"
    )

    # Mejor y peor trade
    if trader_stats.best_trade and system_stats.best_trade:
        print(f"\n🏆 MEJOR TRADE")
        print("-" * 100)
        print(f"Trader: {trader_stats.best_trade.token_symbol} - "
                f"{float(trader_stats.best_trade.profit_loss_sol):.6f} SOL "
                f"({float(trader_stats.best_trade.profit_loss_pct):.2f}%)")
        print(f"Sistema: {system_stats.best_trade.token_symbol} - "
                f"{float(system_stats.best_trade.profit_loss_sol):.6f} SOL "
                f"({float(system_stats.best_trade.profit_loss_pct):.2f}%)")
    
    if trader_stats.worst_trade and system_stats.worst_trade:
        print(f"\n📉 PEOR TRADE")
        print("-" * 100)
        print(f"Trader: {trader_stats.worst_trade.token_symbol} - "
                f"{float(trader_stats.worst_trade.profit_loss_sol):.6f} SOL "
                f"({float(trader_stats.worst_trade.profit_loss_pct):.2f}%)")
        print(f"Sistema: {system_stats.worst_trade.token_symbol} - "
                f"{float(system_stats.worst_trade.profit_loss_sol):.6f} SOL "
                f"({float(system_stats.worst_trade.profit_loss_pct):.2f}%)")

    # Posiciones abiertas
    if trader_stats.open_positions or system_stats.open_positions:
        print(f"\n⚠️  POSICIONES ABIERTAS")
        print("-" * 100)
        print(f"Trader: {len(trader_stats.open_positions)} posiciones abiertas")
        print(f"Sistema: {len(system_stats.open_positions)} posiciones abiertas")

    print(f"\n{'=' * 100}\n")


def _print_comparison_row(
    label: str,
    trader_value: Decimal | int,
    system_value: Decimal | int,
    format_type: str = "decimal"
) -> None:
    """
    Imprime una fila de comparación con formato consistente.
    
    Args:
        label: Etiqueta de la métrica
        trader_value: Valor del trader
        system_value: Valor del sistema
        format_type: Tipo de formato ('sol', 'percentage', 'decimal_4', 'decimal_6', 'integer')
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

    print(f"{label:<40} {trader_str:<25} {system_str:<25} {diff_str:<25}")
