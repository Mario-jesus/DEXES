# -*- coding: utf-8 -*-
"""
Funciones constructoras (builders) para crear BacktestValidator comunes.

Este módulo proporciona funciones que facilitan la creación de validadores
para diferentes estrategias de backtest parametrizadas.
"""
from typing import Dict, Any
from ...domain.services.backtest_validator import BacktestValidator
from ...domain.validations import (
    MinSolAmountValidation,
    MaxSolAmountValidation,
    TradeActivityValidation,
    AllowedPoolsValidation
)


def build_min_sol_amount_validator(params: Dict[str, Any]) -> BacktestValidator:
    """
    Construye un BacktestValidator con validación de monto mínimo de SOL.

    Esta validación acepta únicamente transacciones de compra cuyo monto de SOL sea mayor o igual
    al umbral mínimo especificado. Las transacciones de venta no requieren esta validación.

    Rechaza cualquier transacción de compra cuyo monto sea menor al umbral mínimo configurado.

    Args:
        params: Diccionario que debe contener la clave "sol_amount" con el valor
            del monto mínimo de SOL a validar (aplicado a ambos exchanges: pump_swap y pump_fun).

    Returns:
        BacktestValidator configurado con MinSolAmountValidation y AllowedPoolsValidation.

    Raises:
        ValueError: Si "sol_amount" no está presente en params.
    """
    if "sol_amount" not in params:
        raise ValueError("sol_amount is required in params")

    return BacktestValidator([
        MinSolAmountValidation(
            exchange_thresholds={
                "pump_swap": params["sol_amount"],
                "pump_fun": params["sol_amount"]
            },
            enabled=True
        ),
        AllowedPoolsValidation(
            allowed_pools=["pump_swap", "pump_fun"],
            enabled=True
        )
    ])


def build_in_range_sol_amount_validator(params: Dict[str, Any]) -> BacktestValidator:
    """
    Construye un BacktestValidator que acepta solo trades con montos dentro del rango [min, max].

    Esta validación acepta únicamente transacciones cuyo monto de SOL esté dentro del rango
    [min_sol_amount, max_sol_amount], es decir, que cumplan ambas condiciones:
    - Mayor o igual al monto mínimo especificado, Y
    - Menor o igual al monto máximo especificado
    
    Rechaza cualquier transacción cuyo monto esté fuera del rango [min_sol_amount, max_sol_amount].

    Args:
        params: Diccionario que debe contener las claves "min_sol_amount" y "max_sol_amount"
            con los valores de los montos mínimo y máximo de SOL que definen el rango aceptado.

    Returns:
        BacktestValidator configurado para aceptar solo montos dentro del rango especificado
        y con AllowedPoolsValidation.

    Raises:
        ValueError: Si "min_sol_amount" o "max_sol_amount" no están presentes en params.
    """
    if "min_sol_amount" not in params or "max_sol_amount" not in params:
        raise ValueError("min_sol_amount and max_sol_amount are required in params")

    return BacktestValidator([
        MinSolAmountValidation(
            exchange_thresholds={
                "pump_swap": params["min_sol_amount"],
                "pump_fun": params["min_sol_amount"]
            },
            enabled=True
        ),
        MaxSolAmountValidation(
            exchange_thresholds={
                "pump_swap": params["max_sol_amount"],
                "pump_fun": params["max_sol_amount"]
            },
            enabled=True
        ),
        AllowedPoolsValidation(
            allowed_pools=["pump_swap", "pump_fun"],
            enabled=True
        )
    ])


def build_outside_range_sol_amount_validator(params: Dict[str, Any]) -> BacktestValidator:
    """
    Construye un BacktestValidator que acepta solo trades con montos fuera del rango [min, max].

    Esta validación acepta únicamente transacciones cuyo monto de SOL sea:
    - Menor al monto mínimo especificado, O
    - Mayor al monto máximo especificado
    
    Rechaza cualquier transacción cuyo monto esté dentro del rango [min_sol_amount, max_sol_amount].

    Args:
        params: Diccionario que debe contener las claves "min_sol_amount" y "max_sol_amount"
            con los valores de los montos mínimo y máximo de SOL que definen el rango excluido.

    Returns:
        BacktestValidator configurado para aceptar solo montos fuera del rango especificado
        y con AllowedPoolsValidation.

    Raises:
        ValueError: Si "min_sol_amount" o "max_sol_amount" no están presentes en params.
    """
    if "min_sol_amount" not in params or "max_sol_amount" not in params:
        raise ValueError("min_sol_amount and max_sol_amount are required in params")

    return BacktestValidator([
        {
            "validations": [
                MaxSolAmountValidation(
                    exchange_thresholds={
                        "pump_swap": params["min_sol_amount"],
                        "pump_fun": params["min_sol_amount"]
                    },
                    enabled=True
                ),
                MinSolAmountValidation(
                    exchange_thresholds={
                        "pump_swap": params["max_sol_amount"],
                        "pump_fun": params["max_sol_amount"]
                    },
                    enabled=True
                )
            ],
            "logical_operator": "OR"
        },
        AllowedPoolsValidation(
            allowed_pools=["pump_swap", "pump_fun"],
            enabled=True
        )
    ])


def build_trade_activity_validator(params: Dict[str, Any]) -> BacktestValidator:
    """
    Construye un BacktestValidator con validación de actividad de trading.

    Esta validación acepta únicamente transacciones de compra que cumplan con el requisito
    de actividad: debe haber al menos un número mínimo de trades del mismo token dentro de
    una ventana de tiempo especificada. Las transacciones de venta no requieren esta validación.

    La validación cuenta los trades por token dentro de la ventana de tiempo y acepta el trade
    solo si el conteo alcanza o supera el umbral mínimo especificado.

    Args:
        params: Diccionario que debe contener las claves:
            - "min_trade_count_threshold": Número mínimo de trades requeridos dentro de la ventana.
            - "activity_window_seconds": Ventana de tiempo en segundos para contar los trades.

    Returns:
        BacktestValidator configurado con TradeActivityValidation y AllowedPoolsValidation.

    Raises:
        ValueError: Si "min_trade_count_threshold" o "activity_window_seconds" no están presentes en params.
    """
    if "min_trade_count_threshold" not in params or "activity_window_seconds" not in params:
        raise ValueError("min_trade_count_threshold and activity_window_seconds are required in params")

    return BacktestValidator([
        TradeActivityValidation(
            min_trade_count_threshold=params["min_trade_count_threshold"],
            activity_window_seconds=params["activity_window_seconds"],
            enabled=True
        ),
        AllowedPoolsValidation(
            allowed_pools=["pump_swap", "pump_fun"],
            enabled=True
        )
    ])
