# -*- coding: utf-8 -*-
"""
Presentador de estadísticas para consola.

Formatea y muestra BacktestStats en la consola de manera legible.
"""
from datetime import datetime

from ....domain.entities.backtest_statistics import BacktestStats


def show_stats(stats: BacktestStats) -> None:
    """
    Muestra las estadísticas del backtest formateadas en la consola.
    
    Args:
        stats: BacktestStats a mostrar
    """
    print("\n" + "=" * 80)
    print("RESULTADOS DEL BACKTEST")
    print("=" * 80)

    if stats.validation_metrics:
        print(f"\n🔍 MÉTRICAS DE FILTRADO")
        print("-" * 80)
        vm = stats.validation_metrics
        print(f"Total de buys: {vm.total_buy_transactions}")
        print(f"Buys aceptados: {vm.accepted_buy_transactions}")
        print(f"Tasa de aceptación (solo buys): {float(vm.filter_acceptance_rate):.2f}%")
        print(f"\nFiltros aplicados:")

        # Mostrar métricas de cada validación
        for validation_name, metrics in vm.validation_metrics.items():
            enabled = metrics.get('enabled', False)
            rejected_count = metrics.get('rejected_count', 0)

            if validation_name == "min_sol_amount":
                print(f"  - Filtro de monto mínimo SOL: {'Habilitado' if enabled else 'Deshabilitado'}")
                if enabled:
                    thresholds = metrics.get('exchange_thresholds', {})
                    if thresholds:
                        print(f"    * Umbrales: {', '.join([f'{k}: {v} SOL' for k, v in thresholds.items()])}")
                    print(f"    * Rechazos: {rejected_count}")
            elif validation_name == "max_sol_amount":
                print(f"  - Filtro de monto máximo SOL: {'Habilitado' if enabled else 'Deshabilitado'}")
                if enabled:
                    thresholds = metrics.get('exchange_thresholds', {})
                    if thresholds:
                        print(f"    * Umbrales: {', '.join([f'{k}: {v} SOL' for k, v in thresholds.items()])}")
                    print(f"    * Rechazos: {rejected_count}")
            elif validation_name == "trade_activity":
                print(f"  - Filtro de actividad: {'Habilitado' if enabled else 'Deshabilitado'}")
                if enabled:
                    threshold = metrics.get('min_trade_count_threshold', 0)
                    window = metrics.get('activity_window_seconds', 0)
                    print(f"    * Umbral mínimo: {threshold} trades")
                    print(f"    * Ventana de tiempo: {window} segundos")
                    print(f"    * Rechazos: {rejected_count}")
            elif validation_name == "allowed_pools":
                print(f"  - Filtro de pools permitidos: {'Habilitado' if enabled else 'Deshabilitado'}")
                if enabled:
                    allowed_pools = metrics.get('allowed_pools', [])
                    if allowed_pools:
                        print(f"    * Pools permitidos: {', '.join(allowed_pools)}")
                    print(f"    * Rechazos: {rejected_count}")

    print(f"\n📊 ESTADÍSTICAS GENERALES")
    print("-" * 80)
    print(f"Total de trades cerrados: {stats.total_trades}")
    print(f"Trades rentables: {stats.profitable_trades}")
    print(f"Trades con pérdida: {stats.losing_trades}")
    print(f"Trades break-even: {stats.break_even_trades}")
    print(f"Win rate: {float(stats.win_rate):.2f}%")

    print(f"\n💰 ANÁLISIS FINANCIERO")
    print("-" * 80)
    print(f"Total SOL invertido: {float(stats.total_sol_invested):.6f} SOL")
    print(f"Total SOL recuperado: {float(stats.total_sol_recovered):.6f} SOL")
    print(f"Ganancias totales: {float(stats.total_profit_sol):.6f} SOL")
    print(f"Pérdidas totales: {float(stats.total_loss_sol):.6f} SOL")
    print(f"Beneficio neto: {float(stats.net_profit_sol):.6f} SOL")
    print(f"ROI: {float(stats.roi):.2f}%")

    print(f"\n📈 PROMEDIOS")
    print("-" * 80)
    print(f"Promedio por trade: {float(stats.avg_profit_per_trade):.6f} SOL")
    if stats.profitable_trades > 0:
        print(f"Promedio en trades ganadores: {float(stats.avg_profit_per_winning_trade):.6f} SOL")
    if stats.losing_trades > 0:
        print(f"Promedio en trades perdedores: {float(stats.avg_loss_per_losing_trade):.6f} SOL")

    if stats.best_trade:
        print(f"\n🏆 MEJOR TRADE")
        print("-" * 80)
        bt = stats.best_trade
        exchange_info = f" [{bt.exchange_name}]" if bt.exchange_name else ""
        print(f"Token: {bt.token_symbol}{exchange_info} ({bt.token_address[:8]}...)")
        print(f"Compra: {bt.buy_hash[:16]}... (bloque {bt.buy_block})")
        print(f"Venta: {bt.sell_hash[:16]}... (bloque {bt.sell_block})")
        print(f"SOL invertido: {float(bt.sol_invested):.6f}")
        print(f"SOL recuperado: {float(bt.sol_recovered):.6f}")
        print(f"Ganancia: {float(bt.profit_loss_sol):.6f} SOL ({float(bt.profit_loss_pct):.2f}%)")
        if bt.duration_seconds:
            hours = bt.duration_seconds / 3600
            print(f"Duración: {hours:.2f} horas")

    if stats.worst_trade:
        print(f"\n📉 PEOR TRADE")
        print("-" * 80)
        wt = stats.worst_trade
        exchange_info = f" [{wt.exchange_name}]" if wt.exchange_name else ""
        print(f"Token: {wt.token_symbol}{exchange_info} ({wt.token_address[:8]}...)")
        print(f"Compra: {wt.buy_hash[:16]}... (bloque {wt.buy_block})")
        print(f"Venta: {wt.sell_hash[:16]}... (bloque {wt.sell_block})")
        print(f"SOL invertido: {float(wt.sol_invested):.6f}")
        print(f"SOL recuperado: {float(wt.sol_recovered):.6f}")
        print(f"Pérdida: {float(wt.profit_loss_sol):.6f} SOL ({float(wt.profit_loss_pct):.2f}%)")
        if wt.duration_seconds:
            hours = wt.duration_seconds / 3600
            print(f"Duración: {hours:.2f} horas")

    if stats.open_positions:
        print(f"\n⚠️  POSICIONES ABIERTAS RESTANTES: {len(stats.open_positions)}")
        print("-" * 80)
        print(f"Cantidad de posiciones abiertas: {len(stats.open_positions)}")

    if stats.pool_stats:
        print(f"\n🏊 MÉTRICAS POR POOL/EXCHANGE")
        print("-" * 80)
        for exchange_name, pool_stat in stats.pool_stats.items():
            print(f"\n📊 {exchange_name or 'Unknown'}")
            print(f"  Total trades: {pool_stat.total_trades}")
            print(f"  Trades rentables: {pool_stat.profitable_trades}")
            print(f"  Trades con pérdida: {pool_stat.losing_trades}")
            print(f"  Win rate: {float(pool_stat.win_rate):.2f}%")
            print(f"  SOL invertido: {float(pool_stat.total_sol_invested):.6f}")
            print(f"  SOL recuperado: {float(pool_stat.total_sol_recovered):.6f}")
            print(f"  Beneficio neto: {float(pool_stat.net_profit_sol):.6f} SOL")
            print(f"  ROI: {float(pool_stat.roi):.2f}%")
            print(f"  Promedio por trade: {float(pool_stat.avg_profit_per_trade):.6f} SOL")
            if pool_stat.best_trade:
                print(f"  Mejor trade: {float(pool_stat.best_trade.profit_loss_sol):.6f} SOL")
            if pool_stat.worst_trade:
                print(f"  Peor trade: {float(pool_stat.worst_trade.profit_loss_sol):.6f} SOL")

    print(f"\n📅 INFORMACIÓN DE FECHAS Y FILTROS")
    print("-" * 80)
    # Rango completo de datos disponibles
    if stats.min_timestamp and stats.max_timestamp:
        min_dt = datetime.fromisoformat(stats.min_timestamp)
        max_dt = datetime.fromisoformat(stats.max_timestamp)
        duration = (max_dt - min_dt).days
        print(f"Rango completo de datos disponibles:")
        print(f"  Fecha mínima: {stats.min_timestamp}")
        print(f"  Fecha máxima: {stats.max_timestamp}")
        print(f"  Duración: {duration} días")
    else:
        print("No hay información de fechas disponible")

    # Filtros de fecha aplicados
    if stats.date_range_start or stats.date_range_end:
        print(f"\nFiltros de fecha aplicados:")
        print(f"  Fecha inicio (filtro): {stats.date_range_start or 'Sin límite'}")
        print(f"  Fecha fin (filtro): {stats.date_range_end or 'Sin límite'}")
        print(f"  Transacciones antes del filtro: {stats.total_transactions_before_date_filter}")
        print(f"  Transacciones después del filtro: {stats.date_filtered_transactions}")
        if stats.total_transactions_before_date_filter > 0:
            filter_percentage = (stats.date_filtered_transactions / stats.total_transactions_before_date_filter) * 100
            print(f"  Porcentaje retenido: {filter_percentage:.2f}%")
    else:
        print(f"Sin filtros de fecha aplicados")
        print(f"  Total de transacciones: {stats.total_transactions_before_date_filter}")

    print("\n" + "=" * 80)
