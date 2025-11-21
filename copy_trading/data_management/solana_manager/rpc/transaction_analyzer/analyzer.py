# -*- coding: utf-8 -*-
"""
Analizador principal de transacciones de Solana.
Orquestador que coordina los módulos especializados.
"""
import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from logging_system import AppLogger
from ....models import (
    TransactionAnalysis,
    BalanceResponse,
    SignatureStatus,
    SignatureStatusesResponse,
    SignaturesWithStatuses,
)
from ..client import SolanaRPCClient
from ..utils import lamports_to_sol_str, calculate_price_sol_per_token

from .balance_parser import BalanceParser
from .transaction_analyzer import TransactionAnalyzer
from .detected_errors import DetectedErrors

if TYPE_CHECKING:
    from copy_trading.position_management.queues import OpenPositionQueue
    from ..models.enhanced_transactions import EnhancedTransactionResponse


class SolanaTxAnalyzer:
    """Analizador de transacciones de Solana usando composición con módulos especializados."""

    def __init__(
        self,
        base_rpc_url: str = "https://mainnet.helius-rpc.com",
        *,
        api_key: Optional[str] = None,
        session: Optional[Any] = None,
        request_timeout_s: float = 60.0,
        max_retries: int = 2,
        retry_backoff_s: float = 0.5,
        max_concurrent_rpc: int = 10,
        max_concurrent_heavy_ops: int = 1,
        max_concurrent_balances: int = 5
    ) -> None:
        self._rpc_client = SolanaRPCClient(
            base_rpc_url,
            api_key=api_key,
            session=session,
            request_timeout_s=request_timeout_s,
            max_retries=max_retries,
            retry_backoff_s=retry_backoff_s,
            max_concurrent_rpc=max_concurrent_rpc,
        )
        self._owns_rpc_client = True

        self._logger = AppLogger(self.__class__.__name__)
        self._heavy_operation_semaphore = asyncio.Semaphore(max_concurrent_heavy_ops)
        self._balance_semaphore = asyncio.Semaphore(max_concurrent_balances)

        # Módulos especializados
        self._balance_parser = BalanceParser()
        self._transaction_analyzer = TransactionAnalyzer()
        self._detected_errors = DetectedErrors()

        # Atributos para cumplir con SolanaTxAnalyzerProtocol
        # Nota: Estos no se usan en esta implementación, solo en DryRunSolanaTxAnalyzer
        self._open_position_queue: Optional['OpenPositionQueue'] = None
        self._system_wallet_address: Optional[str] = None

    async def __aenter__(self) -> "SolanaTxAnalyzer":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    async def start(self):
        """Inicia la sesión HTTP del cliente RPC."""
        await self._rpc_client.start()

    async def stop(self):
        """Cierra la sesión HTTP del cliente RPC si fue creado por este analyzer."""
        if self._owns_rpc_client:
            await self._rpc_client.stop()

    def set_rpc_client(self, rpc_client: SolanaRPCClient) -> None:
        self._rpc_client = rpc_client
        self._owns_rpc_client = False

    def set_open_position_queue(self, open_position_queue: 'OpenPositionQueue') -> None:
        """
        Establece la cola de posiciones abiertas.
        
        Nota: Este método cumple con SolanaTxAnalyzerProtocol pero no se usa
        en esta implementación. Solo se utiliza en DryRunSolanaTxAnalyzer.
        """
        self._open_position_queue = open_position_queue

    def set_system_wallet_address(self, system_wallet_address: str) -> None:
        """
        Establece la dirección de la wallet del sistema.
        
        Nota: Este método cumple con SolanaTxAnalyzerProtocol pero no se usa
        en esta implementación. Solo se utiliza en DryRunSolanaTxAnalyzer.
        """
        self._system_wallet_address = system_wallet_address
        self._logger.debug(f"System wallet address seteado: {system_wallet_address}")

    async def get_token_balances(
        self,
        owner_pubkey: str,
        *,
        mints: Optional[List[str]] = None,
        commitment: str = "finalized",
        encoding: str = "jsonParsed",
        include_zero_balances: bool = False,
    ) -> BalanceResponse:
        """Obtiene y parsea los balances de tokens de un propietario."""
        async with self._balance_semaphore:
            response = await self._rpc_client.get_token_accounts_by_owner(
                owner_pubkey,
                commitment=commitment,
                encoding=encoding,
            )

        balance_response = self._balance_parser.parse_token_balances(response, owner_pubkey)

        # Filtrar tokens con balance cero si se especifica
        if not include_zero_balances:
            filtered_tokens = [
                token for token in balance_response.tokens
                if Decimal(token.ui_amount_string) > 0
            ]
            balance_response.tokens = filtered_tokens

        if mints:
            filtered_tokens = [
                token for token in balance_response.tokens
                if token.mint in mints
            ]
            balance_response.tokens = filtered_tokens

        self._logger.info(f"Found {balance_response.total_tokens} tokens for owner: {owner_pubkey[:8]}...")
        return balance_response

    async def get_sol_balance(
        self,
        account_pubkey: str,
        *,
        commitment: str = "finalized",
    ) -> str:
        """Obtiene el balance de SOL de una cuenta y lo convierte de lamports a SOL.
        
        Args:
            account_pubkey: La dirección pública de la cuenta
            commitment: Nivel de confirmación ("finalized", "confirmed", "processed")
            
        Returns:
            Balance en SOL como string formateado
        """
        data = await self._rpc_client.get_balance(
            account_pubkey,
            commitment=commitment,
        )
        lamports = data.get("result", {}).get("value", 0)
        return lamports_to_sol_str(lamports)

    async def get_signature_statuses(
        self,
        signatures: List[str],
        *,
        search_transaction_history: bool = True,
    ) -> SignatureStatusesResponse:
        """Obtiene el estado de confirmación de una lista de firmas.
        
        Args:
            signatures: Lista de firmas de transacciones (hasta 256)
            search_transaction_history: Si buscar en el historial completo
            
        Returns:
            Respuesta con el estado de cada firma
        """
        if not signatures:
            return SignatureStatusesResponse.from_dict({"context": {"slot": 0}, "value": []})

        if len(signatures) > 256:
            self._logger.error(f"Too many signatures requested: {len(signatures)} > 256")
            raise ValueError("Máximo 256 firmas permitidas por request")

        data = await self._rpc_client.get_signature_statuses(
            signatures,
            search_transaction_history=search_transaction_history,
        )

        self._logger.debug(f"Signature statuses response: {data}")
        result = SignatureStatusesResponse.from_dict(data.get("result", {"context": {"slot": 0}, "value": []}))
        self._logger.debug(f"Signature statuses fetched successfully for {len(signatures)} signatures")
        return result

    async def get_signatures_with_statuses(
        self,
        signatures: List[str],
        *,
        search_transaction_history: bool = True,
    ) -> SignaturesWithStatuses:
        """
        Obtiene el estado de confirmación y existencia de una lista de firmas de transacciones en Solana.

        Args:
            signatures (List[str]): Lista de firmas de transacciones (máximo 256).
            search_transaction_history (bool, opcional): Si se debe buscar en todo el historial de transacciones. Por defecto es True.

        Returns:
            SignaturesWithStatuses: 
                - data: Diccionario que mapea cada firma a su objeto SignatureStatus (o None si no se encontró).
                - all_success: Booleano que indica si todas las firmas fueron exitosas (True) o si alguna falló (False).
                - all_exists: Booleano que indica si todas las firmas existen (True) o si alguna no se encontró (False).
        """
        all_exists = True
        statuses = await self.get_signature_statuses(signatures, search_transaction_history=search_transaction_history)
        result: Dict[str, Optional[SignatureStatus]] = {}
        for signature, status in zip(signatures, statuses.value):
            if status is not None:
                result[signature] = status
            else:
                result[signature] = None
                all_exists = False
        self._logger.info(f"Signatures with statuses completed: all_success={statuses.all_success}, all_exists={all_exists}")
        return SignaturesWithStatuses(
            data=result,
            all_success=statuses.all_success,
            all_exists=all_exists
        )

    async def analyze_transactions_enhanced(
        self,
        signatures: List[str],
        pair_addresses: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Optional[TransactionAnalysis]]:
        """Analiza múltiples transacciones enhanced."""
        async with self._heavy_operation_semaphore:
            txs = await self._rpc_client.get_enhanced_transaction(signatures)
            results: Dict[str, Optional[TransactionAnalysis]] = {}
            pair_addresses = pair_addresses or {}
            for tx in txs:
                analysis = self._analyze_transaction(tx, pair_address=pair_addresses.get(tx['signature']))
                results[tx['signature']] = analysis
                self._logger.info(f"Transaction {tx['signature']} analyzed successfully")
            return results

    def _analyze_transaction(
        self,
        tx: 'EnhancedTransactionResponse',
        pair_address: Optional[str] = None,
    ) -> Optional[TransactionAnalysis]:
        """Analiza una transacción."""
        error = {"kind": "unknown", "message": "unknown error"}
        if tx['source'] == "PUMP_FUN" and tx['transactionError'] is None:
            analysis = self._transaction_analyzer.analyze_transaction_for_pump_fun(tx, pair_address=pair_address)
            if analysis is not None:
                return TransactionAnalysis(
                    success=True,
                    op_type=analysis['side'],
                    token_ui_delta=analysis['token_amount'],
                    bonding_curve_sol_delta=analysis['pair_native_balance_change'],
                    signer_sol_delta=analysis['signer_native_balance_change'],
                    fee_sol=analysis['fee'],
                    total_cost_sol=analysis['total_cost'],
                    price_sol_per_token=calculate_price_sol_per_token(
                        amount_sol=analysis['pair_native_balance_change'],
                        amount_tokens=analysis['token_amount'],
                    ),
                )
        elif tx['source'] == "PUMP_AMM" and tx['transactionError'] is None:
            if self._transaction_analyzer.is_pump_amm_of_jupiter(tx):
                analysis = self._transaction_analyzer.analyze_transaction_for_pump_amm_by_jupiter(tx, pair_address=pair_address)
            else:
                analysis = self._transaction_analyzer.analyze_transaction_for_pump_amm(tx, pair_address=pair_address)
            if analysis is not None:
                return TransactionAnalysis(
                    success=True,
                    op_type=analysis['side'],
                    token_ui_delta=analysis['token_amount'],
                    bonding_curve_sol_delta=analysis['pair_native_balance_change'],
                    signer_sol_delta=analysis['signer_native_balance_change'],
                    fee_sol=analysis['fee'],
                    total_cost_sol=analysis['total_cost'],
                    price_sol_per_token=calculate_price_sol_per_token(
                        amount_sol=analysis['pair_native_balance_change'],
                        amount_tokens=analysis['token_amount'],
                    ),
                )
        elif tx['transactionError'] is not None:
            err = self._detected_errors.detect_error(tx['transactionError'])
            if err is not None:
                error = err
        else:
            self._logger.warning(f"Transaction {tx['signature']} is not a pump transaction or has an error")
            return None

        fee_sol = lamports_to_sol_str(tx['fee'])

        return TransactionAnalysis(
            success=False,
            error_kind=error.get('kind', 'unknown'), # type: ignore
            error_message=error.get('message', 'unknown error'),
            fee_sol=fee_sol if fee_sol else None,
        )
