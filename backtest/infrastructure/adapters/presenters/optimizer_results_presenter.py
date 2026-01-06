# -*- coding: utf-8 -*-
"""
Presentador de resultados de optimización para consola.

Formatea y muestra listas de BacktestDataEntry (resultados de optimización)
en la consola de manera legible.
"""
from typing import List

from backtest.application.types.optimizer_types import BacktestDataEntry


def show_optimizer_results(data: List[BacktestDataEntry]) -> None:
    """
    Muestra las estadísticas de las estrategias en el orden en que están en la lista.

    Args:
        data: Lista de BacktestDataEntry con los resultados de las búsquedas.
    """
    if not data:
        print("No hay datos para mostrar")
        return

    print("\n" + "=" * 100)
    print(f"RESULTADOS DE BÚSQUEDA DE PARÁMETROS ({len(data)} estrategias)")
    print("=" * 100)

    for idx, entry in enumerate(data, 1):
        print(f"\n{'─' * 100}")
        print(f"ESTRATEGIA #{idx}")
        print(f"{'─' * 100}")

        # Información básica de la estrategia
        print(f"Tipo de filtro: {entry['filter_type']}")
        print(f"Parámetros: {entry['filter_params']}")

        if entry.get('date_start') or entry.get('date_end'):
            date_start = entry.get('date_start', 'N/A')
            date_end = entry.get('date_end', 'N/A')
            print(f"Rango de fechas: {date_start} a {date_end}")

        # Verificar si hay datos disponibles
        if not entry.get('has_available_data', False):
            print("⚠️  No hay datos disponibles para esta estrategia")
            continue

        # Métricas generales
        print(f"\n📊 ESTADÍSTICAS GENERALES")
        print(f"  Total trades: {entry.get('total_trades', 0)}")
        if 'win_rate' in entry:
            print(f"  Win rate: {float(entry['win_rate']):.2f}%")
        if 'roi' in entry:
            print(f"  ROI: {float(entry['roi']):.2f}%")

        # Métricas avanzadas
        has_advanced_metrics = any(
            key in entry for key in [
                'profit_factor', 'gain_expectancy', 'gain_expectancy_adjusted',
                'sharpe_ratio', 'sortino_ratio'
            ]
        )
        if has_advanced_metrics:
            print(f"\n📈 MÉTRICAS AVANZADAS")
            if 'profit_factor' in entry:
                print(f"  Profit Factor: {float(entry['profit_factor']):.4f}")
            if 'gain_expectancy' in entry:
                print(f"  Gain Expectancy: {float(entry['gain_expectancy']):.6f}")
            if 'gain_expectancy_adjusted' in entry:
                print(f"  Gain Expectancy Adjusted: {float(entry['gain_expectancy_adjusted']):.6f}")
            if 'sharpe_ratio' in entry:
                print(f"  Sharpe Ratio: {float(entry['sharpe_ratio']):.4f}")
            if 'sortino_ratio' in entry:
                print(f"  Sortino Ratio: {float(entry['sortino_ratio']):.4f}")

        print(f"\n💰 ANÁLISIS FINANCIERO")
        if 'total_sol_invested' in entry:
            print(f"  Total SOL invertido: {float(entry['total_sol_invested']):.6f} SOL")
        if 'total_sol_recovered' in entry:
            print(f"  Total SOL recuperado: {float(entry['total_sol_recovered']):.6f} SOL")
        if 'net_profit_sol' in entry:
            profit_sign = "+" if entry['net_profit_sol'] >= 0 else ""
            print(f"  Beneficio neto: {profit_sign}{float(entry['net_profit_sol']):.6f} SOL")

        # Métricas por pool
        if 'pump_fun' in entry and entry['pump_fun']:
            pf = entry['pump_fun']
            print(f"\n🏊 Pump.Fun")
            print(f"  Total trades: {pf.get('total_trades', 0)}")
            print(f"  SOL invertido: {float(pf.get('total_sol_invested', 0)):.6f}")
            print(f"  SOL recuperado: {float(pf.get('total_sol_recovered', 0)):.6f}")
            if 'net_profit_sol' in pf:
                profit_sign = "+" if pf['net_profit_sol'] >= 0 else ""
                print(f"  Beneficio neto: {profit_sign}{float(pf['net_profit_sol']):.6f} SOL")
            if 'win_rate' in pf:
                print(f"  Win rate: {float(pf['win_rate']):.2f}%")
            if 'roi' in pf:
                print(f"  ROI: {float(pf['roi']):.2f}%")
            # Métricas avanzadas del pool
            if 'profit_factor' in pf:
                print(f"  Profit Factor: {float(pf['profit_factor']):.4f}")
            if 'gain_expectancy' in pf:
                print(f"  Gain Expectancy: {float(pf['gain_expectancy']):.6f}")
            if 'gain_expectancy_adjusted' in pf:
                print(f"  Gain Expectancy Adjusted: {float(pf['gain_expectancy_adjusted']):.6f}")
            if 'sharpe_ratio' in pf:
                print(f"  Sharpe Ratio: {float(pf['sharpe_ratio']):.4f}")
            if 'sortino_ratio' in pf:
                print(f"  Sortino Ratio: {float(pf['sortino_ratio']):.4f}")

        if 'pump_swap' in entry and entry['pump_swap']:
            ps = entry['pump_swap']
            print(f"\n🏊 PumpSwap")
            print(f"  Total trades: {ps.get('total_trades', 0)}")
            print(f"  SOL invertido: {float(ps.get('total_sol_invested', 0)):.6f}")
            print(f"  SOL recuperado: {float(ps.get('total_sol_recovered', 0)):.6f}")
            if 'net_profit_sol' in ps:
                profit_sign = "+" if ps['net_profit_sol'] >= 0 else ""
                print(f"  Beneficio neto: {profit_sign}{float(ps['net_profit_sol']):.6f} SOL")
            if 'win_rate' in ps:
                print(f"  Win rate: {float(ps['win_rate']):.2f}%")
            if 'roi' in ps:
                print(f"  ROI: {float(ps['roi']):.2f}%")
            # Métricas avanzadas del pool
            if 'profit_factor' in ps:
                print(f"  Profit Factor: {float(ps['profit_factor']):.4f}")
            if 'gain_expectancy' in ps:
                print(f"  Gain Expectancy: {float(ps['gain_expectancy']):.6f}")
            if 'gain_expectancy_adjusted' in ps:
                print(f"  Gain Expectancy Adjusted: {float(ps['gain_expectancy_adjusted']):.6f}")
            if 'sharpe_ratio' in ps:
                print(f"  Sharpe Ratio: {float(ps['sharpe_ratio']):.4f}")
            if 'sortino_ratio' in ps:
                print(f"  Sortino Ratio: {float(ps['sortino_ratio']):.4f}")

    print(f"\n{'=' * 100}\n")
