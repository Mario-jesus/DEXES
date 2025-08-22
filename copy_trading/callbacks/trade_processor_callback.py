# -*- coding: utf-8 -*-
"""
Callback especializado para Copy Trading
"""
import asyncio
from typing import Dict, Any
from datetime import datetime
from decimal import Decimal, getcontext

from ..config import CopyTradingConfig
from ..position_management.models import TraderTradeData, PositionTraderTradeData
from ..position_management.queues import PendingPositionQueue
from ..validation import ValidationEngine
from ..transactions_management import CopyAmountCalculator
from logging_system import AppLogger

# Configurar precisión decimal según preferencias del usuario
getcontext().prec = 26


class TradeProcessorCallback:
    """Callback para procesar trades y replicarlos automáticamente"""

    def __init__(self, 
                    config: CopyTradingConfig,
                    pending_position_queue: PendingPositionQueue,
                    validation_engine: ValidationEngine):
        """
        Inicializa el callback
        
        Args:
            config: Configuración del sistema
            pending_position_queue: Cola de posiciones pendientes
            validation_engine: Motor de validaciones
        """
        self.config = config
        self.pending_position_queue = pending_position_queue
        self.validation_engine = validation_engine
        self._logger = AppLogger(self.__class__.__name__)
        self._amount_calculator = CopyAmountCalculator(config)

        # Validar que pending_position_queue no sea None
        if self.pending_position_queue is None:
            raise ValueError("pending_position_queue no puede ser None")

        # Cola interna para procesamiento asíncrono
        self._processing_queue = asyncio.Queue(maxsize=1000)
        self._processing_tasks = set()

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

            if not self._validate_trade_data_fast(trade_data):
                self.stats['trades_rejected'] += 1
                asyncio.create_task(self._log_async("Trade rechazado - validación básica", data.get('signature', 'N/A')))
                return

            # Añadir a cola de procesamiento para operaciones lentas
            try:
                self._processing_queue.put_nowait((trade_data, data))
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
                trade_data, original_data = await asyncio.wait_for(
                    self._processing_queue.get(), timeout=1.0
                )

                # Procesar trade en task separado
                task = asyncio.create_task(self._process_trade_async(trade_data, original_data))
                self._processing_tasks.add(task)
                task.add_done_callback(self._processing_tasks.discard)

            except asyncio.TimeoutError:
                # Timeout normal, continuar
                continue
            except Exception as e:
                self._logger.error(f"Error en processing worker: {e}")

    async def _process_trade_async(self, trade_data: TraderTradeData, original_data: dict):
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

    def _validate_trade_data_fast(self, trade_data: TraderTradeData) -> bool:
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
