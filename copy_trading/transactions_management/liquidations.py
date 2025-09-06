# -*- coding: utf-8 -*-
"""
Módulo de Liquidaciones para Copy Trading.
"""
import asyncio
from datetime import datetime
from logging_system import AppLogger
from ..data_management.models.analyzer_models import TokenBalance
from ..data_management.solana_manager import SolanaTxAnalyzer
from ..position_management.models import PositionTraderTradeData, TraderTradeData
from ..position_management.managers.position_queue_manager import PositionQueueManager
from .transactions import TransactionExecutor


class Liquidations:

    def __init__(self,
                system_wallet_address: str,
                solana_analyzer: SolanaTxAnalyzer,
                transaction_executor: TransactionExecutor,
                position_queue_manager: PositionQueueManager):
        self._logger = AppLogger(self.__class__.__name__)
        self._solana_analyzer = solana_analyzer
        self._system_wallet_address = system_wallet_address
        self._transaction_executor = transaction_executor
        self._position_queue_manager = position_queue_manager

    async def run(self):
        self._logger.info("Liquidaciones iniciadas")
        balance_response = await self._solana_analyzer.get_token_balances(
            owner_pubkey=self._system_wallet_address
        )
        self._logger.info(f"Balance: {balance_response.tokens}")

        if balance_response.total_tokens == 0:
            self._logger.info("No se encontraron tokens en la wallet del sistema")
            return

        for token in balance_response.tokens:
            if token.ui_amount < 1:
                self._logger.info(f"El mint {token.mint} tiene balance menor a 1 token, no se liquida")
                continue

            await self._liquidate_token(token)
            await asyncio.sleep(1)

    async def _liquidate_token(self, token: TokenBalance) -> None:
        try:
            self._logger.info(f"Liquidando token: {token.mint}")
            trader_trade_data = TraderTradeData(
                trader_wallet=self._system_wallet_address,
                side="sell",
                token_address=token.mint,
                amount_sol="",
                signature="",
                token_amount=token.ui_amount_string,
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
                copy_amount_tokens=token.ui_amount_string,
                is_liquidation=True
            )
            success, signature, error_message = await self._transaction_executor.execute_trade(
                position_trader_trade_data
            )
            if success and signature:
                self._logger.info(f"Trade ejecutado exitosamente: {signature}")
                await self._position_queue_manager.process_executed_position(
                    position_trade_data=position_trader_trade_data,
                    signature=signature,
                )
            else:
                self._logger.error(f"Error al ejecutar trade: {error_message} | signature: {signature}")
        except Exception as e:
            self._logger.error(f"Error al liquidar token: {e}", exc_info=True)
