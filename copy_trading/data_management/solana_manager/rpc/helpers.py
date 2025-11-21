# -*- coding: utf-8 -*-
"""
Funciones auxiliares para el cliente RPC de Solana.
"""
from typing import Dict, Any, List

from logging_system import AppLogger
from ...models import BalanceResponse, SignatureStatusesResponse
from .transaction_analyzer.analyzer import SolanaTxAnalyzer


async def get_transaction(
    signature: str,
    *,
    endpoint: str = "https://api.mainnet-beta.solana.com",
    commitment: str = "finalized",
    max_supported_transaction_version: int = 0,
    encoding: str = "jsonParsed",
) -> Dict[str, Any]:
    """Atajo funcional para obtener una transacción por signature."""
    logger = AppLogger("SolanaTxAnalyzer")
    logger.info(f"Getting transaction via helper function: {signature[:8]}...")
    try:
        async with SolanaTxAnalyzer(endpoint) as analyzer:
            return await analyzer._rpc_client.get_transaction(
                signature,
                commitment=commitment,
                max_supported_transaction_version=max_supported_transaction_version,
                encoding=encoding,
            )
    except Exception as e:
        logger.error(f"Error getting transaction {signature[:8]}...: {e}")
        raise


async def get_token_balances(
    owner_pubkey: str,
    *,
    endpoint: str = "https://api.mainnet-beta.solana.com",
    commitment: str = "finalized",
    encoding: str = "jsonParsed",
    include_zero_balances: bool = False,
) -> BalanceResponse:
    """Atajo funcional para obtener balances de tokens de un propietario."""
    logger = AppLogger("SolanaTxAnalyzer")
    logger.info(f"Getting token balances via helper function: {owner_pubkey[:8]}...")
    try:
        async with SolanaTxAnalyzer(endpoint) as analyzer:
            return await analyzer.get_token_balances(
                owner_pubkey,
                commitment=commitment,
                encoding=encoding,
                include_zero_balances=include_zero_balances,
            )
    except Exception as e:
        logger.error(f"Error getting token balances for {owner_pubkey[:8]}...: {e}")
        raise


async def get_sol_balance(
    account_pubkey: str,
    *,
    endpoint: str = "https://api.mainnet-beta.solana.com",
    commitment: str = "finalized",
) -> str:
    """Atajo funcional para obtener el balance de SOL de una cuenta."""
    logger = AppLogger("SolanaTxAnalyzer")
    logger.info(f"Getting SOL balance via helper function: {account_pubkey[:8]}...")
    try:
        async with SolanaTxAnalyzer(endpoint) as analyzer:
            return await analyzer.get_sol_balance(
                account_pubkey,
                commitment=commitment,
            )
    except Exception as e:
        logger.error(f"Error getting SOL balance for {account_pubkey[:8]}...: {e}")
        raise


async def get_signature_statuses(
    signatures: List[str],
    *,
    endpoint: str = "https://api.mainnet-beta.solana.com",
    search_transaction_history: bool = False,
) -> SignatureStatusesResponse:
    """Atajo funcional para obtener el estado de confirmación de firmas."""
    logger = AppLogger("SolanaTxAnalyzer")
    logger.info(f"Getting signature statuses via helper function: {len(signatures)} signatures")
    try:
        async with SolanaTxAnalyzer(endpoint) as analyzer:
            return await analyzer.get_signature_statuses(
                signatures,
                search_transaction_history=search_transaction_history,
            )
    except Exception as e:
        logger.error(f"Error getting signature statuses for {len(signatures)} signatures: {e}")
        raise
