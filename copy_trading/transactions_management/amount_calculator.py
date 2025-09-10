# -*- coding: utf-8 -*-
"""
Calculadora de montos para Copy Trading

Este módulo contiene la lógica para calcular los montos a copiar basados
en diferentes modos de configuración (EXACT, PERCENTAGE, FIXED, DISTRIBUTED).
"""
import asyncio
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Callable, Any, Optional, Literal, Tuple, Union
from dataclasses import dataclass
from cachetools import TTLCache
from collections import defaultdict

from logging_system import AppLogger
from ..config import CopyTradingConfig, AmountMode, TraderConfig
from ..position_management.queues import OpenPositionQueue
from ..position_management.models import TraderTradeData, PositionStatus
from ..position_management.services.position_calculation_service import PositionCalculationService
from ..events import (
    PositionEventBus,
    PositionCloseExecutedEvent,
    PositionValidationFailedEvent,
    PositionExecutionFailedEvent
)


@dataclass(slots=True)
class CalculationContext:
    """Contexto para el cálculo de montos a copiar"""
    position_id: str
    trader_wallet: str
    token_address: str
    original_amount: Decimal
    action: Literal["buy", "sell"]
    denominate_in_sol: bool
    trader_config: Optional[TraderConfig]
    global_config: CopyTradingConfig


@dataclass(slots=True)
class OpenPositionClosureAttempt:
    """Intento de cierre de posición"""
    close_position_id: str
    status: Literal["pending", "closed", "partially_closed", "failed"] = "pending"


