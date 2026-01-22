# -*- coding: utf-8 -*-
"""
Callback especializado para Copy Trading
"""
import asyncio
from typing import Dict, Any, Optional, Union, Set
from datetime import datetime, timedelta
from decimal import Decimal, getcontext
from cachetools import TTLCache
from dataclasses import dataclass, field

from ..config import CopyTradingConfig
from ..position_management.models import TraderTradeData, PositionTraderTradeData
from ..position_management.queues import PendingPositionQueue, OpenPositionQueue
from ..transactions_management import CopyAmountCalculator
from ..data_management import TokenTraderManager
from ..events import PositionEventBus, PositionValidationFailedEvent
from logging_system import AppLogger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..validation import ValidationEngine

# Configurar precisión decimal según preferencias del usuario
getcontext().prec = 26


@dataclass(slots=True)
class TraderRateLimitData:
    """Datos de rate limiting para un trader específico"""
    open_tokens: int = 0
    last_trade_time: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class TokenRateLimitData:
    """Datos de rate limiting para un token específico"""
    traders: Set[str] = field(default_factory=set)

    @property
    def traders_per_token(self) -> int:
        """Obtiene el total de traders"""
        return len(self.traders)


@dataclass(slots=True)
class TraderTokenRateLimitData:
    """Datos de rate limiting para la combinación trader-token"""
    open_positions_per_token: int = 0


@dataclass(slots=True)
class TradeDataWithValidation:
    """Datos del trade con las validaciones"""
    trade_data: TraderTradeData
    min_sol_amount_valid: bool
    max_sol_amount_valid: bool
    activity_valid: bool
    is_min_sol_enabled: bool
    is_max_sol_enabled: bool
    is_activity_enabled: bool


