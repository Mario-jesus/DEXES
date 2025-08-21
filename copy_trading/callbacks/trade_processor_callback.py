# -*- coding: utf-8 -*-
"""
Callback especializado para Copy Trading
"""
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

        # Estadísticas
        self.stats = {
            'trades_received': 0,
            'trades_validated': 0,
            'trades_queued': 0,
            'trades_rejected': 0,
            'last_trade_time': None
        }

    async def __call__(self, data: dict) -> None:
        """
        Procesa un trade recibido
        
        Args:
            data: Datos del trade en formato PumpFun
        """
        try:
            # Incrementar contador
            self.stats['trades_received'] += 1

            self._logger.info(f"Trade recibido: {data.get('signature', 'N/A')}")

            # Crear objeto TradeData estructurado a partir de los datos crudos
            trade_data = self._create_trade_data_from_pumpfun(data)

            # Validar datos del trade
            if not self._validate_trade_data(trade_data):
                self._logger.warning(f"Trade inválido o no seguido recibido: {data}")
                self.stats['trades_rejected'] += 1
                return

            # Calcular el monto a copiar según la configuración
            copy_amount_sol = self._amount_calculator.calculate_copy_amount(
                trade_data.trader_wallet, trade_data.amount_sol
            )

            copy_amount_tokens = self._amount_calculator.calculate_copy_amount(
                trade_data.trader_wallet, trade_data.token_amount
            )

            # Validar trade con el motor, usando el monto a copiar
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

                self._logger.info(
                    f"Trade no válido: {error_msg} | trader: {trade_data.trader_wallet} | token: {trade_data.token_address}"
                )
                for check in validation_checks:
                    if check.result.value == 'failed':
                        self._logger.info(
                            f"Validación: {check.name} | Resultado: {check.result.value} | Mensaje: {str(check.message)} | Detalles: {str(check.details)}"
                        )

                self.stats['trades_rejected'] += 1
                return

            # Incrementar contador de trades válidos
            self.stats['trades_validated'] += 1

            self._logger.info(f"Validando trade: {trade_data.side} {trade_data.amount_sol} SOL de {trade_data.token_address}")

            position = PositionTraderTradeData(trade_data, copy_amount_sol, copy_amount_tokens)

            # Verificar que pending_position_queue esté inicializado
            if self.pending_position_queue is None:
                self._logger.error("pending_position_queue no está inicializado")
                self.stats['trades_rejected'] += 1
                return

            await self.pending_position_queue.add_position(position)
            self.stats['trades_queued'] += 1
            self.stats['last_trade_time'] = datetime.now()
            self._logger.info(f"Trade añadido a la cola - ID: {trade_data.signature}")

        except Exception as e:
            self._logger.error(f"Error procesando trade: {e}")
            self.stats['trades_rejected'] += 1

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

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del callback"""
        stats = {
            **self.stats,
            'active_traders': len(self.config.traders)
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
            'last_trade_time': None
        }
