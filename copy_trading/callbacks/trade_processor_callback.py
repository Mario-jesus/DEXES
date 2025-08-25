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
from ..position_management.queues import PendingPositionQueue
from ..validation import ValidationEngine
from ..transactions_management import CopyAmountCalculator
from ..data_management import TokenTraderManager
from logging_system import AppLogger

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
    traders_per_token: int = 0


@dataclass(slots=True)
class TraderTokenRateLimitData:
    """Datos de rate limiting para la combinación trader-token"""
    open_positions_per_token: int = 0


class TradeProcessorCallback:
    """Callback para procesar trades y replicarlos automáticamente"""

    def __init__(self, 
                    config: CopyTradingConfig,
                    pending_position_queue: PendingPositionQueue,
                    validation_engine: ValidationEngine,
                    token_trader_manager: TokenTraderManager):
        """
        Inicializa el callback
        
        Args:
            config: Configuración del sistema
            pending_position_queue: Cola de posiciones pendientes
            validation_engine: Motor de validaciones
            token_trader_manager: Gestor de cache inteligente
        """
        self.config = config
        self.pending_position_queue = pending_position_queue
        self.validation_engine = validation_engine
        self._token_trader_manager = token_trader_manager
        self._logger = AppLogger(self.__class__.__name__)
        self._amount_calculator = CopyAmountCalculator(config)

        # Cache de rate limiting para evitar procesar trades que violen límites de configuración
        # keys: trader_wallet -> TraderRateLimitData, token_address -> TokenRateLimitData, trader_wallet_token_address -> TraderTokenRateLimitData
        self._rate_limit_cache: TTLCache[str, Union[TokenRateLimitData, TraderRateLimitData, TraderTokenRateLimitData]] = TTLCache(maxsize=1000, ttl=60)

        # Validar que pending_position_queue no sea None
        if self.pending_position_queue is None:
            raise ValueError("pending_position_queue no puede ser None")

        # Cola interna para procesamiento asíncrono
        self._processing_queue: asyncio.Queue[TraderTradeData] = asyncio.Queue(maxsize=1000)
        self._processing_tasks: Set[asyncio.Task] = set()

        # Flag para controlar el procesamiento
        self._processing_active = True

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

            if not self._validate_trade_data_basic(trade_data):
                self.stats['trades_rejected'] += 1
                asyncio.create_task(self._log_async("Trade rechazado - validación básica", data.get('signature', 'N/A')))
                return

            if not self._validate_trade_rate_limits(trade_data):
                self.stats['trades_rejected'] += 1
                asyncio.create_task(self._log_async("Trade rechazado - límites de rate", data.get('signature', 'N/A')))
                return

            # Añadir a cola de procesamiento para operaciones lentas
            try:
                self._processing_queue.put_nowait(trade_data)
                self.stats['trades_processing'] += 1
            except asyncio.QueueFull:
                self._logger.warning("Cola de procesamiento llena, trade descartado")
                self.stats['trades_rejected'] += 1

        except Exception as e:
            self._logger.error(f"Error en procesamiento inicial: {e}")
            self.stats['trades_rejected'] += 1

    async def _processing_worker(self):
        """Worker que procesa trades de la cola interna"""
        while self._processing_active:
            try:
                # Obtener trade de la cola con timeout
                trade_data = await asyncio.wait_for(
                    self._processing_queue.get(), timeout=1.0
                )

                # Procesar trade en task separado
                task = asyncio.create_task(self._process_trade_async(trade_data))
                self._processing_tasks.add(task)
                task.add_done_callback(self._processing_tasks.discard)

                self._processing_queue.task_done()

            except asyncio.TimeoutError:
                # Timeout normal, continuar
                continue
            except Exception as e:
                self._logger.error(f"Error en processing worker: {e}")

    async def _process_trade_async(self, trade_data: TraderTradeData):
        """Procesa un trade de manera asíncrona con todas las validaciones"""
        try:
            # Calcular montos de copia
            copy_amount_sol = self._amount_calculator.calculate_copy_amount(
                trade_data.trader_wallet, trade_data.amount_sol
            )

            copy_amount_tokens = self._amount_calculator.calculate_copy_amount(
                trade_data.trader_wallet, trade_data.token_amount
            )

            # Validación avanzada (operación lenta)
            is_valid, validation_checks = await self.validation_engine.validate_trade(
                trader_wallet=trade_data.trader_wallet,
                token_address=trade_data.token_address,
                amount_sol=copy_amount_sol,
                amount_tokens=copy_amount_tokens,
                side=trade_data.side
            )

            if not is_valid:
                error_msg = '; '.join(
                    check.message for check in validation_checks if check.result.value == 'failed'
                ) or 'Validación fallida'

                await self._log_async("Trade no válido", f"{error_msg} | {trade_data.trader_wallet}")
                self.stats['trades_rejected'] += 1
                return

            # Trade válido - crear posición y encolar
            self.stats['trades_validated'] += 1

            await self._log_async("Trade válido", f"{trade_data.side} {trade_data.amount_sol} SOL")

            position = PositionTraderTradeData(trade_data, copy_amount_sol, copy_amount_tokens)

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

        # Para operaciones sell, solo actualizar contadores sin validar límites
        if trade_data.side == 'sell':
            self._logger.debug("Operación de tipo 'sell', actualizando contadores y permitiendo trade.")
            self._update_rate_limits_for_sell(trade_data)
            return True

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
            if (max_traders_per_token and token_cache.traders_per_token >= max_traders_per_token and not trader_already_in_token) or (
                max_traders_per_token and current_traders_per_token >= max_traders_per_token and not trader_already_in_token):
                self._logger.info(f"Trade rechazado - máximo de traders por token alcanzado: {trade_data.token_address}")
                return False
            else:
                if not trader_already_in_token:
                    token_cache.traders_per_token += 1
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

    def _update_rate_limits_for_sell(self, trade_data: TraderTradeData) -> None:
        """
        Actualiza los contadores de rate limiting para operaciones de venta (sell)
        
        Para operaciones sell, decrementa los contadores en los dataclasses
        pero mantiene que nunca sean negativos.
        
        Args:
            trade_data: Objeto TradeData con la información del trade
        """
        # Claves para acceder al cache
        trader_key = f"{trade_data.trader_wallet}"
        token_key = f"{trade_data.token_address}"
        trader_token_key = f"{trade_data.trader_wallet}_{trade_data.token_address}"

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
                token_cache.traders_per_token = max(0, token_cache.traders_per_token - 1)
                self._rate_limit_cache[token_key] = token_cache

        # Actualizar contador de posiciones abiertas por token por trader
        if trader_token_key in self._rate_limit_cache:
            trader_token_cache = self._rate_limit_cache[trader_token_key]
            if isinstance(trader_token_cache, TraderTokenRateLimitData):
                trader_token_cache.open_positions_per_token = max(0, trader_token_cache.open_positions_per_token - 1)
                self._rate_limit_cache[trader_token_key] = trader_token_cache

        self._logger.debug(f"Contadores decrementados para sell: {trade_data.trader_wallet} - {trade_data.token_address}")

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
                new_token_balance=format(Decimal(str(data.get('newTokenBalance', 0))), "f"),

                # Información del pool/bonding curve
                pool=data.get('pool', ''),
                bonding_curve_key=data.get('bondingCurveKey', ''),
                v_tokens_in_bonding_curve=format(Decimal(str(data.get('vTokensInBondingCurve', 0))), "f"),
                v_sol_in_bonding_curve=format(Decimal(str(data.get('vSolInBondingCurve', 0))), "f"),
                market_cap_sol=format(Decimal(str(data.get('marketCapSol', 0))), "f"),

                # Metadatos
                timestamp=datetime.now()
            )
        except Exception as e:
            self._logger.error(f"Error creando TradeData desde PumpFun: {e}")
            # Retornar un objeto vacío con valores por defecto
            return TraderTradeData(
                trader_wallet='', side='buy', token_address='', amount_sol='',
                signature='', token_amount='', new_token_balance='', pool='',
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
