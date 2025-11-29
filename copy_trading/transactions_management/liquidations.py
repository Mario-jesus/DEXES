# -*- coding: utf-8 -*-
"""
Módulo de Liquidaciones para Copy Trading.
"""
import asyncio
from datetime import datetime
from typing import Dict, Any
from logging_system import AppLogger
from ..data_management.models.analyzer_models import TokenBalance
from copy_trading.protocols import SolanaTxAnalyzerProtocol
from ..position_management.models import PositionTraderTradeData, TraderTradeData
from .protocols import TransactionExecutorProtocol
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..position_management.managers.position_queue_manager import PositionQueueManager


class Liquidations:

    def __init__(self,
                system_wallet_address: str,
                solana_analyzer: SolanaTxAnalyzerProtocol,
                transaction_executor: TransactionExecutorProtocol,
                position_queue_manager: "PositionQueueManager"):
        self._logger = AppLogger(self.__class__.__name__)
        self._solana_analyzer = solana_analyzer
        self._system_wallet_address = system_wallet_address
        self._transaction_executor = transaction_executor
        self._position_queue_manager = position_queue_manager

        self._logger.debug(f"Sistema de liquidaciones inicializado - Wallet del sistema: {system_wallet_address}")
        self._logger.debug(f"Componentes configurados - SolanaAnalyzer: {solana_analyzer is not None}, TransactionExecutor: {transaction_executor is not None}, PositionQueueManager: {position_queue_manager is not None}")

    async def run(self):
        self._logger.info("Liquidaciones iniciadas")
        self._logger.debug(f"Obteniendo balances de tokens para wallet del sistema: {self._system_wallet_address}")

        balance_response = await self._solana_analyzer.get_token_balances(
            owner_pubkey=self._system_wallet_address
        )
        self._logger.info(f"Balance: {balance_response.tokens}")
        self._logger.debug(f"Total de tokens encontrados: {balance_response.total_tokens}")

        if balance_response.total_tokens == 0:
            self._logger.info("No se encontraron tokens en la wallet del sistema")
            return

        self._logger.debug(f"Iniciando proceso de liquidación para {len(balance_response.tokens)} tokens")
        liquidated_count = 0
        skipped_count = 0

        for i, token in enumerate(balance_response.tokens, 1):
            self._logger.debug(f"Procesando token {i}/{len(balance_response.tokens)}: {token.mint[:8]}... (balance: {token.ui_amount})")

            if token.ui_amount < 1:
                self._logger.info(f"El mint {token.mint} tiene balance menor a 1 token, no se liquida")
                skipped_count += 1
                continue

            self._logger.debug(f"Iniciando liquidación del token {token.mint[:8]}... con balance {token.ui_amount}")
            await self._liquidate_token(token)
            liquidated_count += 1

            self._logger.debug(f"Esperando 1 segundo antes del siguiente token...")
            await asyncio.sleep(1)

        self._logger.info(f"Proceso de liquidación completado - Liquidados: {liquidated_count}, Omitidos: {skipped_count}")

    async def _liquidate_token(self, token: TokenBalance) -> None:
        try:
            self._logger.info(f"Liquidando token: {token.mint}")
            self._logger.debug(f"Creando TraderTradeData para liquidación - Token: {token.mint[:8]}..., Cantidad: {token.ui_amount_string}")

            trader_trade_data = TraderTradeData(
                trader_wallet=self._system_wallet_address,
                side="sell",
                token_address=token.mint,
                amount_sol="",
                signature="",
                token_amount=token.ui_amount_string,
                tokens_in_pool="",
                sol_in_pool="",
                new_token_balance="",
                pool="auto",
                bonding_curve_key="",
                v_tokens_in_bonding_curve="",
                v_sol_in_bonding_curve="",
                market_cap_sol="",
                timestamp=datetime.now(),
            )

            self._logger.debug(f"Creando PositionTraderTradeData para liquidación - Copy amount: {token.ui_amount_string}")
            position_trader_trade_data = PositionTraderTradeData(
                trader_trade_data=trader_trade_data,
                copy_amount_tokens=token.ui_amount_string,
                denominate_in_sol=False,
                is_liquidation=True
            )

            self._logger.debug(f"Ejecutando trade de liquidación para token {token.mint[:8]}...")
            success, signature, error_message = await self._transaction_executor.execute_trade(
                position_trader_trade_data
            )

            if success and signature:
                self._logger.info(f"Trade ejecutado exitosamente: {signature}")
                self._logger.debug(f"Procesando posición ejecutada para liquidación - Signature: {signature}")
                await self._position_queue_manager.process_executed_position(
                    position_trade_data=position_trader_trade_data,
                    signature=signature,
                )
                self._logger.debug(f"Posición de liquidación procesada exitosamente")
            else:
                self._logger.error(f"Error al ejecutar trade: {error_message} | signature: {signature}")
                self._logger.debug(f"Detalles del error de liquidación - Token: {token.mint[:8]}..., Error: {error_message}")
        except Exception as e:
            self._logger.error(f"Error al liquidar token: {e}", exc_info=True)
            self._logger.debug(f"Error detallado en liquidación - Token: {token.mint[:8]}..., Exception: {type(e).__name__}")

    async def get_stats(self) -> Dict[str, Any]:
        return {
            'mode': 'real'
        }
