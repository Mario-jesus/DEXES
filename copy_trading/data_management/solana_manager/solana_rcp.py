# -*- coding: utf-8 -*-
"""
Solana client for analyzing transactions.
"""
import asyncio
from typing import Any, Dict, List, Optional, Set
from decimal import Decimal, getcontext, ROUND_DOWN
import aiohttp
import re

from logging_system import AppLogger
from ..models import (
    TransactionAnalysis,
    TokenBalance,
    BalanceResponse,
    SolanaRPCError,
    SignatureStatus,
    SignatureStatusesResponse,
    SignaturesWithStatuses
)

getcontext().prec = 26

# Constantes de Solana
PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPFUN_AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
JITOTIP_6 = "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
WSOL_MINT = "So11111111111111111111111111111111111111112"
SYSTEM_PROGRAM = "11111111111111111111111111111111"
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
ASSOCIATED_TOKEN_ACCOUNT_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"


class SolanaTxAnalyzer:
    """Analizador de transacciones de Solana usando aiohttp."""

    def __init__(
        self,
        endpoint: str = "https://api.mainnet-beta.solana.com",
        *,
        session: Optional[aiohttp.ClientSession] = None,
        request_timeout_s: float = 60.0,
        max_retries: int = 2,
        retry_backoff_s: float = 0.5,
        max_concurrent_rpc: int = 10,
        max_concurrent_heavy_ops: int = 1,
        max_concurrent_balances: int = 5,
    ) -> None:
        self.endpoint = endpoint
        self._external_session = session
        self._session: Optional[aiohttp.ClientSession] = session
        self._request_timeout_s = request_timeout_s
        self._max_retries = max_retries
        self._retry_backoff_s = retry_backoff_s

        self._logger = AppLogger(self.__class__.__name__)

        # Semáforos para control de concurrencia
        self._rpc_semaphore = asyncio.Semaphore(max_concurrent_rpc)
        self._heavy_operation_semaphore = asyncio.Semaphore(max_concurrent_heavy_ops)
        self._balance_semaphore = asyncio.Semaphore(max_concurrent_balances)

    async def __aenter__(self) -> "SolanaTxAnalyzer":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    # ================ METODOS PÚBLICOS ================

    async def start(self):
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._request_timeout_s)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._logger.debug(f"Created new HTTP session with timeout: {self._request_timeout_s}s")

    async def stop(self):
        if self._external_session is None and self._session is not None:
            await self._session.close()
            self._session = None
            self._logger.debug("HTTP session closed")

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
            response = await self._get_token_accounts_by_owner(
                owner_pubkey,
                commitment=commitment,
                encoding=encoding,
            )

        balance_response = self._parse_token_balances(response)
        balance_response["owner"] = owner_pubkey

        # Filtrar tokens con balance cero si se especifica
        if not include_zero_balances:
            filtered_tokens = [
                token for token in balance_response["tokens"]
                if float(token["ui_amount"]) > 0
            ]
            balance_response["tokens"] = filtered_tokens
            balance_response["total_tokens"] = len(filtered_tokens)

        if mints:
            filtered_tokens = [
                token for token in balance_response["tokens"]
                if token["mint"] in mints
            ]
            balance_response["tokens"] = filtered_tokens
            balance_response["total_tokens"] = len(filtered_tokens)

        self._logger.info(f"Found {balance_response['total_tokens']} tokens for owner: {owner_pubkey[:8]}...")
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
        async with self._rpc_semaphore:
            params = [
                account_pubkey,
                {
                    "commitment": commitment,
                },
            ]

            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": params}

            last_error: Optional[BaseException] = None
            for attempt in range(self._max_retries + 1):
                try:
                    if self._session is None:
                        timeout = aiohttp.ClientTimeout(total=self._request_timeout_s)
                        async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                            async with temp_session.post(
                                self.endpoint,
                                json=payload,
                                headers={"Content-Type": "application/json"},
                            ) as response:
                                response.raise_for_status()
                                data = await response.json(content_type=None)
                    else:
                        async with self._session.post(
                            self.endpoint,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                        ) as response:
                            response.raise_for_status()
                            data = await response.json(content_type=None)

                    if "error" in data and data["error"]:
                        err = data["error"]
                        raise SolanaRPCError(
                            err.get("message", "Solana RPC error"),
                            code=err.get("code"),
                            data=err.get("data"),
                        )

                    # Extraer el balance en lamports
                    lamports = data.get("result", {}).get("value", 0)
                    sol_balance = self._lamports_to_sol_str(lamports)
                    return sol_balance

                except aiohttp.ClientResponseError as exc:
                    last_error = exc
                    if exc.status == 429:  # Too Many Requests
                        # Sleep agresivo para rate limiting: 10s a 2min
                        base_sleep = 15  # 10 segundos base
                        max_sleep = 120   # 2 minutos máximo
                        sleep_time = min(max_sleep, base_sleep + (attempt * 30))  # Incrementa 30s por intento
                        self._logger.warning(f"Rate limit hit (429) for SOL balance, sleeping {sleep_time}s before retry {attempt + 1}")
                        if attempt < self._max_retries:
                            await asyncio.sleep(sleep_time)
                        else:
                            self._logger.error(f"SOL balance RPC failed after {self._max_retries + 1} attempts due to rate limiting: {exc}")
                            raise
                    else:
                        self._logger.warning(f"SOL balance RPC attempt {attempt + 1} failed: {exc}")
                        if attempt < self._max_retries:
                            await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                        else:
                            self._logger.error(f"SOL balance RPC failed after {self._max_retries + 1} attempts: {exc}")
                            raise
                except (aiohttp.ClientError, asyncio.TimeoutError, SolanaRPCError) as exc:
                    last_error = exc
                    self._logger.warning(f"SOL balance RPC attempt {attempt + 1} failed: {exc}")
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                    else:
                        self._logger.error(f"SOL balance RPC failed after {self._max_retries + 1} attempts: {exc}")
                        raise

            if last_error:
                self._logger.error(f"SOL balance RPC failed with final error: {last_error}")
                raise last_error
            raise RuntimeError("Unknown error performing RPC request")

    async def analyze_transaction_by_signature(
        self,
        signature: str,
        *,
        commitment: str = "finalized",
        max_supported_transaction_version: int = 0,
        encoding: str = "jsonParsed",
    ) -> TransactionAnalysis:
        """Obtiene transacción y la analiza."""
        async with self._heavy_operation_semaphore:
            tx = await self._get_transaction(
                signature,
                commitment=commitment,
                max_supported_transaction_version=max_supported_transaction_version,
                encoding=encoding,
            )
            analysis = self._analyze_transaction(tx)
            self._logger.info(f"Transaction {signature[:8]}... analysis: success={analysis.success}, op_type={analysis.op_type}")
            return analysis

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
        async with self._rpc_semaphore:
            if not signatures:
                return SignatureStatusesResponse.from_dict({"context": {"slot": 0}, "value": []})

            if len(signatures) > 256:
                self._logger.error(f"Too many signatures requested: {len(signatures)} > 256")
                raise ValueError("Máximo 256 firmas permitidas por request")

            config = {
                "searchTransactionHistory": search_transaction_history
            }

            params = [signatures, config]

            payload = {
                "jsonrpc": "2.0", 
                "id": 1, 
                "method": "getSignatureStatuses", 
                "params": params
            }

            last_error: Optional[BaseException] = None
            for attempt in range(self._max_retries + 1):
                try:
                    if self._session is None:
                        timeout = aiohttp.ClientTimeout(total=self._request_timeout_s)
                        async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                            async with temp_session.post(
                                self.endpoint,
                                json=payload,
                                headers={"Content-Type": "application/json"},
                            ) as response:
                                response.raise_for_status()
                                data = await response.json(content_type=None)
                    else:
                        async with self._session.post(
                            self.endpoint,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                        ) as response:
                            response.raise_for_status()
                            data = await response.json(content_type=None)

                    if "error" in data and data["error"]:
                        err = data["error"]
                        raise SolanaRPCError(
                            err.get("message", "Solana RPC error"),
                            code=err.get("code"),
                            data=err.get("data"),
                        )

                    self._logger.debug(f"Signature statuses response: {data}")
                    result = SignatureStatusesResponse.from_dict(data.get("result", {"context": {"slot": 0}, "value": []}))
                    self._logger.debug(f"Signature statuses fetched successfully for {len(signatures)} signatures")
                    return result

                except aiohttp.ClientResponseError as exc:
                    last_error = exc
                    if exc.status == 429:  # Too Many Requests
                        # Sleep agresivo para rate limiting: 10s a 2min
                        base_sleep = 15  # 10 segundos base
                        max_sleep = 120   # 2 minutos máximo
                        sleep_time = min(max_sleep, base_sleep + (attempt * 30))  # Incrementa 30s por intento
                        self._logger.warning(f"Rate limit hit (429) for signature statuses, sleeping {sleep_time}s before retry {attempt + 1}")
                        if attempt < self._max_retries:
                            await asyncio.sleep(sleep_time)
                        else:
                            self._logger.error(f"Signature statuses RPC failed after {self._max_retries + 1} attempts due to rate limiting: {exc}")
                            raise
                    else:
                        self._logger.warning(f"Signature statuses RPC attempt {attempt + 1} failed: {exc}")
                        if attempt < self._max_retries:
                            await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                        else:
                            self._logger.error(f"Signature statuses RPC failed after {self._max_retries + 1} attempts: {exc}")
                            raise
                except (aiohttp.ClientError, asyncio.TimeoutError, SolanaRPCError) as exc:
                    last_error = exc
                    self._logger.warning(f"Signature statuses RPC attempt {attempt + 1} failed: {exc}")
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                    else:
                        self._logger.error(f"Signature statuses RPC failed after {self._max_retries + 1} attempts: {exc}")
                        raise

            if last_error:
                self._logger.error(f"Signature statuses RPC failed with final error: {last_error}")
                raise last_error
            raise RuntimeError("Unknown error performing RPC request")

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

    # ================ METODOS PRIVADOS ================

    async def _get_token_accounts_by_owner(
        self,
        owner_pubkey: str,
        *,
        commitment: str = "finalized",
        encoding: str = "jsonParsed",
    ) -> Dict[str, Any]:
        """Obtiene todas las cuentas de tokens de un propietario."""
        self._logger.debug(f"Fetching token accounts for owner: {owner_pubkey[:8]}...")
        async with self._rpc_semaphore:
            params = [
                owner_pubkey,
                {
                    "programId": TOKEN_PROGRAM
                },
                {
                    "commitment": commitment,
                    "encoding": encoding,
                },
            ]

            payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner", "params": params}

            last_error: Optional[BaseException] = None
            for attempt in range(self._max_retries + 1):
                try:
                    if self._session is None:
                        timeout = aiohttp.ClientTimeout(total=self._request_timeout_s)
                        async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                            async with temp_session.post(
                                self.endpoint,
                                json=payload,
                                headers={"Content-Type": "application/json"},
                            ) as response:
                                response.raise_for_status()
                                data = await response.json(content_type=None)
                    else:
                        async with self._session.post(
                            self.endpoint,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                        ) as response:
                            response.raise_for_status()
                            data = await response.json(content_type=None)

                    if "error" in data and data["error"]:
                        err = data["error"]
                        self._logger.error(f"RPC error fetching token accounts for {owner_pubkey[:8]}...: {err.get("message", "Unknown error")}")
                        raise SolanaRPCError(
                            err.get("message", "Solana RPC error"),
                            code=err.get("code"),
                            data=err.get("data"),
                        )
                    self._logger.debug(f"Token accounts fetched successfully for {owner_pubkey[:8]}...")
                    return data
                except aiohttp.ClientResponseError as exc:
                    last_error = exc
                    if exc.status == 429:  # Too Many Requests
                        # Sleep agresivo para rate limiting: 10s a 2min
                        base_sleep = 15  # 10 segundos base
                        max_sleep = 120   # 2 minutos máximo
                        sleep_time = min(max_sleep, base_sleep + (attempt * 30))  # Incrementa 30s por intento
                        self._logger.warning(f"Rate limit hit (429) for token accounts {owner_pubkey[:8]}..., sleeping {sleep_time}s before retry {attempt + 1}")
                        if attempt < self._max_retries:
                            await asyncio.sleep(sleep_time)
                        else:
                            self._logger.error(f"Token accounts RPC failed after {self._max_retries + 1} attempts due to rate limiting for {owner_pubkey[:8]}...: {exc}")
                            raise
                    else:
                        self._logger.warning(f"Token accounts RPC attempt {attempt + 1} failed for {owner_pubkey[:8]}...: {exc}")
                        if attempt < self._max_retries:
                            await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                        else:
                            self._logger.error(f"Token accounts RPC failed after {self._max_retries + 1} attempts for {owner_pubkey[:8]}...: {exc}")
                            raise
                except (aiohttp.ClientError, asyncio.TimeoutError, SolanaRPCError) as exc:
                    last_error = exc
                    self._logger.warning(f"Token accounts RPC attempt {attempt + 1} failed for {owner_pubkey[:8]}...: {exc}")
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                    else:
                        self._logger.error(f"Token accounts RPC failed after {self._max_retries + 1} attempts for {owner_pubkey[:8]}...: {exc}")
                        raise

            if last_error:
                self._logger.error(f"Token accounts RPC failed with final error for {owner_pubkey[:8]}...: {last_error}")
                raise last_error
            self._logger.error(f"Unknown error performing RPC request for token accounts {owner_pubkey[:8]}...")
            raise RuntimeError("Unknown error performing RPC request")

    def _parse_token_balances(self, response: Dict[str, Any]) -> BalanceResponse:
        """Parsea la respuesta de getTokenAccountsByOwner y extrae balances."""
        try:
            result = response.get("result", {})
            value = result.get("value", [])

            tokens: List[TokenBalance] = []

            for account_info in value:
                try:
                    account = account_info.get("account", {})
                    pubkey = account_info.get("pubkey", "")

                    parsed_data = account.get("data", {}).get("parsed", {})
                    token_info = parsed_data.get("info", {})

                    mint = token_info.get("mint", "")
                    token_amount = token_info.get("tokenAmount", {})

                    # Extraer información del token
                    amount = int(token_amount.get("amount", "0"))
                    decimals = token_amount.get("decimals", 0)
                    ui_amount = token_amount.get("uiAmount", 0.0) or 0.0
                    ui_amount_string = token_amount.get("uiAmountString", "0")
                    lamports = account.get("lamports", 0)

                    # Solo incluir tokens que tengan balance o información válida
                    if mint and pubkey:
                        token_balance: TokenBalance = {
                            "pubkey": pubkey,
                            "mint": mint,
                            "amount": amount,
                            "decimals": decimals,
                            "ui_amount": ui_amount,
                            "ui_amount_string": ui_amount_string,
                            "lamports": lamports,
                        }
                        tokens.append(token_balance)

                except Exception as e:
                    self._logger.warning(f"Error parsing token account info: {e}")
                    # Continuar con el siguiente token si hay error parseando uno
                    continue

            # Asumimos que el owner es el primer parámetro de la consulta original
            owner = ""

            return {
                "owner": owner,
                "tokens": tokens,
                "total_tokens": len(tokens),
            }

        except Exception as e:
            self._logger.error(f"Error parsing token balances response: {e}")
            return {
                "owner": "",
                "tokens": [],
                "total_tokens": 0,
            }

    async def _get_transaction(
        self,
        signature: str,
        *,
        commitment: str = "finalized",
        max_supported_transaction_version: int = 0,
        encoding: str = "jsonParsed",
    ) -> Dict[str, Any]:
        """Obtiene una transacción por signature usando getTransaction."""
        self._logger.debug(f"Fetching transaction: {signature[:8]}...")
        async with self._rpc_semaphore:
            params = [
                signature,
                {
                    "commitment": commitment,
                    "maxSupportedTransactionVersion": max_supported_transaction_version,
                    "encoding": encoding,
                },
            ]

            payload = {"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": params}

            last_error: Optional[BaseException] = None
            for attempt in range(self._max_retries + 1):
                try:
                    if self._session is None:
                        timeout = aiohttp.ClientTimeout(total=self._request_timeout_s)
                        async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                            async with temp_session.post(
                                self.endpoint,
                                json=payload,
                                headers={"Content-Type": "application/json"},
                            ) as response:
                                response.raise_for_status()
                                data = await response.json(content_type=None)
                    else:
                        async with self._session.post(
                            self.endpoint,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                        ) as response:
                            response.raise_for_status()
                            data = await response.json(content_type=None)

                    if "error" in data and data["error"]:
                        err = data["error"]
                        self._logger.error(f"RPC error fetching transaction {signature[:8]}...: {err.get("message", "Unknown error")}")
                        raise SolanaRPCError(
                            err.get("message", "Solana RPC error"),
                            code=err.get("code"),
                            data=err.get("data"),
                        )
                    self._logger.debug(f"Transaction fetched successfully: {signature[:8]}...")
                    return data
                except aiohttp.ClientResponseError as exc:
                    last_error = exc
                    if exc.status == 429:  # Too Many Requests
                        # Sleep agresivo para rate limiting: 10s a 2min
                        base_sleep = 15  # 10 segundos base
                        max_sleep = 120   # 2 minutos máximo
                        sleep_time = min(max_sleep, base_sleep + (attempt * 30))  # Incrementa 30s por intento
                        self._logger.info(f"Rate limit hit (429) for {signature[:8]}..., sleeping {sleep_time}s before retry {attempt + 1}")
                        if attempt < self._max_retries:
                            await asyncio.sleep(sleep_time)
                        else:
                            self._logger.error(f"Transaction RPC failed after {self._max_retries + 1} attempts due to rate limiting: {exc}")
                            raise
                    else:
                        self._logger.info(f"Transaction RPC attempt {attempt + 1} failed for {signature[:8]}...: {exc}")
                        if attempt < self._max_retries:
                            await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                        else:
                            self._logger.error(f"Transaction RPC failed after {self._max_retries + 1} attempts for {signature[:8]}...: {exc}")
                            raise
                except (aiohttp.ClientError, asyncio.TimeoutError, SolanaRPCError) as exc:
                    last_error = exc
                    self._logger.info(f"Transaction RPC attempt {attempt + 1} failed for {signature[:8]}...: {exc}")
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                    else:
                        self._logger.error(f"Transaction RPC failed after {self._max_retries + 1} attempts for {signature[:8]}...: {exc}")
                        raise

            if last_error:
                self._logger.error(f"Transaction RPC failed with final error for {signature[:8]}...: {last_error}")
                raise last_error
            self._logger.error(f"Unknown error performing RPC request for transaction {signature[:8]}...")
            raise RuntimeError("Unknown error performing RPC request")

    def _analyze_transaction(
        self,
        tx: Optional[Dict[str, Any]]
    ) -> TransactionAnalysis:
        """Analiza una transacción y retorna resumen completo."""
        if tx is None:
            self._logger.warning("Transaction is None - cannot analyze")
            return TransactionAnalysis(
                success=False,
                error_kind="transaction_not_found",
                error_message="Transaction not found or could not be retrieved",
            )

        if not isinstance(tx, dict) or "result" not in tx:
            self._logger.warning("Invalid transaction format - missing 'result' field")
            return TransactionAnalysis(
                success=False,
                error_kind="invalid_transaction_format",
                error_message="Invalid transaction format",
            )

        result = tx.get("result")
        if result is None:
            self._logger.warning("Transaction result is null")
            return TransactionAnalysis(
                success=False,
                error_kind="transaction_not_found",
                error_message="Transaction result is null",
            )

        # Detectar operación y errores
        logs = self._extract_logs(tx)
        op_type = self._detect_operation_type(logs)

        meta = result.get("meta", {})
        success = meta.get("err") in (None, {})

        if not success:
            error = self._detect_error(logs, meta.get("err"))
            error_kind = error.get("kind", "unknown") if error else "unknown"
            self._logger.warning(f"Transaction failed with error kind: {error_kind}")
            return TransactionAnalysis(
                success=False,
                op_type=op_type,
                error_kind=error_kind,
                error_message=error.get("message") if error else None,
            )

        # Calcular métricas para transacciones exitosas
        signers = self._extract_signers(tx)
        # Detectar dinámicamente contrapartes (bonding curve o pools) desde innerInstructions
        detected_counterparties = self._detect_counterparty_pubkeys(tx, signers)
        # Usar contrapartes detectadas dinámicamente, combinadas con cualquier bonding_curve_pubkeys proporcionado
        counterparty_pubkeys = detected_counterparties

        # Excluir contrapartes y firmantes de los costos para no contaminar el costo del usuario
        exclude_for_cost = signers | counterparty_pubkeys

        token_ui_delta = self._calculate_token_delta(tx, signers)
        bonding_curve_sol_delta = self._lamports_to_sol_str(self._calculate_lamports_deltas(tx, counterparty_pubkeys))
        signer_sol_delta = self._lamports_to_sol_str(self._calculate_lamports_deltas(tx, signers))
        fee_sol = self._lamports_to_sol_str(int(meta.get("fee", 0)))
        total_cost_sol = self._lamports_to_sol_str(self._calculate_total_cost(tx, exclude_for_cost))

        # Calcular precio SOL por token
        price_sol_per_token = self._calculate_price_sol_per_token(
            op_type or "", token_ui_delta, bonding_curve_sol_delta
        )

        self._logger.debug(f"Transaction analysis completed: op_type={op_type}, token_delta={token_ui_delta}, price={price_sol_per_token}")

        return TransactionAnalysis(
            success=True,
            op_type=op_type,
            token_ui_delta=token_ui_delta,
            bonding_curve_sol_delta=bonding_curve_sol_delta,
            signer_sol_delta=signer_sol_delta,
            fee_sol=fee_sol,
            total_cost_sol=total_cost_sol,
            price_sol_per_token=price_sol_per_token,
        )

    @staticmethod
    def _lamports_to_sol_str(lamports: int) -> str:
        sol = (Decimal(lamports) / Decimal(1_000_000_000)).quantize(Decimal("0.000000001"), rounding=ROUND_DOWN)
        return format(sol, "f")

    def _calculate_price_sol_per_token(self, op_type: str, token_ui_delta: str, bonding_curve_sol_delta: str) -> Optional[str]:
        """
        Calcula el precio de SOL por token basado en los deltas.
        
        Para sell: precio = SOL recibido de bonding curve / tokens vendidos
        Para buy: precio = SOL enviado a bonding curve / tokens recibidos
        
        Retorna el precio como string o None si no se puede calcular.
        """
        if not op_type or not token_ui_delta or not bonding_curve_sol_delta:
            return None

        try:
            token_delta = Decimal(token_ui_delta)
            bonding_curve_sol = Decimal(bonding_curve_sol_delta)

            if token_delta == 0 or bonding_curve_sol == 0:
                return None

            if op_type == "sell":
                # Sell: tokens negativos (vendidos), bonding curve SOL negativo (sale SOL de la curve)
                tokens_sold = abs(token_delta)
                sol_received = abs(bonding_curve_sol)
                if tokens_sold > 0 and sol_received > 0:
                    price = sol_received / tokens_sold
                else:
                    return None
            elif op_type == "buy":
                # Buy: tokens positivos (recibidos), bonding curve SOL positivo (entra SOL a la curve)
                tokens_received = token_delta
                sol_spent = bonding_curve_sol
                if tokens_received > 0 and sol_spent > 0:
                    price = sol_spent / tokens_received
                else:
                    return None
            else:
                return None

            # Formatear con precisión adecuada
            price_formatted = price.quantize(Decimal("0.000000000001"), rounding=ROUND_DOWN)
            return format(price_formatted, "f")

        except Exception as e:
            self._logger.warning(f"Could not calculate price SOL per token: {e}")
            return None

    def _extract_signers(self, tx: Dict[str, Any]) -> Set[str]:
        try:
            account_keys = tx["result"]["transaction"]["message"]["accountKeys"]
            return {item["pubkey"] for item in account_keys if item.get("signer") and isinstance(item.get("pubkey"), str)}
        except Exception as e:
            self._logger.warning(f"Error extracting signers from transaction: {e}")
            return set()

    def _extract_logs(self, tx: Dict[str, Any]) -> List[str]:
        try:
            logs = tx["result"]["meta"].get("logMessages") or []
            return [str(line) for line in logs]
        except Exception as e:
            self._logger.warning(f"Error extracting log messages from transaction: {e}")
            return []

    def _detect_counterparty_pubkeys(self, tx: Dict[str, Any], signers: Set[str]) -> Set[str]:
        """
        Detecta la contraparte principal de la operación:
        - Si el token es no graduado: intenta extraer la bonding curve.
        - Si el token es graduado (presencia de PUMPFUN_AMM): intenta extraer la dirección AMM del par token/SOL.

        Para cada caso aplica 3 opciones y devuelve la dirección con mayor coincidencia.
        Si no hay consenso o no se puede extraer, cae a la heurística previa basada en transfer del System Program.
        """
        # Helpers de acceso seguro
        def _safe_list(value):
            return value if isinstance(value, list) else []

        def _safe_dict(value):
            return value if isinstance(value, dict) else {}

        try:
            result = _safe_dict(tx.get("result"))
            message = _safe_dict(_safe_dict(result.get("transaction")).get("message"))
            meta = _safe_dict(result.get("meta"))

            account_keys_entries = _safe_list(message.get("accountKeys"))
            account_keys: List[str] = []
            for entry in account_keys_entries:
                if isinstance(entry, dict) and isinstance(entry.get("pubkey"), str):
                    account_keys.append(entry["pubkey"])

            msg_instructions = _safe_list(message.get("instructions"))
            inner_blocks = _safe_list(meta.get("innerInstructions"))

            # Detección de token graduado por presencia de PUMPFUN_AMM en accountKeys o en cualquier accounts de instrucciones
            def _has_constant_anywhere(target: str) -> bool:
                if target in account_keys:
                    return True
                for ix in msg_instructions:
                    accs = _safe_list(_safe_dict(ix).get("accounts"))
                    if target in accs:
                        return True
                return False

            is_graduated = _has_constant_anywhere(PUMPFUN_AMM)

            # ============ Bonding curve options (no graduado) ============
            def _bc_opt1_inner_accounts3() -> Optional[str]:
                best_accs = None
                best_len = -1
                for block in inner_blocks:
                    instructions = _safe_list(_safe_dict(block).get("instructions"))
                    for ix in instructions:
                        if not isinstance(ix, dict):
                            continue
                        accs = _safe_list(ix.get("accounts"))
                        if len(accs) >= 4:
                            # Preferir el que pertenezca/contenga PUMPFUN
                            pid = ix.get("programId")
                            has_pump = (pid == PUMPFUN) or (PUMPFUN in accs)
                            score = len(accs)
                            if score > best_len or (score == best_len and has_pump and best_accs is not None and (PUMPFUN not in best_accs)):
                                best_accs = accs
                                best_len = score
                if best_accs and len(best_accs) >= 4:
                    return best_accs[3]
                return None

            def _bc_opt2_account_keys_4_or_5() -> Optional[str]:
                idx = 4
                try:
                    # Si JITOTIP_6 aparece entre los primeros 5, usar la 5ta posición
                    first5 = set(k for k in account_keys[:5] if isinstance(k, str))
                    if JITOTIP_6 in first5:
                        idx = 5
                except Exception:
                    pass
                if len(account_keys) > idx:
                    return account_keys[idx]
                return None

            def _bc_opt3_msg_accounts3() -> Optional[str]:
                best_accs = None
                best_len = -1
                for ix in msg_instructions:
                    if not isinstance(ix, dict):
                        continue
                    accs = _safe_list(ix.get("accounts"))
                    if len(accs) >= 4:
                        has_pump = (PUMPFUN in accs)
                        score = len(accs)
                        if score > best_len or (score == best_len and has_pump and best_accs is not None and (PUMPFUN not in best_accs)):
                            best_accs = accs
                            best_len = score
                if best_accs and len(best_accs) >= 4:
                    return best_accs[3]
                return None

            # ============ AMM options (graduado) ============
            def _amm_opt1_inner_transfer_checked_destination() -> Optional[str]:
                candidates: List[tuple] = []  # (mint, destination)
                for block in inner_blocks:
                    instructions = _safe_list(_safe_dict(block).get("instructions"))
                    for ix in instructions:
                        parsed = _safe_dict(_safe_dict(ix).get("parsed"))
                        if not parsed:
                            continue
                        if str(parsed.get("type")) != "transferChecked":
                            continue
                        info = _safe_dict(parsed.get("info"))
                        authority = info.get("authority")
                        destination = info.get("destination")
                        mint = info.get("mint")
                        if isinstance(authority, str) and authority in signers and isinstance(destination, str):
                            if destination == PUMPFUN_AMM:
                                continue
                            candidates.append((mint, destination))
                if not candidates:
                    return None
                # Preferir el destino cuando el mint es wSOL
                for mint, dest in candidates:
                    if mint == WSOL_MINT:
                        return dest
                return candidates[0][1]

            def _amm_opt2_account_keys4() -> Optional[str]:
                if len(account_keys) > 4:
                    cand = account_keys[4]
                    if cand != PUMPFUN_AMM:
                        return cand
                return None

            def _amm_opt3_msg_accounts8() -> Optional[str]:
                best_accs = None
                best_len = -1
                for ix in msg_instructions:
                    if not isinstance(ix, dict):
                        continue
                    accs = _safe_list(ix.get("accounts"))
                    if len(accs) >= 9:
                        pid = ix.get("programId")
                        has_amm = (pid == PUMPFUN_AMM) or (PUMPFUN_AMM in accs)
                        score = len(accs)
                        if score > best_len or (score == best_len and has_amm and best_accs is not None and (PUMPFUN_AMM not in best_accs)):
                            best_accs = accs
                            best_len = score
                if best_accs and len(best_accs) >= 9:
                    cand = best_accs[8]
                    if cand != PUMPFUN_AMM:
                        return cand
                return None

            # Ejecutar opciones según el estado de graduación
            if is_graduated:
                options = [
                    _amm_opt1_inner_transfer_checked_destination(),
                    _amm_opt2_account_keys4(),
                    _amm_opt3_msg_accounts8(),
                ]
                opt_labels = [
                    "amm_opt1_inner_transferChecked_destination",
                    "amm_opt2_accountKeys[4]",
                    "amm_opt3_msg_accounts[8]",
                ]
            else:
                options = [
                    _bc_opt1_inner_accounts3(),
                    _bc_opt2_account_keys_4_or_5(),
                    _bc_opt3_msg_accounts3(),
                ]
                opt_labels = [
                    "bc_opt1_inner_accounts[3]",
                    "bc_opt2_accountKeys[4/5]",
                    "bc_opt3_msg_accounts[3]",
                ]

            # Consolidar por mayoría y desempatar por prioridad (opt1 > opt2 > opt3)
            forbidden = {
                PUMPFUN,
                PUMPFUN_AMM,
                JITOTIP_6,
                ASSOCIATED_TOKEN_ACCOUNT_PROGRAM,
                TOKEN_PROGRAM,
                SYSTEM_PROGRAM,
                COMPUTE_BUDGET,
            }
            freq: Dict[str, int] = {}
            first_idx: Dict[str, int] = {}
            for i, addr in enumerate(options):
                if isinstance(addr, str) and addr and addr not in forbidden:
                    freq[addr] = freq.get(addr, 0) + 1
                    if addr not in first_idx:
                        first_idx[addr] = i

            if freq:
                selected = sorted(freq.items(), key=lambda kv: (-kv[1], first_idx[kv[0]]))[0][0]
                self._logger.debug(
                    f"Counterparty detection ({'amm' if is_graduated else 'bonding'}) options={{" + ", ".join(f"{l}:{o}" for l, o in zip(opt_labels, options)) + f"}} -> selected={selected}"
                )
                return {selected}
            else:
                self._logger.debug(
                    f"No majority candidate for {'amm' if is_graduated else 'bonding'} found via options; falling back to system-transfer heuristic."
                )
        except Exception as e:
            self._logger.warning(f"Error detecting counterparty (bonding/amm): {e}")
            return set()

        return set()

    def _detect_operation_type(self, logs: List[str]) -> str:
        pattern = re.compile(r"\bInstruction:\s*(Buy|Sell)\b", re.IGNORECASE)
        for line in logs:
            match = pattern.search(line)
            if match:
                op = match.group(1).lower()
                if op in {"buy", "sell"}:
                    self._logger.debug(f"Detected operation type: {op}")
                    return op
        self._logger.debug("No operation type detected.")
        return ""

    def _detect_error(self, logs: List[str], meta_err: Any = None) -> Optional[Dict[str, Any]]:
        if not logs and meta_err is None:
            self._logger.debug("No logs or meta_err provided for error detection.")
            return None

        error_info: Dict[str, Any] = {"kind": None, "message": None}

        # Meta error
        if meta_err is not None:
            try:
                self._logger.debug(f"Attempting to parse meta_err: {meta_err}")
                if isinstance(meta_err, dict) and "InstructionError" in meta_err:
                    err_val = meta_err.get("InstructionError")
                    if isinstance(err_val, list) and len(err_val) >= 2:
                        detail = err_val[1]
                        if isinstance(detail, dict) and "Custom" in detail:
                            error_info["kind"] = "custom"
                            self._logger.debug("Meta error categorized as custom instruction error.")
                        else:
                            error_info["kind"] = "instruction"
                            error_info["message"] = str(detail)
                            self._logger.debug(f"Meta error categorized as instruction error: {detail}")
                else:
                    error_info["kind"] = "generic"
                    error_info["message"] = str(meta_err)
                    self._logger.debug(f"Meta error categorized as generic: {meta_err}")
            except Exception as e:
                self._logger.warning(f"Error processing meta_err: {e}")
                pass

        # Log patterns
        re_anchor = re.compile(r"AnchorError.*?Error Code:\s*([\w]+).*?Error Message:\s*(.*)", re.IGNORECASE)
        re_insuff = re.compile(r"Transfer:\s*insufficient lamports\s*(\d+),\s*need\s*(\d+)", re.IGNORECASE)

        for line in logs:
            # AnchorError
            m = re_anchor.search(line)
            if m:
                error_code = m.group(1).strip()
                error_message = m.group(2).strip()
                self._logger.debug(f"Detected AnchorError: Code={error_code}, Message={error_message}")

                # Categorizar errores específicos de Anchor
                if "TooMuchSolRequired" in error_code or "slippage" in error_message.lower():
                    error_info["kind"] = "slippage"
                    self._logger.debug("Categorized as slippage error.")
                elif "NotEnoughTokensToSell" in error_code or "not enough tokens" in error_message.lower():
                    error_info["kind"] = "insufficient_tokens"
                    self._logger.debug("Categorized as insufficient tokens error.")
                else:
                    error_info["kind"] = "unknown"
                    self._logger.debug("Categorized as unknown Anchor error.")

                error_info["message"] = error_message
                continue

            # Insufficient lamports
            m = re_insuff.search(line)
            if m:
                try:
                    have = int(m.group(1))
                    need = int(m.group(2))
                    error_info["kind"] = "insufficient_lamports"
                    error_info["message"] = f"insufficient lamports: have {have}, need {need}"
                    self._logger.debug(f"Detected insufficient lamports: have {have}, need {need}")
                except Exception as e:
                    self._logger.warning(f"Error parsing insufficient lamports details: {e}")
                    pass
                continue

        if error_info["kind"] is None and meta_err is not None:
            self._logger.warning(f"Could not categorize meta error: {meta_err}")

        return error_info if error_info["kind"] else None

    @staticmethod
    def _calculate_token_delta(tx: Dict[str, Any], signers: Set[str]) -> str:
        """Calcula delta de tokens del signer."""
        meta = tx.get("result", {}).get("meta", {})
        pre = meta.get("preTokenBalances") or []
        post = meta.get("postTokenBalances") or []

        # Map por (accountIndex, mint)
        pre_map = {}
        post_map = {}

        for item in pre:
            try:
                key = (int(item["accountIndex"]), str(item["mint"]))
                pre_map[key] = item
            except Exception:
                continue

        for item in post:
            try:
                key = (int(item["accountIndex"]), str(item["mint"]))
                post_map[key] = item
            except Exception:
                continue

        total_delta = Decimal("0")
        all_keys = set(pre_map.keys()) | set(post_map.keys())

        for key in all_keys:
            pre_item = pre_map.get(key)
            post_item = post_map.get(key)

            # Verificar si el owner es signer
            owner = None
            if post_item and post_item.get("owner"):
                owner = str(post_item["owner"])
            elif pre_item and pre_item.get("owner"):
                owner = str(pre_item["owner"])

            if owner not in signers:
                continue

            # Extraer amounts UI
            pre_ui = "0.0"
            post_ui = "0.0"

            if pre_item:
                ui = pre_item.get("uiTokenAmount") or {}
                pre_ui = str(ui.get("uiAmountString", ui.get("uiAmount", 0.0)))

            if post_item:
                ui = post_item.get("uiTokenAmount") or {}
                post_ui = str(ui.get("uiAmountString", ui.get("uiAmount", 0.0)))

            try:
                delta = Decimal(post_ui) - Decimal(pre_ui)
                total_delta += delta
            except Exception:
                continue

        return format(total_delta.quantize(Decimal("0.000001"), rounding=ROUND_DOWN), "f")

    def _calculate_lamports_deltas(self, tx: Dict[str, Any], target_pubkeys: Set[str]) -> int:
        """Calcula delta de lamports para cuentas específicas."""
        try:
            account_keys = tx["result"]["transaction"]["message"]["accountKeys"]
            meta = tx.get("result", {}).get("meta", {})
            pre_balances = meta.get("preBalances") or []
            post_balances = meta.get("postBalances") or []

            total_delta = 0
            for index, key_info in enumerate(account_keys):
                pubkey = key_info.get("pubkey")
                if pubkey in target_pubkeys:
                    pre = int(pre_balances[index]) if index < len(pre_balances) else 0
                    post = int(post_balances[index]) if index < len(post_balances) else 0
                    total_delta += post - pre

            return total_delta
        except Exception as e:
            self._logger.warning(f"Error calculating lamports deltas: {e}")
            return 0

    def _calculate_total_cost(self, tx: Dict[str, Any], exclude_pubkeys: Set[str]) -> int:
        """Calcula costo total excluyendo cuentas específicas."""
        try:
            account_keys = tx["result"]["transaction"]["message"]["accountKeys"]
            meta = tx.get("result", {}).get("meta", {})
            pre_balances = meta.get("preBalances") or []
            post_balances = meta.get("postBalances") or []
            fee = int(meta.get("fee", 0))

            running_delta = 0
            for index, key_info in enumerate(account_keys):
                pubkey = key_info.get("pubkey")
                if pubkey not in exclude_pubkeys:
                    pre = int(pre_balances[index]) if index < len(pre_balances) else 0
                    post = int(post_balances[index]) if index < len(post_balances) else 0
                    running_delta += post - pre

            return fee + running_delta
        except Exception as e:
            self._logger.warning(f"Error calculating total cost: {e}")
            return 0


# ================ FUNCIONES AUXILIARES ================

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
            return await analyzer._get_transaction(
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
