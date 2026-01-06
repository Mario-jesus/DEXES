# -*- coding: utf-8 -*-
"""
Funciones helper para generar parámetros de validadores.

Este módulo proporciona funciones que facilitan la generación de listas de parámetros
para los diferentes builders de validadores, reduciendo código repetitivo.
"""
from typing import List, Dict, Any, Optional
from calendar import monthrange


def generate_min_sol_amount_params(start: float = 0.5, end: float = 7.0, step: float = 0.5) -> List[Dict[str, str]]:
    """
    Genera parámetros para build_min_sol_amount_validator.

    Args:
        start: Valor inicial (inclusive). Default: 0.5
        end: Valor final (inclusive). Default: 7.0
        step: Incremento entre valores. Default: 0.5

    Returns:
        Lista de diccionarios con parámetros {"sol_amount": "valor"}

    Example:
        >>> params = generate_min_sol_amount_params(start=0.5, end=2.0, step=0.5)
        >>> # Retorna: [{"sol_amount": "0.5"}, {"sol_amount": "1.0"}, {"sol_amount": "1.5"}, {"sol_amount": "2.0"}]
    """
    params = []
    current = start
    while current <= end:
        params.append({"sol_amount": str(current)})
        current += step
        # Evitar problemas de precisión de punto flotante
        current = round(current, 2)
    return params


def generate_range_sol_amount_params(start: float = 1.0, end: float = 7.0, step: float = 1.0) -> List[Dict[str, str]]:
    """
    Genera parámetros para build_in_range_sol_amount_validator o build_outside_range_sol_amount_validator.

    Genera rangos consecutivos: [start, start+step], [start+step, start+2*step], etc.

    Args:
        start: Valor inicial del primer rango. Default: 1.0
        end: Valor final del último rango. Default: 7.0
        step: Tamaño del rango y paso entre rangos. Default: 1.0

    Returns:
        Lista de diccionarios con parámetros {"min_sol_amount": "min", "max_sol_amount": "max"}

    Example:
        >>> params = generate_range_sol_amount_params(start=1.0, end=4.0, step=1.0)
        >>> # Retorna: [
        >>> #     {"min_sol_amount": "1.0", "max_sol_amount": "2.0"},
        >>> #     {"min_sol_amount": "2.0", "max_sol_amount": "3.0"},
        >>> #     {"min_sol_amount": "3.0", "max_sol_amount": "4.0"}
        >>> # ]
    """
    params = []
    current = start
    while current + step <= end:
        params.append({
            "min_sol_amount": str(current),
            "max_sol_amount": str(current + step)
        })
        current += step
    return params


def generate_trade_activity_params(
    min_thresholds: Optional[List[int]] = None,
    activity_windows: Optional[List[int]] = None
) -> List[Dict[str, int]]:
    """
    Genera parámetros para build_trade_activity_validator.

    Genera todas las combinaciones de min_trade_count_threshold y activity_window_seconds.

    Args:
        min_thresholds: Lista de valores para min_trade_count_threshold.
                        Default: [2, 3, 4, 5]
        activity_windows: Lista de valores para activity_window_seconds (en segundos).
                        Default: [30, 60, 120, 180, 240, 300]

    Returns:
        Lista de diccionarios con todas las combinaciones de parámetros

    Example:
        >>> params = generate_trade_activity_params(
        >>>     min_thresholds=[2, 3],
        >>>     activity_windows=[30, 60]
        >>> )
        >>> # Retorna: [
        >>> #     {"min_trade_count_threshold": 2, "activity_window_seconds": 30},
        >>> #     {"min_trade_count_threshold": 2, "activity_window_seconds": 60},
        >>> #     {"min_trade_count_threshold": 3, "activity_window_seconds": 30},
        >>> #     {"min_trade_count_threshold": 3, "activity_window_seconds": 60}
        >>> # ]
    """
    if min_thresholds is None:
        min_thresholds = [2, 3, 4, 5]
    if activity_windows is None:
        activity_windows = [30, 60, 120, 180, 240, 300]

    return [
        {"min_trade_count_threshold": threshold, "activity_window_seconds": window}
        for threshold in min_thresholds
        for window in activity_windows
    ]


def generate_monthly_date_ranges(year: int = 2025) -> List[tuple[str, str]]:
    """
    Genera rangos de fechas mensuales para un año.

    Args:
        year: Año para generar los rangos. Default: 2025

    Returns:
        Lista de tuplas (start_date, end_date) para cada mes del año en formato "YYYY-MM-DD"

    Example:
        >>> ranges = generate_monthly_date_ranges(year=2025)
        >>> # Retorna: [
        >>> #     ("2025-01-01", "2025-01-31"),
        >>> #     ("2025-02-01", "2025-02-28"),
        >>> #     ...
        >>> #     ("2025-12-01", "2025-12-31")
        >>> # ]
    """
    date_ranges = []
    for month in range(1, 13):
        _, last_day = monthrange(year, month)
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year}-{month:02d}-{last_day}"
        date_ranges.append((start_date, end_date))
    return date_ranges
