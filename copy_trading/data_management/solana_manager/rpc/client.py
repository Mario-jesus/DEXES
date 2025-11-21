# -*- coding: utf-8 -*-
"""
Cliente RPC base para comunicación con la API de Solana.
"""
import asyncio, aiohttp, os
from typing import Any, Dict, Optional, List, TYPE_CHECKING
from dotenv import load_dotenv

from logging_system import AppLogger
from ...models import SolanaRPCError

if TYPE_CHECKING:
    from .models.enhanced_transactions import EnhancedTransactionResponse

load_dotenv()

RPC_API_KEY = os.getenv("RPC_API_KEY")


class SolanaRPCClient:
    """Cliente base para realizar llamadas RPC a Solana."""

    TOKEN_PROGRAM: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

    def __init__(
        self,
        base_rpc_url: str = "https://mainnet.helius-rpc.com",
        *,
        api_key: Optional[str] = RPC_API_KEY,
        session: Optional[aiohttp.ClientSession] = None,
        request_timeout_s: float = 60.0,
        max_retries: int = 2,
        retry_backoff_s: float = 0.5,
        max_concurrent_rpc: int = 10,
    ) -> None:
        self._base_rpc_url = base_rpc_url
        self._api_key = api_key
        self._external_session = session
        self._session: Optional[aiohttp.ClientSession] = session
        self._request_timeout_s = request_timeout_s
        self._max_retries = max_retries
        self._retry_backoff_s = retry_backoff_s
        self._logger = AppLogger(self.__class__.__name__)
        self._rpc_semaphore = asyncio.Semaphore(max_concurrent_rpc)

    async def __aenter__(self) -> "SolanaRPCClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    async def start(self):
        """Inicia la sesión HTTP si no existe."""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._request_timeout_s)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._logger.debug(f"Created new HTTP session with timeout: {self._request_timeout_s}s")

    async def stop(self):
        """Cierra la sesión HTTP si fue creada internamente."""
        if self._external_session is None and self._session is not None:
            await self._session.close()
            self._session = None
            self._logger.debug("HTTP session closed")

    def _get_full_rpc_url(self, endpoint: Optional[str] = None, use_api_in_url: bool = False) -> str:
        """Obtiene la URL completa para el RPC, incluyendo la API key de Helius.

        Si endpoint se pasa, se agrega al path; se normalizan los slashes.
        """
        if self._api_key is None:
            raise ValueError("api_key is not set")

        rpc_url = self._base_rpc_url.rstrip("/")
        if use_api_in_url:
            rpc = rpc_url.split("//")
            rpc_url = "//api-".join(rpc)

        if endpoint:
            endpoint = endpoint.strip("/")
            rpc_url = f"{rpc_url}/{endpoint}"

        return f"{rpc_url}/?api-key={self._api_key}"

    async def _rpc_call(self, method: str, params: List[Any], operation_name: str = "RPC call") -> Dict[str, Any]:
        """Realiza una llamada RPC genérica con manejo de errores y reintentos."""
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return await self._make_request(
            payload=payload,
            operation_name=operation_name
        )

    async def _make_request(
        self,
        payload: Dict[str, Any],
        *,
        use_api_in_url: bool = False,
        headers: Optional[Dict[str, str]] = None,
        endpoint: Optional[str] = None,
        operation_name: str = "RPC call",
    ) -> Any:
        """Realiza una llamada RPC genérica con manejo de errores y reintentos.
        
        Args:
            method: Nombre del método RPC
            params: Parámetros del método RPC
            operation_name: Nombre descriptivo de la operación para logging
            
        Returns:
            Respuesta JSON de la API
            
        Raises:
            SolanaRPCError: Si hay un error en la respuesta RPC
            aiohttp.ClientError: Si hay un error de conexión
        """
        headers = headers or {"Content-Type": "application/json"}
        last_error: Optional[BaseException] = None
        for attempt in range(self._max_retries + 1):
            try:
                if self._session is None:
                    timeout = aiohttp.ClientTimeout(total=self._request_timeout_s)
                    async with aiohttp.ClientSession(timeout=timeout) as temp_session:
                        async with temp_session.post(
                            self._get_full_rpc_url(endpoint, use_api_in_url),
                            json=payload,
                            headers=headers,
                        ) as response:
                            response.raise_for_status()
                            data = await response.json(content_type=None)
                else:
                    async with self._session.post(
                        self._get_full_rpc_url(endpoint, use_api_in_url),
                        json=payload,
                        headers=headers,
                    ) as response:
                        response.raise_for_status()
                        data = await response.json(content_type=None)

                if "error" in data and data["error"]:
                    err = data["error"]
                    self._logger.error(
                        f"RPC error in {operation_name}: {err.get('message', 'Unknown error')}"
                    )
                    raise SolanaRPCError(
                        err.get("message", "Solana RPC error"),
                        code=err.get("code"),
                        data=err.get("data"),
                    )

                return data

            except aiohttp.ClientResponseError as exc:
                last_error = exc
                if exc.status == 429:  # Too Many Requests
                    base_sleep = 15
                    max_sleep = 120
                    sleep_time = min(max_sleep, base_sleep + (attempt * 30))
                    self._logger.warning(
                        f"Rate limit hit (429) for {operation_name}, "
                        f"sleeping {sleep_time}s before retry {attempt + 1}"
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(sleep_time)
                    else:
                        self._logger.error(
                            f"{operation_name} RPC failed after {self._max_retries + 1} "
                            f"attempts due to rate limiting: {exc}"
                        )
                        raise
                else:
                    self._logger.warning(f"{operation_name} RPC attempt {attempt + 1} failed: {exc}")
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                    else:
                        self._logger.error(
                            f"{operation_name} RPC failed after {self._max_retries + 1} attempts: {exc}"
                        )
                        raise
            except (aiohttp.ClientError, asyncio.TimeoutError, SolanaRPCError) as exc:
                last_error = exc
                self._logger.warning(f"{operation_name} RPC attempt {attempt + 1} failed: {exc}")
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                else:
                    self._logger.error(
                        f"{operation_name} RPC failed after {self._max_retries + 1} attempts: {exc}"
                    )
                    raise

        if last_error:
            self._logger.error(f"{operation_name} RPC failed with final error: {last_error}")
            raise last_error
        raise RuntimeError(f"Unknown error performing {operation_name}")

    async def get_transaction(
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
            return await self._rpc_call(
                "getTransaction",
                params,
                operation_name=f"transaction {signature[:8]}..."
            )

    async def get_enhanced_transaction(self, signatures: List[str]) -> List['EnhancedTransactionResponse']:
        """
        Obtiene una lista de transacciones enhanced por signature usando getEnhancedTransactions.

        Args:
            signatures: Lista de firmas de transacciones (máximo 100)

        Returns:
            Lista de transacciones enhanced

        Raises:
            ValueError: Si el número de firmas es mayor a 100
            SolanaRPCError: Si hay un error en la respuesta RPC
            aiohttp.ClientError: Si hay un error de conexión
            asyncio.TimeoutError: Si hay un timeout
        """
        self._logger.debug(f"Fetching enhanced transactions for {len(signatures)} signatures...")
        ENDPOINT = "v0/transactions"

        if len(signatures) > 100:
            self._logger.error(f"Too many signatures requested: {len(signatures)} > 100")
            raise ValueError("Maximum 100 signatures allowed per request")

        async with self._rpc_semaphore:
            return await self._make_request(
                payload={
                    "transactions": signatures,
                },
                endpoint=ENDPOINT,
                use_api_in_url=True,
                operation_name=f"enhanced transactions ({len(signatures)} signatures)"
            )

    async def get_token_accounts_by_owner(
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
                    "programId": self.TOKEN_PROGRAM
                },
                {
                    "commitment": commitment,
                    "encoding": encoding,
                },
            ]
            return await self._rpc_call(
                "getTokenAccountsByOwner",
                params,
                operation_name=f"token accounts {owner_pubkey[:8]}..."
            )

    async def get_balance(
        self,
        account_pubkey: str,
        *,
        commitment: str = "finalized",
    ) -> Dict[str, Any]:
        """Obtiene el balance de SOL de una cuenta en lamports.
        
        Args:
            account_pubkey: La dirección pública de la cuenta
            commitment: Nivel de confirmación ("finalized", "confirmed", "processed")
            
        Returns:
            Respuesta JSON con el balance en lamports
            
        Raises:
            SolanaRPCError: Si hay un error en la respuesta RPC
            aiohttp.ClientError: Si hay un error de conexión
        """
        self._logger.debug(f"Fetching balance for account: {account_pubkey[:8]}...")
        async with self._rpc_semaphore:
            params = [
                account_pubkey,
                {
                    "commitment": commitment,
                },
            ]
            return await self._rpc_call(
                "getBalance",
                params,
                operation_name=f"SOL balance {account_pubkey[:8]}..."
            )

    async def get_signature_statuses(
        self,
        signatures: List[str],
        *,
        search_transaction_history: bool = True,
    ) -> Dict[str, Any]:
        """Obtiene el estado de confirmación de una lista de firmas.
        
        Args:
            signatures: Lista de firmas de transacciones (máximo 256)
            search_transaction_history: Si buscar en el historial completo
            
        Returns:
            Respuesta JSON con el estado de cada firma
            
        Raises:
            ValueError: Si el número de firmas es mayor a 256
            SolanaRPCError: Si hay un error en la respuesta RPC
            aiohttp.ClientError: Si hay un error de conexión
        """
        self._logger.debug(f"Fetching signature statuses for {len(signatures)} signatures...")

        if len(signatures) > 256:
            raise ValueError("Máximo 256 firmas permitidas por request")

        async with self._rpc_semaphore:
            config = {
                "searchTransactionHistory": search_transaction_history
            }
            params = [signatures, config]
            return await self._rpc_call(
                "getSignatureStatuses",
                params,
                operation_name=f"signature statuses ({len(signatures)} signatures)"
            )