class TradeProcessorCallback:
    """Callback para procesar trades y replicarlos automáticamente"""

    def __init__(self, 
                    config: CopyTradingConfig,
                    pending_position_queue: PendingPositionQueue,
                    validation_engine: "ValidationEngine",
                    token_trader_manager: TokenTraderManager,
                    amount_calculator: CopyAmountCalculator,
                    position_event_bus: PositionEventBus,
                    open_position_queue: Optional[OpenPositionQueue] = None):
        """
        Inicializa el callback
        
        Args:
            config: Configuración del sistema
            pending_position_queue: Cola de posiciones pendientes
            validation_engine: Motor de validaciones
            token_trader_manager: Gestor de cache inteligente
            amount_calculator: Calculador de montos de copia
            position_event_bus: EventBus para notificaciones de eventos de posición
            open_position_queue: Cola de posiciones abiertas
        """
        self.config = config
        self.pending_position_queue = pending_position_queue
        self.open_position_queue = open_position_queue
        self.validation_engine = validation_engine
        self._token_trader_manager = token_trader_manager
        self._logger = AppLogger(self.__class__.__name__)
        self._amount_calculator = amount_calculator
        self._position_event_bus = position_event_bus

        # Cache de rate limiting para evitar procesar trades que violen límites de configuración
        # keys: trader_wallet -> TraderRateLimitData, token_address -> TokenRateLimitData, trader_wallet_token_address -> TraderTokenRateLimitData
        self._rate_limit_cache: TTLCache[str, Union[TokenRateLimitData, TraderRateLimitData, TraderTokenRateLimitData]] = TTLCache(maxsize=1000, ttl=60)

        # Validar que pending_position_queue no sea None
        if self.pending_position_queue is None:
            raise ValueError("pending_position_queue no puede ser None")

        # Cola interna para procesamiento asíncrono
        self._processing_queue: asyncio.Queue[TradeDataWithValidation] = asyncio.Queue(maxsize=1000)
        self._processing_tasks: Set[asyncio.Task] = set()

        # Flag para controlar el procesamiento
        self._processing_active = True

        # token_address -> contador de trades observados en la ventana de tiempo
        self._token_trade_activity_cache: TTLCache[str, int] = TTLCache(maxsize=1000, ttl=self.config.trade_activity_window_seconds)

        # Iniciar worker de procesamiento
        asyncio.create_task(self._processing_worker())

        # Estadísticas
        self.stats = {
            'trades_received': 0,
            'trades_validated': 0,
            'trades_queued': 0,
            'trades_rejected': 0,
            'trades_processing': 0,
            'last_trade_time': None
        }

    async def __call__(self, data: dict) -> None:
        """
        Procesa un trade recibido de manera no-bloqueante
        
        Args:
            data: Datos del trade en formato PumpFun
        """
        try:
            # Incrementar contador inmediatamente
            self.stats['trades_received'] += 1

            # Log rápido sin await
            asyncio.create_task(self._log_async("Trade recibido", data.get('signature', 'N/A')))

            # Validación básica síncrona (rápida)
            trade_data = self._create_trade_data_from_pumpfun(data)

            if isinstance(self.config.allowed_pools, list) and trade_data.pool not in self.config.allowed_pools:
                self.stats['trades_rejected'] += 1
                asyncio.create_task(self._log_async("Trade rechazado - pool no permitido", data.get('signature', 'N/A')))
                return

            if not self._validate_trade_data_basic(trade_data):
                self.stats['trades_rejected'] += 1
                asyncio.create_task(self._log_async("Trade rechazado - validación básica", data.get('signature', 'N/A')))
                return

            # Validar montos mínimo y máximo de SOL según el pool
            pool_min_threshold = self._get_min_sol_threshold(trade_data.pool)
            pool_max_threshold = self._get_max_sol_threshold(trade_data.pool)
            min_sol_valid = self._validate_minimum_sol_amount(trade_data, pool_min_threshold)
            max_sol_valid = self._validate_maximum_sol_amount(trade_data, pool_max_threshold)
            activity_valid = self._validate_trade_activity_threshold(trade_data)

            is_min_sol_enabled = pool_min_threshold is not None
            is_max_sol_enabled = pool_max_threshold is not None
            is_activity_enabled = self.config.is_trade_activity_filter_enabled

            # Validar monto máximo (si está habilitado, debe cumplirse siempre)
            if is_max_sol_enabled and not max_sol_valid:
                self.stats['trades_rejected'] += 1
                asyncio.create_task(self._log_async("Trade rechazado - monto máximo de SOL excedido", data.get('signature', 'N/A')))
                return

            if is_min_sol_enabled and is_activity_enabled:
                if not (min_sol_valid or activity_valid):
                    self.stats['trades_rejected'] += 1
                    asyncio.create_task(self._log_async("Trade rechazado - monto mínimo de SOL y actividad de trading insuficiente", data.get('signature', 'N/A')))
                    return
            elif is_min_sol_enabled:
                if not min_sol_valid:
                    self.stats['trades_rejected'] += 1
                    asyncio.create_task(self._log_async("Trade rechazado - monto mínimo de SOL insuficiente", data.get('signature', 'N/A')))
                    return
            elif is_activity_enabled:
                if not activity_valid:
                    self.stats['trades_rejected'] += 1
                    asyncio.create_task(self._log_async("Trade rechazado - actividad de trading insuficiente", data.get('signature', 'N/A')))

            if not self._validate_trade_rate_limits(trade_data):
                self.stats['trades_rejected'] += 1
                asyncio.create_task(self._log_async("Trade rechazado - límites de rate", data.get('signature', 'N/A')))
                return

            # Añadir a cola de procesamiento para operaciones lentas
            try:
                self._processing_queue.put_nowait(TradeDataWithValidation(
                    trade_data=trade_data,
                    min_sol_amount_valid=min_sol_valid,
                    max_sol_amount_valid=max_sol_valid,
                    activity_valid=activity_valid,
                    is_min_sol_enabled=is_min_sol_enabled,
                    is_max_sol_enabled=is_max_sol_enabled,
                    is_activity_enabled=is_activity_enabled,
                ))

                self.stats['trades_processing'] += 1
            except asyncio.QueueFull:
                self._logger.warning("Cola de procesamiento llena, trade descartado")
                self.stats['trades_rejected'] += 1

        except Exception as e:
            self._logger.error(f"Error en procesamiento inicial: {e}", exc_info=True)
            self.stats['trades_rejected'] += 1

    def _get_min_sol_threshold(self, pool: Optional[str]) -> Optional[str]:
        """
        Obtiene el umbral mínimo de SOL según el pool del trade.
        Para pump-amm usa el umbral dedicado; para cualquier otro pool usa el umbral general.
        """
        pool_normalized = (pool or "").strip().lower()
        if pool_normalized == "pump-amm":
            return self.config.pump_amm_min_sol_amount_threshold
        return self.config.other_pools_min_sol_amount_threshold

    def _get_max_sol_threshold(self, pool: Optional[str]) -> Optional[str]:
        """
        Obtiene el umbral máximo de SOL según el pool del trade.
        Para pump-amm usa el umbral dedicado; para cualquier otro pool usa el umbral general.
        """
        pool_normalized = (pool or "").strip().lower()
        if pool_normalized == "pump-amm":
            return self.config.pump_amm_max_sol_amount_threshold
        return self.config.other_pools_max_sol_amount_threshold

    def _validate_minimum_sol_amount(self, trade_data: TraderTradeData, threshold: Optional[str] = None) -> bool:
        """
        Valida que el trade cumpla con el monto mínimo de SOL configurado según el pool
        
        Args:
            trade_data: Datos del trade a validar
            threshold: Umbral de SOL a utilizar; si no se pasa se determina por pool
            
        Returns:
            True si el monto es mayor o igual al umbral mínimo, False en caso contrario
        """
        pool_threshold = threshold if threshold is not None else self._get_min_sol_threshold(trade_data.pool)

        if pool_threshold is None:
            self._logger.debug("Monto mínimo de SOL deshabilitado para el pool actual")
            return True

        if trade_data.side == 'sell':
            self._logger.debug("Operación de tipo 'sell', no se valida monto mínimo de SOL para esta operación")
            return True

        try:
            amount_decimal = Decimal(trade_data.amount_sol)
            threshold_decimal = Decimal(pool_threshold)
            pool_name = trade_data.pool or 'desconocido'

            if amount_decimal < threshold_decimal:
                self._logger.info(f"Trade rechazado - monto {trade_data.amount_sol} SOL < {threshold_decimal} SOL (mínimo) para pool {pool_name}")
                return False
            self._logger.debug(f"Trade validado - monto {trade_data.amount_sol} SOL >= {threshold_decimal} SOL (mínimo) para pool {pool_name}")
            return True
        except (ValueError, TypeError, Exception):
            self._logger.warning(f"Error al validar monto mínimo de SOL ({pool_threshold}) para pool {trade_data.pool}: {trade_data.amount_sol}")
            return False

    def _validate_maximum_sol_amount(self, trade_data: TraderTradeData, threshold: Optional[str] = None) -> bool:
        """
        Valida que el trade cumpla con el monto máximo de SOL configurado según el pool
        
        Args:
            trade_data: Datos del trade a validar
            threshold: Umbral de SOL a utilizar; si no se pasa se determina por pool
            
        Returns:
            True si el monto es menor o igual al umbral máximo, False en caso contrario
        """
        pool_threshold = threshold if threshold is not None else self._get_max_sol_threshold(trade_data.pool)

        if pool_threshold is None:
            self._logger.debug("Monto máximo de SOL deshabilitado para el pool actual")
            return True

        if trade_data.side == 'sell':
            self._logger.debug("Operación de tipo 'sell', no se valida monto máximo de SOL para esta operación")
            return True

        try:
            amount_decimal = Decimal(trade_data.amount_sol)
            threshold_decimal = Decimal(pool_threshold)
            pool_name = trade_data.pool or 'desconocido'

            if amount_decimal > threshold_decimal:
                self._logger.info(f"Trade rechazado - monto {trade_data.amount_sol} SOL > {threshold_decimal} SOL (máximo) para pool {pool_name}")
                return False
            self._logger.debug(f"Trade validado - monto {trade_data.amount_sol} SOL <= {threshold_decimal} SOL (máximo) para pool {pool_name}")
            return True
        except (ValueError, TypeError, Exception):
            self._logger.warning(f"Error al validar monto máximo de SOL ({pool_threshold}) para pool {trade_data.pool}: {trade_data.amount_sol}")
            return False

    def _validate_trade_activity_threshold(self, trade_data: TraderTradeData) -> bool:
        """
        Valida que el token haya alcanzado un umbral mínimo de actividad de trading
        
        Este filtro solo permite copiar trades después de observar N trades previos
        en el token dentro de una ventana de tiempo. Sirve como filtro de "popularidad"
        para evitar copiar tokens con baja actividad.
        
        Args:
            trade_data: Datos del trade a validar
            
        Returns:
            True si se ha alcanzado el umbral de actividad, False en caso contrario
        """
        if not self.config.is_trade_activity_filter_enabled:
            self._logger.debug("Filtro de actividad de trading deshabilitado")
            return True

        if trade_data.side == 'sell':
            self._logger.debug("Operación de tipo 'sell', no se valida actividad de trading para esta operación")
            return True

        try:
            token_key = trade_data.token_address
            if token_key not in self._token_trade_activity_cache:
                self._token_trade_activity_cache[token_key] = 0

            self._token_trade_activity_cache[token_key] += 1
            current_count = self._token_trade_activity_cache[token_key]

            if current_count >= self.config.min_trade_count_threshold:
                self._logger.debug(f"Trade validado - actividad suficiente para {trade_data.token_address}: {current_count}/{self.config.min_trade_count_threshold} trades observados")
                return True

            self._logger.debug(f"Trade rechazado - actividad insuficiente para {trade_data.token_address}: {current_count}/{self.config.min_trade_count_threshold} trades observados")
            return False
        except (ValueError, TypeError, Exception) as e:
            self._logger.warning(f"Error al validar actividad de trading para {trade_data.token_address}: {e}")
            return False

    async def _processing_worker(self):
        """Worker que procesa trades de la cola interna"""
        while self._processing_active:
            try:
                # Obtener trade de la cola con timeout
                trade_data_with_validation = await asyncio.wait_for(
                    self._processing_queue.get(), timeout=1.0
                )

                # Procesar trade en task separado
                task = asyncio.create_task(self._process_trade_async(trade_data_with_validation))
                self._processing_tasks.add(task)
                task.add_done_callback(self._processing_tasks.discard)

                self._processing_queue.task_done()

            except asyncio.TimeoutError:
                # Timeout normal, continuar
                continue
            except Exception as e:
                self._logger.error(f"Error en processing worker: {e}")

    async def _process_trade_async(self, trade_data_with_validation: TradeDataWithValidation):
        """Procesa un trade de manera asíncrona con todas las validaciones"""
        try:
            # Obtener datos del trade con validaciones
            trade_data = trade_data_with_validation.trade_data
            min_sol_amount_valid = trade_data_with_validation.min_sol_amount_valid
            max_sol_amount_valid = trade_data_with_validation.max_sol_amount_valid
            activity_valid = trade_data_with_validation.activity_valid
            is_min_sol_enabled = trade_data_with_validation.is_min_sol_enabled
            is_max_sol_enabled = trade_data_with_validation.is_max_sol_enabled
            is_activity_enabled = trade_data_with_validation.is_activity_enabled

            # Calcular montos de copia
            copy_amount, context = await self._amount_calculator.calculate_copy_amount(trade_data)

            # Validación avanzada (operación lenta)
            is_valid, validation_checks = await self.validation_engine.validate_trade(
                trader_wallet=trade_data.trader_wallet,
                token_address=trade_data.token_address,
                amount_sol=copy_amount if context.denominate_in_sol else "",
                amount_tokens=copy_amount if not context.denominate_in_sol else "",
                denominate_in_sol=context.denominate_in_sol,
                side=trade_data.side
            )

            if not is_valid:
                error_msg = '; '.join(
                    check.message for check in validation_checks if check.result.value == 'failed'
                ) or 'Validación fallida'

                await self._log_async("Trade no válido", f"{error_msg} | {trade_data.trader_wallet}")
                self.stats['trades_rejected'] += 1
                self._position_event_bus.emit_position_validation_failed(
                    PositionValidationFailedEvent(
                        position_id=trade_data.id,
                        token_address=trade_data.token_address,
                        trader_wallet=trade_data.trader_wallet,
                        error_message=error_msg
                    )
                )
                return

            # Trade válido - crear posición y encolar
            self.stats['trades_validated'] += 1

            await self._log_async("Trade válido", f"{trade_data.side} {trade_data.amount_sol} SOL")

            position = PositionTraderTradeData(
                trader_trade_data=trade_data,
                copy_amount_sol=copy_amount if context.denominate_in_sol else "",
                copy_amount_tokens=copy_amount if not context.denominate_in_sol else "",
                denominate_in_sol=context.denominate_in_sol,
                trader_balance_used=format(context.trader_balance, "f") if context.trader_balance else None,
                own_balance_used=format(context.own_balance, "f") if context.own_balance else None,
                original_percentage=context.original_percentage
            )

            # Añadir metadata a la posición
            position.add_metadata("min_sol_amount_valid", min_sol_amount_valid)
            position.add_metadata("max_sol_amount_valid", max_sol_amount_valid)
            position.add_metadata("activity_valid", activity_valid)
            position.add_metadata("is_min_sol_enabled", is_min_sol_enabled)
            position.add_metadata("is_max_sol_enabled", is_max_sol_enabled)
            position.add_metadata("is_activity_enabled", is_activity_enabled)

            # Encolar posición
            await self.pending_position_queue.add_position(position)
            self.stats['trades_queued'] += 1
            self.stats['last_trade_time'] = datetime.now()

            await self._log_async("Trade encolado", trade_data.signature)

        except Exception as e:
            self._logger.error(f"Error procesando trade asíncrono: {e}")
            self.stats['trades_rejected'] += 1
        finally:
            self.stats['trades_processing'] -= 1

    def _validate_trade_data_basic(self, trade_data: TraderTradeData) -> bool:
        """
        Validación rápida y síncrona de datos básicos del trade
        
        Args:
            trade_data: Objeto TradeData con la información del trade
            
        Returns:
            True si el trade pasa validación básica
        """
        # Validar campos obligatorios
        if not trade_data.trader_wallet or not trade_data.token_address:
            return False

        # Validar amount_sol usando Decimal para mayor precisión
        try:
            amount_decimal = Decimal(trade_data.amount_sol)
            if amount_decimal <= Decimal('0'):
                return False
        except (ValueError, TypeError, Exception):
            return False

        if trade_data.side not in ['buy', 'sell']:
            return False

        # Verificar si es un trader que seguimos
        if not self.config.get_trader_info(trade_data.trader_wallet):
            return False

        return True

    def _validate_trade_rate_limits(self, trade_data: TraderTradeData) -> bool:
        """
        Valida los límites de rate limiting para evitar trades excesivos de apertura
        
        Esta validación es síncrona y rápida para no bloquear el callback.
        Se enfoca en proteger el sistema de trades duplicados o excesivos
        según la configuración, complementando las validaciones del ValidationEngine.
        Para trades de apertura (side='buy') incrementa contadores, para cierre (side='sell') los decrementa.
        
        Args:
            trade_data: Objeto TradeData con la información del trade
            
        Returns:
            True si el trade cumple con los límites de rate
        """
        self._logger.debug(f"Validando rate limits para trade: wallet={trade_data.trader_wallet}, token={trade_data.token_address}, side={trade_data.side}")

        # Validar campos obligatorios
        if not trade_data.trader_wallet or not trade_data.token_address:
            self._logger.debug("Trade rechazado - faltan campos obligatorios (trader_wallet o token_address)")
            return False

        # Para operaciones sell, solo actualizar contadores y validar que no haya posiciones abiertas
        if trade_data.side == 'sell':
            self._logger.debug("Operación de tipo 'sell', actualizando contadores y permitiendo trade si hay posiciones abiertas.")
            return self._validate_and_update_rate_limits_for_sell(trade_data)

        # Para operaciones buy, validar límites e incrementar contadores
        trader_config_values = self._get_trader_rate_limit_config(trade_data.trader_wallet)
        self._logger.debug(f"Configuración de rate limit para trader: {trader_config_values}")

        # Inicializar o obtener datos de cache para trader
        trader_key = f"{trade_data.trader_wallet}"
        if trader_key not in self._rate_limit_cache:
            self._logger.debug(f"Inicializando cache de rate limit para trader: {trader_key}")
            self._rate_limit_cache[trader_key] = TraderRateLimitData()

        # Inicializar o obtener datos de cache para token
        token_key = f"{trade_data.token_address}"
        if token_key not in self._rate_limit_cache:
            self._logger.debug(f"Inicializando cache de rate limit para token: {token_key}")
            self._rate_limit_cache[token_key] = TokenRateLimitData()

        # Inicializar o obtener datos de cache para trader-token
        trader_token_key = f"{trade_data.trader_wallet}_{trade_data.token_address}"
        if trader_token_key not in self._rate_limit_cache:
            self._logger.debug(f"Inicializando cache de rate limit para trader-token: {trader_token_key}")
            self._rate_limit_cache[trader_token_key] = TraderTokenRateLimitData()

        # Validar intervalo mínimo entre trades
        min_trade_interval_seconds = trader_config_values["min_open_trade_interval_seconds"]
        trader_cache = self._rate_limit_cache[trader_key]
        if isinstance(trader_cache, TraderRateLimitData):
            tiempo_desde_ultimo_trade = (datetime.now() - trader_cache.last_trade_time).total_seconds()
            self._logger.debug(f"Tiempo desde último trade para trader {trader_key}: {tiempo_desde_ultimo_trade} segundos (mínimo requerido: {min_trade_interval_seconds})")
            if min_trade_interval_seconds and (datetime.now() - trader_cache.last_trade_time) < timedelta(seconds=min_trade_interval_seconds):
                self._logger.info(f"Trade rechazado - intervalo mínimo no cumplido para trader: {trade_data.trader_wallet}")
                return False
            else:
                trader_cache.last_trade_time = datetime.now()
                self._rate_limit_cache[trader_key] = trader_cache
        else:
            self._logger.debug(f"Cache de trader no es instancia de TraderRateLimitData, reinicializando: {trader_key}")
            self._rate_limit_cache[trader_key] = TraderRateLimitData()

        # Validar máximo de traders por token
        trader_already_in_token = self._token_trader_manager.has_trader_in_token(trade_data.trader_wallet, trade_data.token_address)
        current_traders_per_token = self._token_trader_manager.get_traders_count_by_token(trade_data.token_address)
        max_traders_per_token = trader_config_values["max_traders_per_token"]
        token_cache = self._rate_limit_cache[token_key]
        self._logger.debug(f"Traders actuales en token {token_key}: {current_traders_per_token}, máximo permitido: {max_traders_per_token}, ya está en token: {trader_already_in_token}")
        if isinstance(token_cache, TokenRateLimitData):
            trader_already_in_token_cache = trade_data.trader_wallet in token_cache.traders
            if (max_traders_per_token and token_cache.traders_per_token >= max_traders_per_token and not (trader_already_in_token or trader_already_in_token_cache)) or (
                max_traders_per_token and current_traders_per_token >= max_traders_per_token and not (trader_already_in_token or trader_already_in_token_cache)):
                self._logger.info(f"Trade rechazado - máximo de traders por token alcanzado: {trade_data.token_address}")
                return False
            else:
                if not (trader_already_in_token or trader_already_in_token_cache):
                    token_cache.traders.add(trade_data.trader_wallet)
                    self._logger.debug(f"Incrementando traders_per_token para token {token_key}: {token_cache.traders_per_token}")
                self._rate_limit_cache[token_key] = token_cache
        else:
            self._logger.debug(f"Cache de token no es instancia de TokenRateLimitData, reinicializando: {token_key}")
            self._rate_limit_cache[token_key] = TokenRateLimitData()

        # Validar máximo de tokens abiertos por trader
        target_token_has_active_positions = self._token_trader_manager.target_token_has_active_positions(trade_data.trader_wallet, trade_data.token_address)
        current_open_tokens_per_trader = self._token_trader_manager.get_tokens_by_trader_count(trade_data.trader_wallet)
        max_open_tokens = trader_config_values["max_open_tokens"]
        trader_cache = self._rate_limit_cache[trader_key]
        self._logger.debug(f"Tokens abiertos por trader {trader_key}: {current_open_tokens_per_trader}, máximo permitido: {max_open_tokens}, token objetivo ya tiene posiciones activas: {target_token_has_active_positions}")
        if isinstance(trader_cache, TraderRateLimitData):
            if (max_open_tokens and trader_cache.open_tokens >= max_open_tokens and not target_token_has_active_positions) or (
                max_open_tokens and current_open_tokens_per_trader >= max_open_tokens and not target_token_has_active_positions):
                self._logger.info(f"Trade rechazado - máximo de tokens abiertos alcanzado para trader: {trade_data.trader_wallet}")
                return False
            else:
                if not target_token_has_active_positions:
                    trader_cache.open_tokens += 1
                    self._logger.debug(f"Incrementando open_tokens para trader {trader_key}: {trader_cache.open_tokens}")
                self._rate_limit_cache[trader_key] = trader_cache
        else:
            self._logger.debug(f"Cache de trader no es instancia de TraderRateLimitData, reinicializando: {trader_key}")
            self._rate_limit_cache[trader_key] = TraderRateLimitData()

        # Validar máximo de posiciones abiertas por token por trader
        current_open_positions_per_token = self._token_trader_manager.get_open_positions_count_by_token(trade_data.token_address)
        max_open_positions_per_token = trader_config_values["max_open_positions_per_token"]
        trader_token_cache = self._rate_limit_cache[trader_token_key]
        self._logger.debug(f"Posiciones abiertas por token {trader_token_key}: {current_open_positions_per_token}, máximo permitido: {max_open_positions_per_token}")
        if isinstance(trader_token_cache, TraderTokenRateLimitData):
            if (max_open_positions_per_token and trader_token_cache.open_positions_per_token >= max_open_positions_per_token) or (
                max_open_positions_per_token and current_open_positions_per_token >= max_open_positions_per_token):
                self._logger.info(f"Trade rechazado - máximo de posiciones por token alcanzado: {trader_token_key}")
                return False
            else:
                trader_token_cache.open_positions_per_token += 1
                self._logger.debug(f"Incrementando open_positions_per_token para trader-token {trader_token_key}: {trader_token_cache.open_positions_per_token}")
                self._rate_limit_cache[trader_token_key] = trader_token_cache
        else:
            self._logger.debug(f"Cache de trader-token no es instancia de TraderTokenRateLimitData, reinicializando: {trader_token_key}")
            self._rate_limit_cache[trader_token_key] = TraderTokenRateLimitData()

        self._logger.debug(f"Contadores incrementados para buy: {trade_data.trader_wallet} - {trade_data.token_address}")
        return True

    def _validate_and_update_rate_limits_for_sell(self, trade_data: TraderTradeData) -> bool:
        """
        Actualiza los contadores de rate limiting para operaciones de venta (sell)
        
        Para operaciones sell, decrementa los contadores en los dataclasses
        pero mantiene que nunca sean negativos y que haya posiciones abiertas.
        
        Args:
            trade_data: Objeto TradeData con la información del trade
            
        Returns:
            True si el trade es válido
        """
        # Claves para acceder al cache
        trader_key = f"{trade_data.trader_wallet}"
        token_key = f"{trade_data.token_address}"
        trader_token_key = f"{trade_data.trader_wallet}_{trade_data.token_address}"

        # Validar si la posición abierta existe en la cola de posiciones abiertas
        if not self._has_open_position_queue(trade_data):
            self._logger.debug(f"Trade rechazado - no hay posiciones abiertas: {trade_data.trader_wallet} - {trade_data.token_address}")
            return False

        # Actualizar contador de tokens abiertos por trader
        if trader_key in self._rate_limit_cache:
            trader_cache = self._rate_limit_cache[trader_key]
            if isinstance(trader_cache, TraderRateLimitData):
                trader_cache.open_tokens = max(0, trader_cache.open_tokens - 1)
                self._rate_limit_cache[trader_key] = trader_cache

        # Actualizar contador de traders por token
        if token_key in self._rate_limit_cache:
            token_cache = self._rate_limit_cache[token_key]
            if isinstance(token_cache, TokenRateLimitData):
                if self._get_open_position_queue_size(trade_data) <= 1:
                    try:
                        token_cache.traders.remove(trade_data.trader_wallet)
                        self._logger.debug(f"Removiendo trader {trade_data.trader_wallet} del token {token_key}")
                    except KeyError:
                        self._logger.debug(f"Trader {trade_data.trader_wallet} no encontrado en el token {token_key}")
                self._rate_limit_cache[token_key] = token_cache

        # Actualizar contador de posiciones abiertas por token por trader
        if trader_token_key in self._rate_limit_cache:
            trader_token_cache = self._rate_limit_cache[trader_token_key]
            if isinstance(trader_token_cache, TraderTokenRateLimitData):
                trader_token_cache.open_positions_per_token = max(0, trader_token_cache.open_positions_per_token - 1)
                self._rate_limit_cache[trader_token_key] = trader_token_cache

        self._logger.debug(f"Contadores decrementados para sell: {trade_data.trader_wallet} - {trade_data.token_address}")
        return True

    def _has_open_position_queue(self, trade_data: TraderTradeData) -> bool:
        """
        Valida si hay posiciones abiertas para el trader y token especificados
        """
        if self.open_position_queue is None:
            return False

        return self._get_open_position_queue_size(trade_data) > 0

    def _get_open_position_queue_size(self, trade_data: TraderTradeData) -> int:
        """
        Obtiene el tamaño de la cola de posiciones abiertas para el trader y token especificados
        """
        if self.open_position_queue is None:
            return 0
        return self.open_position_queue.get_queue_size(trade_data.trader_wallet, trade_data.token_address)

    def _get_trader_rate_limit_config(self, trader_wallet: str) -> Dict[str, Optional[int]]:
        """
        Obtiene la configuración de rate limiting para un trader específico
        
        Combina configuración global con configuración específica del trader,
        dando prioridad a la configuración del trader cuando está disponible.
        
        Args:
            trader_wallet: Dirección de la wallet del trader
            
        Returns:
            Diccionario con los valores de configuración de rate limiting
        """
        global_config = {
            "max_traders_per_token": self.config.max_traders_per_token,
            "max_open_tokens": self.config.max_open_tokens_per_trader,
            "max_open_positions_per_token": self.config.max_open_positions_per_token_per_trader,
            "min_open_trade_interval_seconds": self.config.min_open_trade_interval_seconds_per_trader
        }

        # Obtener información del trader
        trader_info = self.config.get_trader_info(trader_wallet)
        if not trader_info:
            # Si no hay trader_info, usar configuración global directamente
            return global_config

        # Obtener configuración específica del trader
        trader_config = self.config.get_trader_config(trader_info)
        if trader_config:
            return {
                "max_traders_per_token": global_config["max_traders_per_token"],
                "max_open_tokens": trader_config.max_open_tokens or global_config["max_open_tokens"],
                "max_open_positions_per_token": trader_config.max_open_positions_per_token or global_config["max_open_positions_per_token"],
                "min_open_trade_interval_seconds": trader_config.min_open_trade_interval_seconds or global_config["min_open_trade_interval_seconds"]
            }

        # Fallback a configuración global
        return global_config

    async def _log_async(self, message: str, details: str = ""):
        """Logging asíncrono para evitar bloqueos"""
        try:
            self._logger.info(f"{message}: {details}")
        except Exception as e:
            # Fallback a print si logging falla
            print(f"Log error: {e}")

    def _validate_trade_data(self, trade_data: TraderTradeData) -> bool:
        """
        Valida que el TradeData tenga toda la información necesaria y cumpla con las reglas
        
        Args:
            trade_data: Objeto TradeData con la información del trade
            
        Returns:
            True si el trade es válido
        """
        # Validar valores
        if not trade_data.trader_wallet:
            self._logger.warning("Trader wallet no puede estar vacío")
            return False

        if not trade_data.token_address:
            self._logger.warning("Token address no puede estar vacío")
            return False

        # Validar amount_sol usando Decimal para mayor precisión
        try:
            amount_decimal = Decimal(trade_data.amount_sol)
            if amount_decimal <= Decimal('0'):
                self._logger.warning("amount_sol debe ser mayor a 0")
                return False
        except (ValueError, TypeError, Exception) as e:
            self._logger.warning(f"amount_sol inválido: {trade_data.amount_sol} - Error: {e}")
            return False

        if trade_data.side not in ['buy', 'sell']:
            self._logger.warning("side debe ser 'buy' o 'sell'")
            return False

        # Verificar si es un trader que seguimos
        if not self.config.get_trader_info(trade_data.trader_wallet):
            self._logger.debug(f"Trader no seguido: {trade_data.trader_wallet}")
            return False

        return True

    def _create_trade_data_from_pumpfun(self, data: dict) -> TraderTradeData:
        """
        Crea un objeto TradeData desde los datos de PumpFun
        
        Args:
            data: Datos del trade en formato PumpFun
            
        Returns:
            Objeto TradeData con todos los campos mapeados
        """
        try:
            return TraderTradeData(
                # Información básica del trade
                trader_wallet=data.get('traderPublicKey', ''),
                side=data.get('txType', '').lower(),
                token_address=data.get('mint', ''),
                amount_sol=format(Decimal(str(data.get('solAmount', 0))), "f"),
                signature=data.get('signature', ''),

                # Información del token
                token_amount=format(Decimal(str(data.get('tokenAmount', 0))), "f"),
                new_token_balance=format(Decimal(str(data['newTokenBalance'])), "f") if 'newTokenBalance' in data else '',

                # Información del pool
                tokens_in_pool=format(Decimal(str(data['tokensInPool'])), "f") if 'tokensInPool' in data else '',
                sol_in_pool=format(Decimal(str(data['solInPool'])), "f") if 'solInPool' in data else '',

                # Información del pool/bonding curve
                pool=data.get('pool', ''),
                bonding_curve_key=data.get('bondingCurveKey', ''),
                v_tokens_in_bonding_curve=format(Decimal(str(data['vTokensInBondingCurve'])), "f") if 'vTokensInBondingCurve' in data else '',
                v_sol_in_bonding_curve=format(Decimal(str(data['vSolInBondingCurve'])), "f") if 'vSolInBondingCurve' in data else '',
                market_cap_sol=format(Decimal(str(data.get('marketCapSol', 0))), "f"),

                # Metadatos
                timestamp=datetime.now()
            )
        except Exception as e:
            self._logger.error(f"Error creando TradeData desde PumpFun: {e}")
            # Retornar un objeto vacío con valores por defecto
            return TraderTradeData(
                trader_wallet='', side='buy', token_address='', amount_sol='',
                signature='', token_amount='', new_token_balance='', pool='', tokens_in_pool='', sol_in_pool='',
                bonding_curve_key='', v_tokens_in_bonding_curve='',
                v_sol_in_bonding_curve='', market_cap_sol='', timestamp=datetime.now()
            )

    async def shutdown(self):
        """Cierra el callback de manera ordenada"""
        self._processing_active = False

        # Esperar a que se completen las tareas pendientes
        if self._processing_tasks:
            await asyncio.gather(*self._processing_tasks, return_exceptions=True)

        # Limpiar cola
        while not self._processing_queue.empty():
            try:
                self._processing_queue.get_nowait()
                self._processing_queue.task_done()
            except asyncio.QueueEmpty:
                break

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del callback"""
        stats = {
            **self.stats,
            'active_traders': len(self.config.traders),
            'queue_size': self._processing_queue.qsize(),
            'active_tasks': len(self._processing_tasks)
        }

        # Calcular tiempo desde el último trade si existe
        if self.stats['last_trade_time']:
            time_since_last = datetime.now() - self.stats['last_trade_time']
            stats['seconds_since_last_trade'] = time_since_last.total_seconds()
        else:
            stats['seconds_since_last_trade'] = None

        # Calcular tasas de éxito
        if self.stats['trades_received'] > 0:
            stats['validation_rate'] = (self.stats['trades_validated'] / self.stats['trades_received']) * 100
            stats['rejection_rate'] = (self.stats['trades_rejected'] / self.stats['trades_received']) * 100
        else:
            stats['validation_rate'] = 0.0
            stats['rejection_rate'] = 0.0

        return stats

    def reset_stats(self):
        """Resetea estadísticas"""
        self.stats = {
            'trades_received': 0,
            'trades_validated': 0,
            'trades_queued': 0,
            'trades_rejected': 0,
            'trades_processing': 0,
            'last_trade_time': None
        }
