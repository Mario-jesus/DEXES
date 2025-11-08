# -*- coding: utf-8 -*-
"""
Calculadora de montos para Copy Trading

Este módulo contiene la lógica para calcular los montos a copiar basados
en diferentes modos de configuración (EXACT, PERCENTAGE, FIXED, DISTRIBUTED).
"""
import asyncio
from decimal import Decimal, ROUND_DOWN
from typing import Dict, cast, Any, Optional, Literal, Tuple, Union, TYPE_CHECKING, Protocol
from dataclasses import dataclass
from cachetools import TTLCache
from collections import defaultdict
from time import time

from logging_system import AppLogger
from ..config import CopyTradingConfig, AmountMode, TraderConfig
from ..position_management.models import TraderTradeData, PositionStatus
from ..position_management.services.position_calculation_service import PositionCalculationService

if TYPE_CHECKING:
    from ..position_management.queues import OpenPositionQueue
    from copy_trading.protocols import SolanaTxAnalyzerProtocol
    from ..balance_management import BalanceManager
    from ..events import (
        PositionEventBus,
        PositionCloseExecutedEvent,
        PositionValidationFailedEvent,
        PositionExecutionFailedEvent
    )


class CalculationStrategy(Protocol):
    """Protocolo para estrategias de cálculo que pueden ser síncronas o asíncronas"""
    def __call__(self, context: 'CalculationContext') -> Decimal:
        ...


