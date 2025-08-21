# -*- coding: utf-8 -*-
"""
Calculadora de montos para Copy Trading

Este módulo contiene la lógica para calcular los montos a copiar basados
en diferentes modos de configuración (EXACT, PERCENTAGE, FIXED, DISTRIBUTED).
"""
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Callable, Any, Optional
from dataclasses import dataclass

from logging_system import AppLogger
from ..config import CopyTradingConfig, AmountMode, TraderConfig


@dataclass
class CalculationContext:
    """Contexto para el cálculo de montos a copiar"""
    trader_wallet: str
    original_amount: Decimal
    trader_config: Optional[TraderConfig]
    global_config: CopyTradingConfig


class CopyAmountCalculator:
    """
    Calculadora especializada para determinar montos a copiar en el sistema de copy trading.
    
    Responsabilidades:
    - Calcular montos basados en diferentes modos de configuración
    - Aplicar límites de posición (mínimo/máximo)
    - Manejar cálculos distribuidos para balance de inversión
    """

    def __init__(self, config: CopyTradingConfig):
        """Inicializa la calculadora con las estrategias de cálculo"""
        self._logger = AppLogger(self.__class__.__name__)

        self._global_config = config

        self._calculation_strategies: Dict[AmountMode, Callable[[CalculationContext], Decimal]] = {
            AmountMode.EXACT: self._calculate_exact_amount,
            AmountMode.PERCENTAGE: self._calculate_percentage_amount,
            AmountMode.FIXED: self._calculate_fixed_amount,
            AmountMode.DISTRIBUTED: self._calculate_distributed_amount,
        }

    def calculate_copy_amount(self, trader_wallet: str, original_amount: str) -> str:
        """
        Calcula el monto a copiar basado en la configuración usando Decimal
        
        Args:
            trader_wallet: Dirección del trader
            original_amount: Monto original del trade (como string)
            
        Returns:
            Monto calculado para copiar (como string)

        Exceptions:
            ValueError: Si el trader no se encuentra o no se puede calcular el monto
        """
        # Validar y preparar contexto
        context = self._prepare_calculation_context(trader_wallet, original_amount)

        # Determinar modo de cálculo
        mode = self._determine_calculation_mode(context)

        # Calcular monto base según el modo
        copy_amount = self._calculate_base_amount(context, mode)

        # Aplicar límites de posición
        copy_amount = self._apply_position_limits(context, copy_amount)

        # Formatear resultado
        result = format(copy_amount, "f")

        # Logging
        self._logger.debug(f"Monto calculado para trader {trader_wallet}: {original_amount} -> {result} (modo: {mode.value})")

        return result

    def _prepare_calculation_context(self, trader_wallet: str, original_amount: str) -> CalculationContext:
        """
        Prepara el contexto de cálculo validando la configuración
        
        Args:
            trader_wallet: Dirección del trader
            original_amount: Monto original como string
            
        Returns:
            Contexto de cálculo validado
            
        Raises:
            ValueError: Si el trader no se encuentra
        """
        # Validar trader
        trader_info = self._global_config.get_trader_info(trader_wallet)
        if not trader_info:
            error_msg = f"Trader not found: {trader_wallet}"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        trader_config = self._global_config.get_trader_config(trader_info)
        original_amount_dec = Decimal(original_amount)

        return CalculationContext(
            trader_wallet=trader_wallet,
            original_amount=original_amount_dec,
            trader_config=trader_config,
            global_config=self._global_config
        )

    def _determine_calculation_mode(self, context: CalculationContext) -> AmountMode:
        """
        Determina el modo de cálculo priorizando configuración individual sobre global
        
        Args:
            context: Contexto de cálculo
            
        Returns:
            Modo de cálculo a utilizar
        """
        if context.trader_config and context.trader_config.amount_mode:
            return context.trader_config.amount_mode
        return context.global_config.amount_mode

    def _calculate_base_amount(self, context: CalculationContext, mode: AmountMode) -> Decimal:
        """
        Calcula el monto base según el modo especificado
        
        Args:
            context: Contexto de cálculo
            mode: Modo de cálculo
            
        Returns:
            Monto base calculado
        """
        strategy = self._calculation_strategies.get(mode)
        if not strategy:
            self._logger.warning(f"Modo de cálculo no reconocido: {mode}, usando EXACT")
            return context.original_amount

        return strategy(context)

    def _calculate_exact_amount(self, context: CalculationContext) -> Decimal:
        """Calcula monto exacto (replica el monto original)"""
        return context.original_amount

    def _calculate_percentage_amount(self, context: CalculationContext) -> Decimal:
        """Calcula monto basado en porcentaje del original"""
        value = self._get_calculation_value(context)
        return (context.original_amount * (value / Decimal("100"))).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )

    def _calculate_fixed_amount(self, context: CalculationContext) -> Decimal:
        """Calcula monto fijo independiente del original"""
        return self._get_calculation_value(context)

    def _calculate_distributed_amount(self, context: CalculationContext) -> Decimal:
        """
        Calcula monto distribuido basado en balance de inversión
        
        Raises:
            ValueError: Si no se puede calcular el monto distribuido
        """
        # Obtener parámetros de distribución
        distribution_params = self._get_distribution_parameters(context)
        if not distribution_params:
            error_msg = "No se puede calcular el monto a copiar en modo DISTRIBUTED, no se encontró la configuración del trader o la configuración global"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        # Calcular monto distribuido
        balance_per_token = distribution_params['max_amount_to_invest'] / distribution_params['max_open_tokens']
        return balance_per_token / distribution_params['max_open_positions_per_token']

    def _get_calculation_value(self, context: CalculationContext) -> Decimal:
        """Obtiene el valor de cálculo priorizando configuración individual"""
        if context.trader_config and context.trader_config.amount_value:
            return Decimal(context.trader_config.amount_value)
        return Decimal(context.global_config.amount_value) if context.global_config.amount_value else Decimal("0")

    def _get_distribution_parameters(self, context: CalculationContext) -> Optional[Dict[str, Any]]:
        """
        Obtiene los parámetros de distribución priorizando configuración individual
        
        Returns:
            Diccionario con parámetros de distribución o None si no están disponibles
        """
        # Intentar con configuración individual
        if (context.trader_config and 
            context.trader_config.max_amount_to_invest and
            context.trader_config.max_open_tokens and
            context.trader_config.max_open_positions_per_token and
            context.trader_config.use_balanced_allocation):

            return {
                'max_amount_to_invest': Decimal(context.trader_config.max_amount_to_invest),
                'max_open_tokens': context.trader_config.max_open_tokens,
                'max_open_positions_per_token': context.trader_config.max_open_positions_per_token
            }

        # Intentar con configuración global
        if (not context.trader_config and
            context.global_config.max_amount_to_invest_per_trader and
            context.global_config.max_open_tokens_per_trader and
            context.global_config.max_open_positions_per_token_per_trader and
            context.global_config.use_balanced_allocation_per_trader):

            return {
                'max_amount_to_invest': Decimal(context.global_config.max_amount_to_invest_per_trader),
                'max_open_tokens': context.global_config.max_open_tokens_per_trader,
                'max_open_positions_per_token': context.global_config.max_open_positions_per_token_per_trader
            }

    def _apply_position_limits(self, context: CalculationContext, amount: Decimal) -> Decimal:
        """
        Aplica límites de posición (mínimo/máximo) al monto calculado
        
        Args:
            context: Contexto de cálculo
            amount: Monto a limitar
            
        Returns:
            Monto con límites aplicados
        """
        # Aplicar límite máximo
        amount = self._apply_max_limit(context, amount)

        # Aplicar límite mínimo
        amount = self._apply_min_limit(context, amount)

        return amount

    def _apply_max_limit(self, context: CalculationContext, amount: Decimal) -> Decimal:
        """Aplica límite máximo de posición"""
        max_limit = self._get_max_position_limit(context)
        if max_limit is not None:
            return min(amount, max_limit)
        return amount

    def _apply_min_limit(self, context: CalculationContext, amount: Decimal) -> Decimal:
        """Aplica límite mínimo de posición"""
        min_limit = self._get_min_position_limit(context)
        if min_limit is not None:
            return max(amount, min_limit)
        return amount

    def _get_max_position_limit(self, context: CalculationContext) -> Optional[Decimal]:
        """Obtiene el límite máximo de posición"""
        if (context.trader_config and 
            context.trader_config.adjust_position_size and 
            context.trader_config.max_position_size):
            return Decimal(context.trader_config.max_position_size)

        if (context.global_config.max_position_size and 
            context.global_config.adjust_position_size):
            return Decimal(context.global_config.max_position_size)

    def _get_min_position_limit(self, context: CalculationContext) -> Optional[Decimal]:
        """Obtiene el límite mínimo de posición"""
        if (context.trader_config and 
            context.trader_config.adjust_position_size and 
            context.trader_config.min_position_size):
            return Decimal(context.trader_config.min_position_size)

        if (context.global_config.min_position_size and 
            context.global_config.adjust_position_size):
            return Decimal(context.global_config.min_position_size)
