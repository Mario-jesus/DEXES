# -*- coding: utf-8 -*-
"""
Presentador de estadísticas para consola.

Formatea y muestra BacktestStats en la consola de manera legible.
"""
from datetime import datetime

from ....domain.entities.backtest_statistics import BacktestStats


def _out(s: str, lines: list[str] | None) -> None:
    """Emit line: append to list or print."""
    if lines is not None:
        lines.append(s)
    else:
        print(s)


def show_stats(stats: BacktestStats, return_string: bool = False) -> str | None:
    """
    Muestra las estadísticas del backtest formateadas en la consola.
    
    Args:
        stats: BacktestStats a mostrar
        return_string: Si True, devuelve el texto formateado en lugar de imprimirlo.
            Por defecto False (imprime en consola).
    
    Returns:
        Si return_string es True, el string con el reporte; si no, None.
    """
    lines: list[str] | None = [] if return_string else None

    _out("\n" + "=" * 80, lines)
    _out("RESULTADOS DEL BACKTEST", lines)
    _out("=" * 80, lines)

    if stats.validation_metrics:
        _out(f"\n🔍 MÉTRICAS DE FILTRADO", lines)
        _out("-" * 80, lines)
        vm = stats.validation_metrics
        _out(f"Total de buys: {vm.total_buy_transactions}", lines)
        _out(f"Buys aceptados: {vm.accepted_buy_transactions}", lines)
        _out(f"Tasa de aceptación (solo buys): {float(vm.filter_acceptance_rate):.2f}%", lines)
        _out(f"\nFiltros aplicados:", lines)

        # Mostrar métricas de cada validación
        for validation_name, metrics in vm.validation_metrics.items():
            enabled = metrics.get('enabled', False)
            rejected_count = metrics.get('rejected_count', 0)

            if validation_name == "min_sol_amount":
                _out(f"  - Filtro de monto mínimo SOL: {'Habilitado' if enabled else 'Deshabilitado'}", lines)
                if enabled:
                    thresholds = metrics.get('exchange_thresholds', {})
                    if thresholds:
                        _out(f"    * Umbrales: {', '.join([f'{k}: {v} SOL' for k, v in thresholds.items()])}", lines)
                    _out(f"    * Rechazos: {rejected_count}", lines)
            elif validation_name == "max_sol_amount":
                _out(f"  - Filtro de monto máximo SOL: {'Habilitado' if enabled else 'Deshabilitado'}", lines)
                if enabled:
                    thresholds = metrics.get('exchange_thresholds', {})
                    if thresholds:
                        _out(f"    * Umbrales: {', '.join([f'{k}: {v} SOL' for k, v in thresholds.items()])}", lines)
                    _out(f"    * Rechazos: {rejected_count}", lines)
            elif validation_name == "trade_activity":
                _out(f"  - Filtro de actividad: {'Habilitado' if enabled else 'Deshabilitado'}", lines)
                if enabled:
                    threshold = metrics.get('min_trade_count_threshold', 0)
                    window = metrics.get('activity_window_seconds', 0)
                    _out(f"    * Umbral mínimo: {threshold} trades", lines)
                    _out(f"    * Ventana de tiempo: {window} segundos", lines)
                    _out(f"    * Rechazos: {rejected_count}", lines)
            elif validation_name == "allowed_pools":
                _out(f"  - Filtro de pools permitidos: {'Habilitado' if enabled else 'Deshabilitado'}", lines)
                if enabled:
                    allowed_pools = metrics.get('allowed_pools', [])
                    if allowed_pools:
                        _out(f"    * Pools permitidos: {', '.join(allowed_pools)}", lines)
                    _out(f"    * Rechazos: {rejected_count}", lines)

    _out(f"\n📊 ESTADÍSTICAS GENERALES", lines)
    _out("-" * 80, lines)
    _out(f"Total de trades cerrados: {stats.total_trades}", lines)
    _out(f"Trades rentables: {stats.profitable_trades}", lines)
    _out(f"Trades con pérdida: {stats.losing_trades}", lines)
    _out(f"Trades break-even: {stats.break_even_trades}", lines)
    _out(f"Win rate: {float(stats.win_rate):.2f}%", lines)

    _out(f"\n💰 ANÁLISIS FINANCIERO", lines)
    _out("-" * 80, lines)
    _out(f"Total SOL invertido: {float(stats.total_sol_invested):.6f} SOL", lines)
    _out(f"Total SOL recuperado: {float(stats.total_sol_recovered):.6f} SOL", lines)
    _out(f"Ganancias totales: {float(stats.total_profit_sol):.6f} SOL", lines)
    _out(f"Pérdidas totales: {float(stats.total_loss_sol):.6f} SOL", lines)
    _out(f"Beneficio neto: {float(stats.net_profit_sol):.6f} SOL", lines)
    _out(f"ROI: {float(stats.roi):.2f}%", lines)

    _out(f"\n📈 PROMEDIOS", lines)
    _out("-" * 80, lines)
    _out(f"Promedio por trade: {float(stats.avg_profit_per_trade):.6f} SOL", lines)
    if stats.profitable_trades > 0:
        _out(f"Promedio en trades ganadores: {float(stats.avg_profit_per_winning_trade):.6f} SOL", lines)
    if stats.losing_trades > 0:
        _out(f"Promedio en trades perdedores: {float(stats.avg_loss_per_losing_trade):.6f} SOL", lines)

    if stats.best_trade:
        _out(f"\n🏆 MEJOR TRADE", lines)
        _out("-" * 80, lines)
        bt = stats.best_trade
        exchange_info = f" [{bt.exchange_name}]" if bt.exchange_name else ""
        _out(f"Token: {bt.token_symbol}{exchange_info} ({bt.token_address[:8]}...)", lines)
        _out(f"Compra: {bt.buy_hash[:16]}... (bloque {bt.buy_block})", lines)
        _out(f"Venta: {bt.sell_hash[:16]}... (bloque {bt.sell_block})", lines)
        _out(f"SOL invertido: {float(bt.sol_invested):.6f}", lines)
        _out(f"SOL recuperado: {float(bt.sol_recovered):.6f}", lines)
        _out(f"Ganancia: {float(bt.profit_loss_sol):.6f} SOL ({float(bt.profit_loss_pct):.2f}%)", lines)
        if bt.duration_seconds:
            hours = bt.duration_seconds / 3600
            _out(f"Duración: {hours:.2f} horas", lines)

    if stats.worst_trade:
        _out(f"\n📉 PEOR TRADE", lines)
        _out("-" * 80, lines)
        wt = stats.worst_trade
        exchange_info = f" [{wt.exchange_name}]" if wt.exchange_name else ""
        _out(f"Token: {wt.token_symbol}{exchange_info} ({wt.token_address[:8]}...)", lines)
        _out(f"Compra: {wt.buy_hash[:16]}... (bloque {wt.buy_block})", lines)
        _out(f"Venta: {wt.sell_hash[:16]}... (bloque {wt.sell_block})", lines)
        _out(f"SOL invertido: {float(wt.sol_invested):.6f}", lines)
        _out(f"SOL recuperado: {float(wt.sol_recovered):.6f}", lines)
        _out(f"Pérdida: {float(wt.profit_loss_sol):.6f} SOL ({float(wt.profit_loss_pct):.2f}%)", lines)
        if wt.duration_seconds:
            hours = wt.duration_seconds / 3600
            _out(f"Duración: {hours:.2f} horas", lines)

    if stats.open_positions:
        _out(f"\n⚠️  POSICIONES ABIERTAS RESTANTES: {len(stats.open_positions)}", lines)
        _out("-" * 80, lines)
        _out(f"Cantidad de posiciones abiertas: {len(stats.open_positions)}", lines)

    if stats.pool_stats:
        _out(f"\n🏊 MÉTRICAS POR POOL/EXCHANGE", lines)
        _out("-" * 80, lines)
        for exchange_name, pool_stat in stats.pool_stats.items():
            _out(f"\n📊 {exchange_name or 'Unknown'}", lines)
            _out(f"  Total trades: {pool_stat.total_trades}", lines)
            _out(f"  Trades rentables: {pool_stat.profitable_trades}", lines)
            _out(f"  Trades con pérdida: {pool_stat.losing_trades}", lines)
            _out(f"  Win rate: {float(pool_stat.win_rate):.2f}%", lines)
            _out(f"  SOL invertido: {float(pool_stat.total_sol_invested):.6f}", lines)
            _out(f"  SOL recuperado: {float(pool_stat.total_sol_recovered):.6f}", lines)
            _out(f"  Beneficio neto: {float(pool_stat.net_profit_sol):.6f} SOL", lines)
            _out(f"  ROI: {float(pool_stat.roi):.2f}%", lines)
            _out(f"  Promedio por trade: {float(pool_stat.avg_profit_per_trade):.6f} SOL", lines)
            if pool_stat.best_trade:
                _out(f"  Mejor trade: {float(pool_stat.best_trade.profit_loss_sol):.6f} SOL", lines)
            if pool_stat.worst_trade:
                _out(f"  Peor trade: {float(pool_stat.worst_trade.profit_loss_sol):.6f} SOL", lines)

    _out(f"\n📅 INFORMACIÓN DE FECHAS Y FILTROS", lines)
    _out("-" * 80, lines)
    # Rango completo de datos disponibles
    if stats.min_timestamp and stats.max_timestamp:
        min_dt = datetime.fromisoformat(stats.min_timestamp)
        max_dt = datetime.fromisoformat(stats.max_timestamp)
        duration = (max_dt - min_dt).days
        _out(f"Rango completo de datos disponibles:", lines)
        _out(f"  Fecha mínima: {stats.min_timestamp}", lines)
        _out(f"  Fecha máxima: {stats.max_timestamp}", lines)
        _out(f"  Duración: {duration} días", lines)
    else:
        _out("No hay información de fechas disponible", lines)

    # Filtros de fecha aplicados
    if stats.date_range_start or stats.date_range_end:
        _out(f"\nFiltros de fecha aplicados:", lines)
        _out(f"  Fecha inicio (filtro): {stats.date_range_start or 'Sin límite'}", lines)
        _out(f"  Fecha fin (filtro): {stats.date_range_end or 'Sin límite'}", lines)
        _out(f"  Transacciones antes del filtro: {stats.total_transactions_before_date_filter}", lines)
        _out(f"  Transacciones después del filtro: {stats.date_filtered_transactions}", lines)
        if stats.total_transactions_before_date_filter > 0:
            filter_percentage = (stats.date_filtered_transactions / stats.total_transactions_before_date_filter) * 100
            _out(f"  Porcentaje retenido: {filter_percentage:.2f}%", lines)
    else:
        _out(f"Sin filtros de fecha aplicados", lines)
        _out(f"  Total de transacciones: {stats.total_transactions_before_date_filter}", lines)

    _out("\n" + "=" * 80, lines)

    if return_string and lines is not None:
        return "\n".join(lines)
    return None