@dataclass(slots=True)
class CalculationContext:
    """Contexto para el cálculo de montos a copiar"""
    position_id: str
    trader_wallet: str
    token_address: str
    original_amount: Decimal
    original_sol_amount: Decimal
    original_token_amount: Decimal
    original_token_balance: Decimal
    action: Literal["buy", "sell"]
    denominate_in_sol: bool
    trader_config: Optional[TraderConfig]
    global_config: CopyTradingConfig
    trader_balance: Optional[Decimal] = None
    own_balance: Optional[Decimal] = None
    original_percentage: Optional[str] = None


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

    def __init__(
        self,
        config: CopyTradingConfig,
        position_event_bus: "PositionEventBus",
        open_position_queue: Optional["OpenPositionQueue"] = None,
        solana_analyzer: Optional["SolanaTxAnalyzerProtocol"] = None,
        balance_manager: Optional["BalanceManager"] = None
    ):
        """Inicializa la calculadora con las estrategias de cálculo"""
        self._logger = AppLogger(self.__class__.__name__)
        self._logger.info("Inicializando calculadora de montos para copy trading")

        self._global_config = config
        self._open_position_queue = open_position_queue
        self._solana_analyzer = solana_analyzer
        self._balance_manager = balance_manager

        self._logger.debug(f"Configuración global: modo={config.amount_mode.value}, valor={config.amount_value}")
        self._logger.debug(f"Cola de posiciones abiertas: {'disponible' if open_position_queue else 'no disponible'}")

        # (trader_wallet, token_address) -> TTLCache[open_position_id, OpenPositionClosureAttempt]
        self._open_position_closure_attempts: defaultdict[Tuple[str, str], TTLCache[str, OpenPositionClosureAttempt]] = defaultdict(lambda: TTLCache(maxsize=1000, ttl=600))

        # TTLCache[trader_wallet, balance]
        self._trader_balances: TTLCache[str, str] = TTLCache(maxsize=1000, ttl=30)

        # (trader_wallet, token_address) -> monto original en SOL del primer trade de apertura
        # Se reinicia cuando detectamos que no hay posiciones abiertas (nueva primera apertura)
        self._first_trade_original_amounts: Dict[Tuple[str, str], Decimal] = {}

        # Lock para evitar race conditions
        self._lock = asyncio.Lock()

        # Suscribirse a eventos
        position_event_bus.on_position_close_executed(self._on_position_close_executed)
        position_event_bus.on_position_validation_failed(self._on_position_failed)
        position_event_bus.on_position_execution_failed(self._on_position_failed)

        self._logger.debug("Calculadora de montos inicializada correctamente con suscripciones a eventos")

        self._calculation_strategies_for_buy: Dict[AmountMode, CalculationStrategy] = {
            AmountMode.EXACT: self._calculate_exact_amount_to_buy,
            AmountMode.PERCENTAGE: self._calculate_percentage_amount_to_buy,
            AmountMode.PERCENTAGE_OF_BALANCE: self._calculate_percentage_of_balance_amount_to_buy,
            AmountMode.FIXED: self._calculate_fixed_amount_to_buy,
            AmountMode.DISTRIBUTED: self._calculate_distributed_amount_to_buy,
        }

        self._calculation_strategies_for_sell: Dict[AmountMode, CalculationStrategy] = {
            AmountMode.EXACT: self._calculate_exact_amount_to_sell,
            AmountMode.PERCENTAGE: self._calculate_percentage_amount_to_sell,
            AmountMode.PERCENTAGE_OF_BALANCE: self._calculate_percentage_of_balance_amount_to_sell,
            AmountMode.FIXED: self._calculate_fixed_amount_to_sell,
            AmountMode.DISTRIBUTED: self._calculate_distributed_amount_to_sell,
        }

    def set_open_position_queue(self, open_position_queue: Optional["OpenPositionQueue"]) -> None:
        self._open_position_queue = open_position_queue

    async def _on_position_close_executed(self, event: "PositionCloseExecutedEvent") -> None:
        """
        Actualiza el estado de los intentos de cierre de posición procesados
        """
        self._logger.info(f"Procesando evento de cierre de posición: {event.position_id} para trader {event.trader_wallet} (token: {event.token_address})")
        try:
            async with self._lock:
                cache = self._open_position_closure_attempts[event.trader_wallet, event.token_address]
                for index, open_position_id in enumerate(event.processed_open_position_ids):
                    if open_position_id not in cache:
                        self._logger.debug(f"Intento de cierre no encontrado para posición {open_position_id} en evento {event.position_id}; omitiendo actualización")
                        continue

                    attempt = cache[open_position_id]
                    if index == len(event.processed_open_position_ids) - 1 and event.last_partial_closure:
                        attempt.status = "partially_closed"
                        self._logger.debug(f"Posición {open_position_id} marcada como parcialmente cerrada por evento {event.position_id}")
                    elif event.status == "success":
                        attempt.status = "closed"
                        self._logger.debug(f"Posición {open_position_id} marcada como cerrada exitosamente por evento {event.position_id}")
                    else:
                        attempt.status = "failed"
                        self._logger.warning(f"Posición {open_position_id} marcada como fallida por evento {event.position_id}")

                    attempt.close_position_id = event.position_id
                    cache[open_position_id] = attempt

            self._logger.info(f"Actualizados {len(event.processed_open_position_ids)} intentos de cierre de posición para evento {event.position_id}")
        except Exception as e:
            self._logger.error(f"Error al actualizar el estado de los intentos de cierre de posición procesados para evento {event.position_id}: {e}", exc_info=True)

    async def _on_position_failed(self, event: Union["PositionValidationFailedEvent", "PositionExecutionFailedEvent"]) -> None:
        self._logger.debug(f"Posición falló: {event.position_id} para trader {event.trader_wallet} (token: {event.token_address}) - {type(event).__name__}")
        position_closure_attempts = self._open_position_closure_attempts[event.trader_wallet, event.token_address]
        for open_position_id, attempt in position_closure_attempts.items():
            if event.position_id == attempt.close_position_id:
                attempt.status = "failed"
                position_closure_attempts[open_position_id] = attempt
                self._logger.warning(f"Marcado intento de cierre como fallido: {open_position_id} por evento {event.position_id}")
                break

    async def calculate_copy_amount(self, trade_data: TraderTradeData) -> Tuple[str, CalculationContext]:
        """
        Calcula el monto a copiar basado en la configuración usando Decimal
        
        Args:
            trade_data: Datos del trade del trader con ID único
            
        Returns:
            Monto calculado para copiar (como string)
            Contexto de cálculo

        Exceptions:
            ValueError: Si el trader no se encuentra o no se puede calcular el monto
        """
        trade_id = trade_data.id
        self._logger.info(f"Iniciando cálculo de monto para trade {trade_id} - Trader: {trade_data.trader_wallet[:8]}..., Acción: {trade_data.side}, Token: {trade_data.token_address[:8]}...")

        try:
            # Validar y preparar contexto
            context = await self._prepare_calculation_context(trade_data)

            # Determinar modo de cálculo
            mode = self._determine_calculation_mode(context)
            self._logger.debug(f"Trade {trade_id}: Modo de cálculo determinado: {mode.value}")

            # Calcular monto base según el modo
            copy_amount = self._calculate_base_amount(context, mode)
            self._logger.debug(f"Trade {trade_id}: Monto base calculado: {copy_amount}")

            # Aplicar límites de posición
            copy_amount = self._apply_position_limits(context, copy_amount)
            self._logger.debug(f"Trade {trade_id}: Monto final después de límites: {copy_amount}")

            # Formatear resultado
            result = format(copy_amount, "f")

            # Logging de éxito
            self._logger.info(f"Trade {trade_id}: Monto calculado exitosamente - {result} SOL (modo: {mode.value}, acción: {trade_data.side}, trader: {trade_data.trader_wallet})")

            return result, context

        except Exception as e:
            self._logger.error(f"Trade {trade_id}: Error al calcular monto - {str(e)} (trader: {trade_data.trader_wallet}, acción: {trade_data.side})", exc_info=True)
            raise

    async def _prepare_calculation_context(self, trade_data: TraderTradeData) -> CalculationContext:
        """
        Prepara el contexto de cálculo validando la configuración
        
        Args:
            trade_data: Datos del trade del trader con ID único
            
        Returns:
            Contexto de cálculo validado
            
        Raises:
            ValueError: Si el trader no se encuentra
        """
        # Validar trader
        trader_info = self._global_config.get_trader_info(trade_data.trader_wallet)
        if not trader_info:
            error_msg = f"Trade {trade_data.id}: Trader no encontrado: {trade_data.trader_wallet}"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        self._logger.debug(f"Trade {trade_data.id}: Trader encontrado - {trade_data.trader_wallet[:8]}..., acción: {trade_data.side}, monto original: {trade_data.amount_sol}, token: {trade_data.token_address[:8]}...")

        trader_config = self._global_config.get_trader_config(trader_info)
        original_amount_dec = Decimal(trade_data.amount_sol)
        original_sol_amount_dec = Decimal(trade_data.amount_sol)
        original_token_amount_dec = Decimal(trade_data.token_amount)
        original_token_balance_dec = Decimal(trade_data.new_token_balance)

        # Obtener balances propios y del trader si la estrategia es de porcentaje de balance
        if ((trader_config and trader_config.amount_mode and trader_config.amount_mode == AmountMode.PERCENTAGE_OF_BALANCE) or
            (self._global_config.amount_mode and self._global_config.amount_mode == AmountMode.PERCENTAGE_OF_BALANCE)):
            own_balance = await self._balance_manager.get_sol_balance() if self._balance_manager else "0.0"
            trader_balance = await self._get_trader_balance(trade_data.trader_wallet)
        else:
            own_balance = None
            trader_balance = None

        return CalculationContext(
            position_id=trade_data.id,
            trader_wallet=trade_data.trader_wallet,
            original_amount=original_amount_dec,
            original_sol_amount=original_sol_amount_dec,
            original_token_amount=original_token_amount_dec,
            original_token_balance=original_token_balance_dec,
            token_address=trade_data.token_address,
            action=trade_data.side,
            denominate_in_sol=trade_data.side == "buy",
            trader_config=trader_config,
            global_config=self._global_config,
            trader_balance=Decimal(trader_balance) if trader_balance else None,
            own_balance=Decimal(own_balance) if own_balance else None
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
            self._logger.debug(f"Trade {context.position_id}: Usando modo de cálculo individual: {context.trader_config.amount_mode.value}")
            return context.trader_config.amount_mode

        self._logger.debug(f"Trade {context.position_id}: Usando modo de cálculo global: {context.global_config.amount_mode.value}")
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
            self._logger.warning(f"Trade {context.position_id}: Modo de cálculo no reconocido: {mode}, usando EXACT")
            return context.original_amount

        start_time = time()
        self._logger.debug(f"Trade {context.position_id}: Ejecutando estrategia síncrona: {getattr(strategy, '__name__', str(strategy))}")
        result = strategy(context)
        self._logger.debug(f"Trade {context.position_id}: Estrategia síncrona completada en {time() - start_time:.6f} segundos, resultado: {result}")
        return cast(Decimal, result)

    def _calculate_exact_amount_to_buy(self, context: CalculationContext) -> Decimal:
        """Calcula monto exacto (replica el monto original)"""
        return context.original_amount

    def _calculate_exact_amount_to_sell(self, context: CalculationContext) -> Decimal:
        """Calcula monto exacto (replica el monto original)"""
        context.denominate_in_sol = True
        return self._calculate_exact_amount_to_buy(context)

    def _calculate_percentage_amount_to_buy(self, context: CalculationContext) -> Decimal:
        """Calcula monto basado en porcentaje del original"""
        value = self._get_calculation_value(context)
        result = context.original_amount * (value / Decimal("100"))
        self._logger.debug(f"Trade {context.position_id}: Cálculo de porcentaje para compra - Valor: {value}%, Original: {context.original_amount}, Resultado: {result}")
        return result

    def _calculate_percentage_amount_to_sell(self, context: CalculationContext) -> Decimal:
        """Calcula monto basado en porcentaje del original"""
        self._logger.debug(f"Trade {context.position_id}: Delegando cálculo de porcentaje para venta al método de compra")
        result = self._calculate_percentage_amount_to_buy(context)
        context.denominate_in_sol = True
        self._logger.debug(f"Trade {context.position_id}: Cálculo de porcentaje para venta completado: {result}")
        return result

    def _calculate_percentage_of_balance_amount_to_buy(self, context: CalculationContext) -> Decimal:
        """Calcula monto basado en porcentaje de nuestro balance a invertir respecto al porcentaje que invirtió el trader de su balance"""
        try:
            self._logger.debug(f"Trade {context.position_id}: Iniciando cálculo de porcentaje de balance para trader {context.trader_wallet}")

            base_key = (context.trader_wallet, context.token_address)

            # Determinar si es la primera vez que se abre posición para este token y trader
            is_first_open = True
            if self._open_position_queue is not None:
                try:
                    open_positions = self._open_position_queue.get_open_positions(context.trader_wallet, context.token_address)
                    is_first_open = len(open_positions) == 0
                    self._logger.debug(
                        f"Trade {context.position_id}: Detected {'primera' if is_first_open else 'subsiguiente'} apertura para token {context.token_address}"
                    )
                except Exception as e:
                    # Si no podemos consultar, por seguridad tratamos como primera apertura
                    self._logger.warning(f"Trade {context.position_id}: No se pudo consultar posiciones abiertas, asumiendo primera apertura. Error: {e}")

            if is_first_open and context.action == "sell":
                self._logger.info(f"Trade {context.position_id}: Primera apertura - Venta, monto=0")
                return Decimal('0')

            self._logger.debug(f"Trade {context.position_id}: Balance propio obtenido: {context.own_balance} SOL")
            if context.own_balance is None or context.own_balance == 0:
                self._logger.warning(f"Trade {context.position_id}: Balance propio es 0 o None")
                return Decimal('0')

            self._logger.debug(f"Trade {context.position_id}: Balance del trader obtenido: {context.trader_balance} SOL")
            if context.trader_balance is None or context.trader_balance == 0:
                self._logger.warning(f"Trade {context.position_id}: Balance del trader es 0 o None")
                return Decimal('0')

            if is_first_open and context.action == "buy":
                price_sol_per_token = context.original_sol_amount / context.original_token_amount
                token_balance_in_sol = context.original_token_balance * price_sol_per_token
                percentage = token_balance_in_sol / (context.trader_balance + token_balance_in_sol)
                amount_to_invest = percentage * context.own_balance

                # Guardar el monto original del primer trade para este par trader/token
                self._first_trade_original_amounts[base_key] = context.original_sol_amount

                self._logger.info(
                    f"Trade {context.position_id}: Primera apertura - Porcentaje del balance: {percentage:.4%}, Monto a invertir: {amount_to_invest} SOL"
                )
                context.original_percentage = format(percentage, "f")
                return amount_to_invest

            if context.original_sol_amount == 0:
                self._logger.warning(f"Trade {context.position_id}: Sol amount es 0")
                return Decimal('0')

            if context.action == "buy":
                percentage = context.original_sol_amount / (context.trader_balance + context.original_sol_amount)
                amount_to_invest = percentage * context.own_balance
            else:
                percentage = context.original_sol_amount / context.trader_balance
                amount_to_invest = percentage * context.own_balance

            context.original_percentage = format(percentage, "f")
            return amount_to_invest

        except Exception as e:
            self._logger.error(f"Trade {context.position_id}: Error en cálculo de porcentaje de balance: {e}", exc_info=True)
            return Decimal('0')

    def _calculate_percentage_of_balance_amount_to_sell(self, context: CalculationContext) -> Decimal:
        """Calcula el monto a vender (en tokens) siguiendo la estrategia de porcentaje de balance, con salvaguardas.

        Reglas:
        - Operar SIEMPRE en tokens (no en SOL).
        - Comparar el monto en SOL del trader con el equivalente en SOL de nuestros tokens,
            restando 1% SOLO de la última posición para proteger de la volatilidad.
        - Si el monto del trader es mayor que nuestro monto protegido, vender TODOS los tokens.
        - En caso contrario, seguir la venta "normal" por porcentaje de balance, convertida a tokens.
        """
        # Validaciones de precondición
        if not self._open_position_queue:
            self._logger.warning(f"Trade {context.position_id}: No hay cola de posiciones abiertas disponible, monto de venta=0")
            return Decimal('0')

        positions = self._open_position_queue.get_open_positions(context.trader_wallet, context.token_address)
        if not positions:
            self._logger.info(
                f"Trade {context.position_id}: No hay posiciones abiertas para vender (trader={context.trader_wallet}, token={context.token_address}). Monto=0"
            )
            return Decimal('0')

        # Precio SOL por token basado en el trade del trader
        if context.original_token_amount == 0:
            self._logger.warning(
                f"Trade {context.position_id}: original_token_amount es 0; no se puede calcular precio SOL/token. Monto=0"
            )
            return Decimal('0')

        price_sol_per_token = context.original_sol_amount / context.original_token_amount
        if price_sol_per_token <= 0:
            self._logger.warning(
                f"Trade {context.position_id}: Precio SOL/token no válido ({price_sol_per_token}). Monto=0"
            )
            return Decimal('0')

        self._logger.debug(
            f"Trade {context.position_id}: Precio estimado SOL/token={price_sol_per_token} (sol={context.original_sol_amount}, tokens={context.original_token_amount})"
        )

        # Recolectar tokens disponibles por posición (omitiendo intentos de cierre pendientes/cerrados)
        closure_attempts = self._open_position_closure_attempts.get((context.trader_wallet, context.token_address), {})

        positions_info = []  # lista de dicts: { 'id', 'tokens', 'sol' }
        total_tokens_available = Decimal('0')
        total_sol_equivalent = Decimal('0')
        last_position_sol_total = Decimal('0')
        positions_used_for_sum = 0

        for position in positions:
            if position.id in closure_attempts:
                attempt = closure_attempts[position.id]
                if attempt.status in ["pending", "closed"]:
                    self._logger.debug(
                        f"Trade {context.position_id}: Saltando posición {position.id} por intento de cierre status={attempt.status}"
                    )
                    continue

            # Considerar posiciones abiertas o parcialmente cerradas
            if position.status == PositionStatus.OPEN or not position.is_fully_closed():
                remaining_tokens = Decimal(PositionCalculationService.calculate_remaining_tokens(position, exact=True))
                if remaining_tokens <= 0:
                    self._logger.debug(
                        f"Trade {context.position_id}: Posición {position.id} sin tokens restantes (remaining_tokens={remaining_tokens}); se omite"
                    )
                    continue

                sol_value = remaining_tokens * price_sol_per_token
                positions_info.append({
                    'id': position.id,
                    'tokens': remaining_tokens,
                    'sol': sol_value,
                })
                total_tokens_available += remaining_tokens
                total_sol_equivalent += sol_value
                last_position_sol_total = sol_value
                positions_used_for_sum += 1

        if total_tokens_available == 0:
            self._logger.info(
                f"Trade {context.position_id}: No hay tokens disponibles para vender tras filtrar posiciones. Monto=0"
            )
            return Decimal('0')

        # Comparación con protección del 1% sobre la última posición
        protected_sol_equivalent = total_sol_equivalent - (last_position_sol_total * Decimal('0.01'))
        trader_sol_amount = context.original_sol_amount

        self._logger.debug(
            f"Trade {context.position_id}: Totales -> tokens={total_tokens_available}, sol_total={total_sol_equivalent}, "
            f"ultima_pos_sol={last_position_sol_total}, protegido_sol={protected_sol_equivalent}, trader_sol={trader_sol_amount}"
        )

        sell_all_tokens = trader_sol_amount > protected_sol_equivalent

        if sell_all_tokens:
            # Vender TODO: se utilizaron todas las posiciones consideradas
            tokens_to_sell = total_tokens_available
            positions_used_for_sale = positions_used_for_sum
            last_used_position_sol = last_position_sol_total

            # Registrar intentos de cierre para todas las posiciones consideradas
            for info in positions_info:
                self._open_position_closure_attempts[context.trader_wallet, context.token_address][info['id']] = OpenPositionClosureAttempt(
                    close_position_id=context.position_id
                )

            self._logger.info(
                f"Trade {context.position_id}: Monto del trader ({trader_sol_amount} SOL) > monto protegido ({protected_sol_equivalent} SOL). "
                f"Se venderán TODOS los tokens: {tokens_to_sell}. Posiciones usadas: {positions_used_for_sale}. "
                f"SOL última posición: {last_used_position_sol}"
            )
        else:
            # Seguir normalmente: usar el cálculo de porcentaje de balance (en SOL) y convertir a tokens
            normal_sol_amount = self._calculate_percentage_of_balance_amount_to_buy(context)
            context.denominate_in_sol = True
            normal_sol_amount_limited = self._apply_position_limits(context, normal_sol_amount)
            context.denominate_in_sol = False
            tokens_to_sell = normal_sol_amount_limited / price_sol_per_token
            if tokens_to_sell > total_tokens_available:
                tokens_to_sell = total_tokens_available

            # Determinar cuántas posiciones se usan para alcanzar tokens_to_sell y registrar intentos de cierre
            remaining = tokens_to_sell
            positions_used_for_sale = 0
            last_used_position_sol = Decimal('0')

            for info in positions_info:
                if remaining <= 0:
                    break
                take_tokens = info['tokens'] if info['tokens'] <= remaining else remaining
                positions_used_for_sale += 1
                last_used_position_sol = take_tokens * price_sol_per_token
                remaining -= take_tokens
                # Registrar intento de cierre para la posición utilizada
                self._open_position_closure_attempts[context.trader_wallet, context.token_address][info['id']] = OpenPositionClosureAttempt(
                    close_position_id=context.position_id
                )

            self._logger.info(
                f"Trade {context.position_id}: Venta normal por porcentaje de balance -> {normal_sol_amount_limited} SOL ~= {tokens_to_sell} tokens. "
                f"Posiciones usadas: {positions_used_for_sale}. SOL última posición usada: {last_used_position_sol}"
            )

        return tokens_to_sell

    def _calculate_fixed_amount_to_buy(self, context: CalculationContext) -> Decimal:
        """Calcula monto fijo independiente del original"""
        result = self._get_calculation_value(context)
        self._logger.debug(f"Trade {context.position_id}: Cálculo de monto fijo para compra completado: {result} SOL")
        return result

    def _calculate_fixed_amount_to_sell(self, context: CalculationContext) -> Decimal:
        """Calcula monto fijo independiente del original"""
        if not self._open_position_queue:
            self._logger.warning(f"Trade {context.position_id}: No hay cola de posiciones abiertas disponible para cálculo de venta")
            return Decimal('0')

        self._logger.debug(
            f"Trade {context.position_id}: Calculando monto fijo para venta - trader={context.trader_wallet}, token={context.token_address}"
        )

        positions_to_sell = self._open_position_queue.get_open_positions(context.trader_wallet, context.token_address)
        self._logger.debug(
            f"Trade {context.position_id}: Obtenidas {len(positions_to_sell)} posiciones abiertas para vender "
            f"(trader={context.trader_wallet}, token={context.token_address})"
        )

        close_tokens_amount = Decimal('0')

        for idx, position in enumerate(positions_to_sell):
            self._logger.debug(
                f"Trade {context.position_id}: Procesando posición {idx+1}/{len(positions_to_sell)}: id={position.id}, "
                f"status={getattr(position, 'status', None)}, "
                f"is_fully_closed={getattr(position, 'is_fully_closed', lambda: None)()}"
            )

            closure_attempts = self._open_position_closure_attempts.get((context.trader_wallet, context.token_address), {})
            if position.id in closure_attempts:
                attempt_to_close = closure_attempts[position.id]
                self._logger.debug(
                    f"Trade {context.position_id}: Intento previo de cierre encontrado para posición {position.id}: status={attempt_to_close.status}"
                )
                if attempt_to_close.status in ["pending", "closed"]:
                    self._logger.debug(f"Trade {context.position_id}: Saltando posición {position.id} con estado {attempt_to_close.status}")
                    continue

            if position.status == PositionStatus.OPEN:
                remaining_tokens = Decimal(PositionCalculationService.calculate_remaining_tokens(position, exact=True))
                self._logger.debug(
                    f"Trade {context.position_id}: Posición {position.id} está ABIERTA. Tokens restantes para cerrar: {remaining_tokens}"
                )
                close_tokens_amount += remaining_tokens
                self._logger.debug(
                    f"Trade {context.position_id}: Registrando intento de cierre para posición {position.id} (open). close_position_id={context.position_id}"
                )
                self._open_position_closure_attempts[context.trader_wallet, context.token_address][position.id] = OpenPositionClosureAttempt(
                    close_position_id=context.position_id
                )
                self._logger.debug(
                    f"Trade {context.position_id}: Agregada posición abierta {position.id}: {remaining_tokens} tokens. "
                    f"Total acumulado: {close_tokens_amount}"
                )
                break
            elif not position.is_fully_closed():
                remaining_tokens = Decimal(PositionCalculationService.calculate_remaining_tokens(position, exact=True))
                self._logger.debug(
                    f"Trade {context.position_id}: Posición {position.id} está PARCIALMENTE CERRADA. Tokens restantes para cerrar: {remaining_tokens}"
                )
                close_tokens_amount += remaining_tokens
                self._logger.debug(
                    f"Trade {context.position_id}: Registrando intento de cierre para posición {position.id} (partial). close_position_id={context.position_id}"
                )
                self._open_position_closure_attempts[context.trader_wallet, context.token_address][position.id] = OpenPositionClosureAttempt(
                    close_position_id=context.position_id
                )
                self._logger.debug(
                    f"Trade {context.position_id}: Agregada posición parcialmente cerrada {position.id}: {remaining_tokens} tokens. "
                    f"Total acumulado: {close_tokens_amount}"
                )

        self._logger.debug(
            f"Trade {context.position_id}: Monto total calculado para venta (trader={context.trader_wallet}, token={context.token_address}): {close_tokens_amount} tokens"
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
            error_msg = f"Trade {context.position_id}: No se puede calcular el monto a copiar en modo DISTRIBUTED, no se encontró la configuración del trader o la configuración global"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        self._logger.debug(f"Trade {context.position_id}: Parámetros de distribución: {distribution_params}")

        # Calcular monto distribuido
        balance_per_token = distribution_params['max_amount_to_invest'] / distribution_params['max_open_tokens']
        distributed_amount = balance_per_token / distribution_params['max_open_positions_per_token']

        self._logger.debug(f"Trade {context.position_id}: Cálculo distribuido - balance por token={balance_per_token}, monto distribuido={distributed_amount}")
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
        if context.denominate_in_sol:
            # Aplicar límite máximo
            original_amount = amount
            amount = self._apply_max_limit(context, amount)
            if amount != original_amount:
                self._logger.debug(f"Trade {context.position_id}: Aplicado límite máximo: {original_amount} -> {amount}")

            # Aplicar límite mínimo
            original_amount = amount
            amount = self._apply_min_limit(context, amount)
            if amount != original_amount:
                self._logger.debug(f"Trade {context.position_id}: Aplicado límite mínimo: {original_amount} -> {amount}")

        exp = Decimal("0.000000001" if context.denominate_in_sol else "0.000001")
        final_amount = amount.quantize(exp, rounding=ROUND_DOWN).normalize()

        if final_amount != amount:
            self._logger.debug(f"Trade {context.position_id}: Redondeado monto: {amount} -> {final_amount} (precisión: {exp})")

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
        max_position_size_static = None
        if (context.trader_config and 
            context.trader_config.adjust_position_size and 
            context.trader_config.max_position_size):
            max_position_size_static = Decimal(context.trader_config.max_position_size)
        elif (context.global_config.max_position_size and 
            context.global_config.adjust_position_size):
            max_position_size_static = Decimal(context.global_config.max_position_size)

        max_position_size_percentage = None
        if (context.trader_config and 
            context.trader_config.adjust_position_size and 
            context.trader_config.max_position_size_percentage):
            max_position_size_percentage = Decimal(context.trader_config.max_position_size_percentage)
        elif (context.global_config and 
            context.global_config.adjust_position_size and 
            context.global_config.max_position_size_percentage):
            max_position_size_percentage = Decimal(context.global_config.max_position_size_percentage)

        max_position_size_percentage_in_sol = None
        if max_position_size_percentage:
            if context.own_balance is None or context.own_balance == 0:
                self._logger.warning(f"Trade {context.position_id}: Balance propio es 0 o None")
                return Decimal('0')
            max_position_size_percentage_in_sol = context.own_balance * max_position_size_percentage / Decimal("100")

        if max_position_size_static and max_position_size_percentage_in_sol:
            return min(max_position_size_static, max_position_size_percentage_in_sol)
        elif max_position_size_static:
            return max_position_size_static
        elif max_position_size_percentage_in_sol:
            return max_position_size_percentage_in_sol

        return max_position_size_static

    def _get_min_position_limit(self, context: CalculationContext) -> Optional[Decimal]:
        """Obtiene el límite mínimo de posición"""
        min_position_size_static = None
        if (context.trader_config and 
            context.trader_config.adjust_position_size and 
            context.trader_config.min_position_size):
            min_position_size_static = Decimal(context.trader_config.min_position_size)
        elif (context.global_config.min_position_size and 
            context.global_config.adjust_position_size):
            min_position_size_static = Decimal(context.global_config.min_position_size)

        min_position_size_percentage = None
        if (context.trader_config and 
            context.trader_config.adjust_position_size and 
            context.trader_config.min_position_size_percentage):
            min_position_size_percentage = Decimal(context.trader_config.min_position_size_percentage)
        elif (context.global_config and 
            context.global_config.adjust_position_size and 
            context.global_config.min_position_size_percentage):
            min_position_size_percentage = Decimal(context.global_config.min_position_size_percentage)

        min_position_size_percentage_in_sol = None
        if min_position_size_percentage:
            if context.own_balance is None or context.own_balance == 0:
                self._logger.warning(f"Trade {context.position_id}: Balance propio es 0 o None")
                return Decimal('0')
            min_position_size_percentage_in_sol = context.own_balance * min_position_size_percentage / Decimal("100")

        if min_position_size_static and min_position_size_percentage_in_sol:
            return max(min_position_size_static, min_position_size_percentage_in_sol)
        elif min_position_size_static:
            return min_position_size_static
        elif min_position_size_percentage_in_sol:
            return min_position_size_percentage_in_sol

        return min_position_size_static

    async def _get_trader_balance(self, wallet: str) -> str:
        """Obtiene el balance del trader"""
        if wallet not in self._trader_balances:
            start_time = time()
            self._logger.debug(f"Obteniendo balance para trader {wallet} desde Solana")
            self._trader_balances[wallet] = await self._solana_analyzer.get_sol_balance(wallet) if self._solana_analyzer else "0.0"
            self._logger.debug(f"Balance del trader {wallet} obtenido en {time() - start_time:.6f} segundos: {self._trader_balances[wallet]} SOL")
        else:
            self._logger.debug(f"Usando balance en caché para trader {wallet}: {self._trader_balances[wallet]} SOL")
        return self._trader_balances[wallet]
