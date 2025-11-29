# -*- coding: utf-8 -*-
"""
Mock de Liquidaciones para modo Dry Run.

Simula el proceso de liquidar tokens disponibles en la wallet del sistema sin
ejecutar transacciones on-chain reales. Utiliza el analizador Dry Run para
obtener balances agregados desde la cola de posiciones abiertas y ejecuta
operaciones con el TransactionExecutor en modo Dry Run.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

from logging_system import AppLogger
from ..data_management.models.analyzer_models import TokenBalance
from copy_trading.protocols import SolanaTxAnalyzerProtocol
from ..position_management.models import PositionTraderTradeData, TraderTradeData
from .protocols import TransactionExecutorProtocol
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..position_management.managers.position_queue_manager import PositionQueueManager


class DryRunLiquidations:

    def __init__(
        self,
        *,
        system_wallet_address: str,
        solana_analyzer: SolanaTxAnalyzerProtocol,
        transaction_executor: TransactionExecutorProtocol,
        position_queue_manager: "PositionQueueManager",
    ) -> None:
        self._logger = AppLogger(self.__class__.__name__)
        self._solana_analyzer = solana_analyzer
        self._system_wallet_address = system_wallet_address
        self._transaction_executor = transaction_executor
        self._position_queue_manager = position_queue_manager

        self._logger.debug(
            f"[DRY RUN] Sistema de liquidaciones inicializado - Wallet del sistema: {system_wallet_address}"
        )
        self._logger.debug(
            f"[DRY RUN] Componentes - Analyzer(dry): {solana_analyzer is not None}, Executor(dry): {transaction_executor is not None}, PQM: {position_queue_manager is not None}"
        )

    async def run(self) -> None:
        self._logger.info("[DRY RUN] Liquidaciones iniciadas")
        self._logger.debug(
            f"[DRY RUN] Obteniendo balances (simulados) para wallet: {self._system_wallet_address}"
        )

        balance_response = await self._solana_analyzer.get_token_balances(
            owner_pubkey=self._system_wallet_address
        )
        self._logger.info(f"[DRY RUN] Balance encontrado: {balance_response.tokens}")
        self._logger.debug(
            f"[DRY RUN] Total de tokens encontrados: {balance_response.total_tokens}"
        )

        if balance_response.total_tokens == 0:
            self._logger.info("[DRY RUN] No se encontraron tokens para liquidar")
            return

        self._logger.debug(
            f"[DRY RUN] Iniciando proceso de liquidación para {len(balance_response.tokens)} tokens"
        )
        liquidated_count = 0
        skipped_count = 0

        for i, token in enumerate(balance_response.tokens, 1):
            self._logger.debug(
                f"[DRY RUN] Procesando token {i}/{len(balance_response.tokens)}: {token.mint[:8]}... (balance: {token.ui_amount})"
            )

            if token.ui_amount < 1:
                self._logger.info(
                    f"[DRY RUN] Mint {token.mint} con balance menor a 1 token, se omite"
                )
                skipped_count += 1
                continue

            self._logger.debug(
                f"[DRY RUN] Iniciando liquidación simulada del token {token.mint[:8]}... con balance {token.ui_amount}"
            )
            await self._liquidate_token(token)
            liquidated_count += 1

            self._logger.debug("[DRY RUN] Esperando 0.3s antes del siguiente token...")
            await asyncio.sleep(0.3)

        self._logger.info(
            f"[DRY RUN] Proceso de liquidación completado - Liquidados: {liquidated_count}, Omitidos: {skipped_count}"
        )

    async def _liquidate_token(self, token: TokenBalance) -> None:
        try:
            self._logger.info(f"[DRY RUN] Liquidando token (simulado): {token.mint}")
            self._logger.debug(
                f"[DRY RUN] Creando TraderTradeData (sell) - Token: {token.mint[:8]}..., Cantidad: {token.ui_amount_string}"
            )

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

            self._logger.debug(
                f"[DRY RUN] Creando PositionTraderTradeData para liquidación - Copy amount: {token.ui_amount_string}"
            )
            position_trader_trade_data = PositionTraderTradeData(
                trader_trade_data=trader_trade_data,
                copy_amount_tokens=token.ui_amount_string,
                denominate_in_sol=False,
                is_liquidation=True,
            )

            self._logger.debug(
                f"[DRY RUN] Ejecutando trade de liquidación (simulado) para {token.mint[:8]}..."
            )
            success, signature, error_message = await self._transaction_executor.execute_trade(
                position_trader_trade_data
            )

            if success and signature:
                self._logger.info(f"[DRY RUN] Trade simulado exitoso: {signature}")
                self._logger.debug(
                    f"[DRY RUN] Procesando posición ejecutada (simulada) - Signature: {signature}"
                )
                await self._position_queue_manager.process_executed_position(
                    position_trade_data=position_trader_trade_data,
                    signature=signature,
                )
                self._logger.debug(
                    f"[DRY RUN] Posición de liquidación (simulada) procesada exitosamente"
                )
            else:
                self._logger.error(
                    f"[DRY RUN] Error al ejecutar trade simulado: {error_message} | signature: {signature}"
                )
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error simulando liquidación: {e}", exc_info=True)

    async def get_stats(self) -> Dict[str, Any]:
        return {
            'mode': 'dry_run'
        }