class CopyAmountCalculator:
    """
    Calculadora especializada para determinar montos a copiar en el sistema de copy trading.
    
    Responsabilidades:
    - Calcular montos basados en diferentes modos de configuración
    - Aplicar límites de posición (mínimo/máximo)
    - Manejar cálculos distribuidos para balance de inversión
    """

    def __init__(self, config: CopyTradingConfig, position_event_bus: PositionEventBus, open_position_queue: Optional[OpenPositionQueue] = None):
        """Inicializa la calculadora con las estrategias de cálculo"""
        self._logger = AppLogger(self.__class__.__name__)
        self._logger.info("Inicializando calculadora de montos para copy trading")

        self._global_config = config
        self._open_position_queue = open_position_queue

        self._logger.debug(f"Configuración global: modo={config.amount_mode.value}, valor={config.amount_value}")
        self._logger.debug(f"Cola de posiciones abiertas: {'disponible' if open_position_queue else 'no disponible'}")

        # (trader_wallet, token_address) -> TTLCache[open_position_id, OpenPositionClosureAttempt]
        self._open_position_closure_attempts: defaultdict[Tuple[str, str], TTLCache[str, OpenPositionClosureAttempt]] = defaultdict(lambda: TTLCache(maxsize=1000, ttl=600))

        # Lock para evitar race conditions
        self._lock = asyncio.Lock()

        # Suscribirse a eventos
        position_event_bus.on_position_close_executed(self._on_position_close_executed)
        position_event_bus.on_position_validation_failed(self._on_position_failed)
        position_event_bus.on_position_execution_failed(self._on_position_failed)

        self._logger.debug("Calculadora de montos inicializada correctamente con suscripciones a eventos")

        self._calculation_strategies_for_buy: Dict[AmountMode, Callable[[CalculationContext], Decimal]] = {
            AmountMode.EXACT: self._calculate_exact_amount_to_buy,
            AmountMode.PERCENTAGE: self._calculate_percentage_amount_to_buy,
            AmountMode.FIXED: self._calculate_fixed_amount_to_buy,
            AmountMode.DISTRIBUTED: self._calculate_distributed_amount_to_buy,
        }

        self._calculation_strategies_for_sell: Dict[AmountMode, Callable[[CalculationContext], Decimal]] = {
            AmountMode.EXACT: self._calculate_exact_amount_to_sell,
            AmountMode.PERCENTAGE: self._calculate_percentage_amount_to_sell,
            AmountMode.FIXED: self._calculate_fixed_amount_to_sell,
            AmountMode.DISTRIBUTED: self._calculate_distributed_amount_to_sell,
        }

    def set_open_position_queue(self, open_position_queue: Optional[OpenPositionQueue]) -> None:
        self._open_position_queue = open_position_queue

    async def _on_position_close_executed(self, event: PositionCloseExecutedEvent) -> None:
        """
        Actualiza el estado de los intentos de cierre de posición procesados
        """
        self._logger.debug(f"Procesando evento de cierre de posición: {event.position_id} para trader {event.trader_wallet}")
        try:
            async with self._lock:
                for index, open_position_id in enumerate(event.processed_open_position_ids):
                    if open_position_id in self._open_position_closure_attempts[event.trader_wallet, event.token_address]:
                        continue

                    attempt = self._open_position_closure_attempts[event.trader_wallet, event.token_address][open_position_id]
                    if index == len(event.processed_open_position_ids) - 1 and event.last_partial_closure:
                        attempt.status = "partially_closed"
                    elif event.status == "success":
                        attempt.status = "closed"
                    else:
                        attempt.status = "failed"

                    attempt.close_position_id = event.position_id
                    self._open_position_closure_attempts[event.trader_wallet, event.token_address][open_position_id] = attempt

            self._logger.debug(f"Actualizados {len(event.processed_open_position_ids)} intentos de cierre de posición")
        except Exception as e:
            self._logger.error(f"Error al actualizar el estado de los intentos de cierre de posición procesados: {e}", exc_info=True)

    async def _on_position_failed(self, event: Union[PositionValidationFailedEvent, PositionExecutionFailedEvent]) -> None:
        self._logger.info(f"Posición falló: {event.position_id} para trader {event.trader_wallet} - {type(event).__name__}")
        position_closure_attempts = self._open_position_closure_attempts[event.trader_wallet, event.token_address]
        for open_position_id, attempt in position_closure_attempts.items():
            if event.position_id == attempt.close_position_id:
                attempt.status = "failed"
                position_closure_attempts[open_position_id] = attempt
                self._logger.debug(f"Marcado intento de cierre como fallido: {open_position_id}")
                break

    def calculate_copy_amount(self, trade_data: TraderTradeData) -> str:
        """
        Calcula el monto a copiar basado en la configuración usando Decimal
        
        Args:
            trader_wallet: Dirección del trader
            original_amount: Monto original del trade (como string)
            action: Accion del trade (buy o sell)
            denominate_in_sol: Si el monto se debe denominar en SOL
            
        Returns:
            Monto calculado para copiar (como string)

        Exceptions:
            ValueError: Si el trader no se encuentra o no se puede calcular el monto
        """
        # Validar y preparar contexto
        context = self._prepare_calculation_context(
            position_id=trade_data.id,
            trader_wallet=trade_data.trader_wallet,
            token_address=trade_data.token_address,
            original_amount=trade_data.amount_sol if trade_data.side == 'buy' else trade_data.token_amount,
            action=trade_data.side,
            denominate_in_sol=True if trade_data.side == 'buy' else False
        )

        # Determinar modo de cálculo
        mode = self._determine_calculation_mode(context)
        self._logger.debug(f"Modo de cálculo determinado: {mode.value}")

        # Calcular monto base según el modo
        copy_amount = self._calculate_base_amount(context, mode)
        self._logger.debug(f"Monto base calculado: {copy_amount}")

        # Aplicar límites de posición
        copy_amount = self._apply_position_limits(context, copy_amount)
        self._logger.debug(f"Monto final después de límites: {copy_amount}")

        # Formatear resultado
        result = format(copy_amount, "f")

        # Logging
        self._logger.debug(f"Monto calculado para trader {trade_data.trader_wallet}: {result} (modo: {mode.value}, acción: {trade_data.side})")

        return result

    def _prepare_calculation_context(self,
        position_id: str,
        trader_wallet: str,
        token_address: str,
        original_amount: str,
        *,
        action: Literal["buy", "sell"],
        denominate_in_sol: bool
    ) -> CalculationContext:
        """
        Prepara el contexto de cálculo validando la configuración
        
        Args:
            trader_wallet: Dirección del trader
            original_amount: Monto original como string
            action: Accion del trade (buy o sell)
            denominate_in_sol: Si el monto se debe denominar en SOL
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

        self._logger.debug(f"Trader encontrado: {trader_wallet}, acción: {action}, monto original: {original_amount}")

        trader_config = self._global_config.get_trader_config(trader_info)
        original_amount_dec = Decimal(original_amount)

        return CalculationContext(
            position_id=position_id,
            trader_wallet=trader_wallet,
            original_amount=original_amount_dec,
            token_address=token_address,
            action=action,
            denominate_in_sol=denominate_in_sol,
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
        if context.action == "buy":
            strategy = self._calculation_strategies_for_buy.get(mode)
        else:
            strategy = self._calculation_strategies_for_sell.get(mode)

        if not strategy:
            self._logger.warning(f"Modo de cálculo no reconocido: {mode}, usando EXACT")
            return context.original_amount

        self._logger.debug(f"Aplicando estrategia de cálculo: {strategy.__name__}")

        return strategy(context)

    def _calculate_exact_amount_to_buy(self, context: CalculationContext) -> Decimal:
        """Calcula monto exacto (replica el monto original)"""
        return context.original_amount

    def _calculate_exact_amount_to_sell(self, context: CalculationContext) -> Decimal:
        """Calcula monto exacto (replica el monto original)"""
        return self._calculate_exact_amount_to_buy(context)

    def _calculate_percentage_amount_to_buy(self, context: CalculationContext) -> Decimal:
        """Calcula monto basado en porcentaje del original"""
        value = self._get_calculation_value(context)
        return context.original_amount * (value / Decimal("100"))

    def _calculate_percentage_amount_to_sell(self, context: CalculationContext) -> Decimal:
        """Calcula monto basado en porcentaje del original"""
        return self._calculate_percentage_amount_to_buy(context)

    def _calculate_fixed_amount_to_buy(self, context: CalculationContext) -> Decimal:
        """Calcula monto fijo independiente del original"""
        return self._get_calculation_value(context)

    def _calculate_fixed_amount_to_sell(self, context: CalculationContext) -> Decimal:
        """Calcula monto fijo independiente del original"""
        if not self._open_position_queue:
            self._logger.warning("No hay cola de posiciones abiertas disponible para cálculo de venta")
            return Decimal('0')

        self._logger.debug(
            f"Calculando monto fijo para venta: trader={context.trader_wallet}, token={context.token_address}, "
            f"position_id={getattr(context, 'position_id', None)}"
        )

        positions_to_sell = self._open_position_queue.get_open_positions(context.trader_wallet, context.token_address)
        self._logger.debug(
            f"Obtenidas {len(positions_to_sell)} posiciones abiertas para vender "
            f"(trader={context.trader_wallet}, token={context.token_address})"
        )

        close_tokens_amount = Decimal('0')

        for idx, position in enumerate(positions_to_sell):
            self._logger.debug(
                f"Procesando posición {idx+1}/{len(positions_to_sell)}: id={position.id}, "
                f"status={getattr(position, 'status', None)}, "
                f"is_fully_closed={getattr(position, 'is_fully_closed', lambda: None)()}"
            )

            closure_attempts = self._open_position_closure_attempts.get((context.trader_wallet, context.token_address), {})
            if position.id in closure_attempts:
                attempt_to_close = closure_attempts[position.id]
                self._logger.debug(
                    f"Intento previo de cierre encontrado para posición {position.id}: status={attempt_to_close.status}"
                )
                if attempt_to_close.status in ["pending", "closed"]:
                    self._logger.debug(f"Saltando posición {position.id} con estado {attempt_to_close.status}")
                    continue

            if position.status == PositionStatus.OPEN:
                remaining_tokens = Decimal(PositionCalculationService.calculate_remaining_tokens(position, exact=True))
                self._logger.debug(
                    f"Posición {position.id} está ABIERTA. Tokens restantes para cerrar: {remaining_tokens}"
                )
                close_tokens_amount += remaining_tokens
                self._logger.debug(
                    f"Registrando intento de cierre para posición {position.id} (open). close_position_id={context.position_id}"
                )
                self._open_position_closure_attempts[context.trader_wallet, context.token_address][position.id] = OpenPositionClosureAttempt(
                    close_position_id=context.position_id
                )
                self._logger.debug(
                    f"Agregada posición abierta {position.id}: {remaining_tokens} tokens. "
                    f"Total acumulado: {close_tokens_amount}"
                )
                break
            elif not position.is_fully_closed():
                remaining_tokens = Decimal(PositionCalculationService.calculate_remaining_tokens(position, exact=True))
                self._logger.debug(
                    f"Posición {position.id} está PARCIALMENTE CERRADA. Tokens restantes para cerrar: {remaining_tokens}"
                )
                close_tokens_amount += remaining_tokens
                self._logger.debug(
                    f"Registrando intento de cierre para posición {position.id} (partial). close_position_id={context.position_id}"
                )
                self._open_position_closure_attempts[context.trader_wallet, context.token_address][position.id] = OpenPositionClosureAttempt(
                    close_position_id=context.position_id
                )
                self._logger.debug(
                    f"Agregada posición parcialmente cerrada {position.id}: {remaining_tokens} tokens. "
                    f"Total acumulado: {close_tokens_amount}"
                )

        self._logger.debug(
            f"Monto total calculado para venta (trader={context.trader_wallet}, token={context.token_address}): {close_tokens_amount} tokens"
        )
        return close_tokens_amount

    def _calculate_distributed_amount_to_buy(self, context: CalculationContext) -> Decimal:
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

        self._logger.debug(f"Parámetros de distribución: {distribution_params}")

        # Calcular monto distribuido
        balance_per_token = distribution_params['max_amount_to_invest'] / distribution_params['max_open_tokens']
        distributed_amount = balance_per_token / distribution_params['max_open_positions_per_token']

        self._logger.debug(f"Cálculo distribuido: balance por token={balance_per_token}, monto distribuido={distributed_amount}")
        return distributed_amount

    def _calculate_distributed_amount_to_sell(self, context: CalculationContext) -> Decimal:
        return self._calculate_distributed_amount_to_buy(context)

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
        original_amount = amount
        amount = self._apply_max_limit(context, amount)
        if amount != original_amount:
            self._logger.debug(f"Aplicado límite máximo: {original_amount} -> {amount}")

        # Aplicar límite mínimo
        original_amount = amount
        amount = self._apply_min_limit(context, amount)
        if amount != original_amount:
            self._logger.debug(f"Aplicado límite mínimo: {original_amount} -> {amount}")

        exp = Decimal("0.000000001" if context.denominate_in_sol else "0.000001")
        final_amount = amount.quantize(exp, rounding=ROUND_DOWN).normalize()

        if final_amount != amount:
            self._logger.debug(f"Redondeado monto: {amount} -> {final_amount} (precisión: {exp})")

        return final_amount

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
