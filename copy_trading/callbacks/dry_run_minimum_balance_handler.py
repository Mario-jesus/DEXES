# -*- coding: utf-8 -*-
"""
Mock de MinimumBalanceHandler para modo Dry Run.

Se comporta como el handler real pero sin ejecutar operaciones on-chain.
Utiliza el TransactionExecutor en modo Dry Run y las colas existentes para
liquidar la posición abierta más antigua cuando recibe el error correspondiente.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

from logging_system import AppLogger
from ..position_management.models import TraderTradeData, PositionTraderTradeData, OpenPosition
from ..transactions_management import TransactionExecutorProtocol
from .protocols import MinimumBalanceHandlerProtocol
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..position_management.managers import PositionQueueManager


class DryRunMinimumBalanceHandler(MinimumBalanceHandlerProtocol):
    """
    Handler Dry Run para gestionar el error de balance mínimo.
    """

    def __init__(
        self,
        *,
        system_wallet_address: str,
        transaction_executor: TransactionExecutorProtocol,
        position_queue_manager: "PositionQueueManager",
        cooldown_seconds: int = 60,
    ) -> None:
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
            f"[DRY RUN] MinimumBalanceHandler inicializado - Wallet: {system_wallet_address}, Cooldown: {cooldown_seconds}s"
        )

    async def __call__(self, error_data: Dict[str, Any]) -> bool:
        try:
            if not self._is_minimum_balance_error(error_data):
                self._logger.debug("[DRY RUN] Error recibido no es de balance mínimo")
                return False

            self._logger.warning(f"[DRY RUN] Error de balance mínimo detectado: {error_data}")

            if not self._check_cooldown():
                self._logger.info(
                    f"[DRY RUN] Liquidación en cooldown. Última: {self._get_seconds_since_last_liquidation():.1f}s"
                )
                return False

            if self._is_processing:
                self._logger.warning("[DRY RUN] Ya hay una liquidación en proceso, saltando")
                return False

            async with self._lock:
                self._is_processing = True
                try:
                    if not self._position_queue_manager.open_queue:
                        self._logger.warning("[DRY RUN] Cola de abiertas no inicializada")
                        return False

                    oldest_position = await self._position_queue_manager.open_queue.get_oldest_position()
                    if not oldest_position:
                        self._logger.warning("[DRY RUN] No hay posiciones abiertas para liquidar")
                        return False

                    self._logger.info(
                        f"[DRY RUN] Posición más antigua a liquidar: {oldest_position.id} | Token: {oldest_position.token_address} | Tokens: {oldest_position.amount_tokens_executed}"
                    )

                    success = await self._liquidate_position(oldest_position)
                    if success:
                        self._last_liquidation_time = datetime.now()
                        self._logger.info(f"[DRY RUN] Posición {oldest_position.id} liquidada (simulada)")
                    else:
                        self._logger.error(f"[DRY RUN] Error al liquidar posición {oldest_position.id}")

                    return success
                finally:
                    self._is_processing = False
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error manejando balance mínimo: {e}", exc_info=True)
            self._is_processing = False
            return False

    async def _liquidate_position(self, position: OpenPosition) -> bool:
        try:
            if not position.amount_tokens_executed or float(position.amount_tokens_executed) <= 0:
                self._logger.warning(
                    f"[DRY RUN] Posición {position.id} sin tokens ejecutados para liquidar"
                )
                return False

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

            position_trader_trade_data = PositionTraderTradeData(
                trader_trade_data=trader_trade_data,
                copy_amount_tokens=position.amount_tokens_executed,
                denominate_in_sol=False,
                is_liquidation=True,
            )

            position_trader_trade_data.add_metadata('original_position_id', position.id)
            position_trader_trade_data.add_metadata('liquidation_reason', 'minimum_balance_error')
            position_trader_trade_data.add_metadata('original_trader', position.trader_wallet)

            success, signature, error_message = await self._transaction_executor.execute_trade(
                position_trader_trade_data
            )

            if success and signature:
                await self._position_queue_manager.process_executed_position(
                    position_trade_data=position_trader_trade_data,
                    signature=signature,
                )
                return True

            self._logger.error(
                f"[DRY RUN] Error al ejecutar trade de liquidación: {error_message}"
            )
            return False
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error en liquidación simulada: {e}", exc_info=True)
            return False

    def _is_minimum_balance_error(self, error_data: Dict[str, Any]) -> bool:
        if not isinstance(error_data, dict):
            return False
        errors = error_data.get('errors', '')
        if not errors:
            return False
        return 'Minimum balance not met' in str(errors)

    def _check_cooldown(self) -> bool:
        if self._last_liquidation_time is None:
            return True
        return self._get_seconds_since_last_liquidation() >= self._cooldown_seconds

    def _get_seconds_since_last_liquidation(self) -> float:
        if self._last_liquidation_time is None:
            return 0.0
        delta = datetime.now() - self._last_liquidation_time
        return delta.total_seconds()

    async def get_stats(self) -> Dict[str, Any]:
        return {
            'last_liquidation_time': self._last_liquidation_time.isoformat() if self._last_liquidation_time else None,
            'seconds_since_last_liquidation': self._get_seconds_since_last_liquidation(),
            'is_processing': self._is_processing,
            'cooldown_seconds': self._cooldown_seconds,
            'can_liquidate': self._check_cooldown() and not self._is_processing,
            'mode': 'dry_run',
        }
