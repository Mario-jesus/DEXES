# -*- coding: utf-8 -*-
"""
Callback para manejar el error de balance mínimo del websocket de PumpFun.
Cuando se detecta el error 'Minimum balance not met for PumpSwap websocket data.',
liquida automáticamente la posición abierta más antigua del sistema.
"""
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
from logging_system import AppLogger

from ..position_management.models import TraderTradeData, PositionTraderTradeData, OpenPosition
from ..transactions_management import TransactionExecutor
from ..position_management.managers import PositionQueueManager


class MinimumBalanceHandler:
    """
    Handler para gestionar el error de balance mínimo del websocket.
    Liquida automáticamente la posición más antigua cuando se detecta el error.
    """

    def __init__(
        self,
        system_wallet_address: str,
        transaction_executor: TransactionExecutor,
        position_queue_manager: PositionQueueManager,
        cooldown_seconds: int = 60
    ):
        """
        Inicializa el handler de balance mínimo.

        Args:
            system_wallet_address: Dirección de la wallet del sistema
            transaction_executor: Ejecutor de transacciones
            position_queue_manager: Manager de colas de posiciones
            cooldown_seconds: Tiempo de espera entre liquidaciones consecutivas (default: 60s)
        """
        self._logger = AppLogger(self.__class__.__name__)
        self._system_wallet_address = system_wallet_address
        self._transaction_executor = transaction_executor
        self._position_queue_manager = position_queue_manager
        self._cooldown_seconds = cooldown_seconds

        # Control de ejecución
        self._last_liquidation_time: Optional[datetime] = None
        self._is_processing = False
        self._lock = asyncio.Lock()

        self._logger.info(
            f"MinimumBalanceHandler inicializado - "
            f"Wallet: {system_wallet_address}, "
            f"Cooldown: {cooldown_seconds}s"
        )

    async def __call__(self, error_data: Dict[str, Any]) -> bool:
        """
        Maneja el error de balance mínimo liquidando la posición más antigua.

        Args:
            error_data: Datos del error recibido (debe contener 'errors' con el mensaje)

        Returns:
            True si se procesó y liquidó una posición, False si no
        """
        try:
            # Verificar que sea el error correcto
            if not self._is_minimum_balance_error(error_data):
                self._logger.debug("El error recibido no es un error de balance mínimo")
                return False

            self._logger.warning(
                f"Error de balance mínimo detectado: {error_data}"
            )

            # Verificar cooldown
            if not self._check_cooldown():
                self._logger.info(
                    f"Liquidación en cooldown. "
                    f"Última liquidación hace {self._get_seconds_since_last_liquidation():.1f}s"
                )
                return False

            # Verificar que no haya otro proceso ejecutándose
            if self._is_processing:
                self._logger.warning("Ya hay una liquidación en proceso, saltando")
                return False

            async with self._lock:
                self._is_processing = True
                try:
                    if not self._position_queue_manager.open_queue:
                        self._logger.warning("Cola de posiciones abiertas no inicializada")
                        return False

                    # Obtener la posición más antigua
                    oldest_position = await self._position_queue_manager.open_queue.get_oldest_position()

                    if not oldest_position:
                        self._logger.warning(
                            "No hay posiciones abiertas para liquidar"
                        )
                        return False

                    self._logger.info(
                        f"Posición más antigua identificada para liquidación:"
                        f" ID: {oldest_position.id},"
                        f" Trader: {oldest_position.trader_wallet},"
                        f" Token: {oldest_position.token_address},"
                        f" Creada: {oldest_position.created_at},"
                        f" Tokens: {oldest_position.amount_tokens_executed}"
                    )

                    # Liquidar la posición
                    success = await self._liquidate_position(oldest_position)

                    if success:
                        self._last_liquidation_time = datetime.now()
                        self._logger.info(
                            f"Posición {oldest_position.id} liquidada exitosamente"
                        )
                    else:
                        self._logger.error(
                            f"Error al liquidar posición {oldest_position.id}"
                        )

                    return success

                finally:
                    self._is_processing = False

        except Exception as e:
            self._logger.error(
                f"Error manejando error de balance mínimo: {e}",
                exc_info=True
            )
            self._is_processing = False
            return False

    async def _liquidate_position(self, position: OpenPosition) -> bool:
        """
        Liquida una posición abierta.

        Args:
            position: Posición a liquidar (OpenPosition)

        Returns:
            True si se liquidó exitosamente, False si no
        """
        try:
            # Validar que la posición tenga tokens para vender
            if not position.amount_tokens_executed or float(position.amount_tokens_executed) <= 0:
                self._logger.warning(
                    f"La posición {position.id} no tiene tokens ejecutados para liquidar"
                )
                return False

            self._logger.debug(
                f"Creando TraderTradeData para liquidación de posición {position.id}"
            )

            # Crear TraderTradeData para la liquidación
            trader_trade_data = TraderTradeData(
                trader_wallet=self._system_wallet_address,
                side="sell",
                token_address=position.token_address,
                amount_sol="",
                signature="",
                token_amount=position.amount_tokens_executed,
                new_token_balance="",
                pool="auto",
                bonding_curve_key="",
                v_tokens_in_bonding_curve="",
                v_sol_in_bonding_curve="",
                market_cap_sol="",
                timestamp=datetime.now(),
            )

            self._logger.debug(
                f"Creando PositionTraderTradeData para liquidación - "
                f"Cantidad: {position.amount_tokens_executed}"
            )

            # Crear PositionTraderTradeData
            position_trader_trade_data = PositionTraderTradeData(
                trader_trade_data=trader_trade_data,
                copy_amount_tokens=position.amount_tokens_executed,
                denominate_in_sol=False,
                is_liquidation=True
            )

            # Agregar metadata con información de la posición original
            position_trader_trade_data.add_metadata('original_position_id', position.id)
            position_trader_trade_data.add_metadata('liquidation_reason', 'minimum_balance_error')
            position_trader_trade_data.add_metadata('original_trader', position.trader_wallet)

            self._logger.info(
                f"Ejecutando trade de liquidación para posición {position.id}..."
            )

            # Ejecutar el trade de liquidación
            success, signature, error_message = await self._transaction_executor.execute_trade(
                position_trader_trade_data
            )

            if success and signature:
                self._logger.info(
                    f"Trade de liquidación ejecutado exitosamente: {signature}"
                )

                # Procesar la posición ejecutada
                self._logger.debug(
                    f"Procesando posición de liquidación ejecutada - Signature: {signature}"
                )

                await self._position_queue_manager.process_executed_position(
                    position_trade_data=position_trader_trade_data,
                    signature=signature,
                )

                self._logger.info(
                    f"Posición de liquidación {position.id} procesada exitosamente"
                )
                return True
            else:
                self._logger.error(
                    f"Error al ejecutar trade de liquidación: {error_message}"
                )
                return False

        except Exception as e:
            self._logger.error(
                f"Error al liquidar posición {position.id}: {e}",
                exc_info=True
            )
            return False

    def _is_minimum_balance_error(self, error_data: Dict[str, Any]) -> bool:
        """
        Verifica si el error es un error de balance mínimo.

        Args:
            error_data: Datos del error

        Returns:
            True si es un error de balance mínimo, False si no
        """
        if not isinstance(error_data, dict):
            return False

        errors = error_data.get('errors', '')
        if not errors:
            return False

        return 'Minimum balance not met' in str(errors)

    def _check_cooldown(self) -> bool:
        """
        Verifica si ha pasado suficiente tiempo desde la última liquidación.

        Returns:
            True si se puede liquidar, False si está en cooldown
        """
        if self._last_liquidation_time is None:
            return True

        seconds_since_last = self._get_seconds_since_last_liquidation()
        return seconds_since_last >= self._cooldown_seconds

    def _get_seconds_since_last_liquidation(self) -> float:
        """
        Obtiene los segundos transcurridos desde la última liquidación.

        Returns:
            Segundos desde la última liquidación, 0 si nunca se ha liquidado
        """
        if self._last_liquidation_time is None:
            return 0.0

        delta = datetime.now() - self._last_liquidation_time
        return delta.total_seconds()

    async def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas del handler.

        Returns:
            Diccionario con estadísticas
        """
        return {
            'last_liquidation_time': self._last_liquidation_time.isoformat() if self._last_liquidation_time else None,
            'seconds_since_last_liquidation': self._get_seconds_since_last_liquidation(),
            'is_processing': self._is_processing,
            'cooldown_seconds': self._cooldown_seconds,
            'can_liquidate': self._check_cooldown() and not self._is_processing
        }
