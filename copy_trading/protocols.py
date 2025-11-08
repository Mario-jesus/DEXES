# -*- coding: utf-8 -*-
"""
Protocolos para el sistema de Copy Trading.
Contiene las interfaces que evitan dependencias circulares.
"""
from __future__ import annotations

from typing import Protocol, Optional, Callable, Awaitable, Literal, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .data_management.models import SignatureNotification, TransactionAnalysis, SignaturesWithStatuses, BalanceResponse
    from .position_management.queues import OpenPositionQueue


class SolanaWebsocketProtocol(Protocol):
    """
    Interfaz para SolanaWebsocketManager y DryRunSolanaWebsocketManager.
    """

    async def __aenter__(self) -> "SolanaWebsocketProtocol":
        ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        ...

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    def set_callbacks(self,
                        on_signature_confirmed: Optional[Callable[[str, "SignatureNotification"], Awaitable[None]]] = None,
                        on_signature_timeout: Optional[Callable[[str, int], Awaitable[None]]] = None,
                        on_connection_error: Optional[Callable[[Exception], Awaitable[None]]] = None) -> None:
        ...

    async def subscribe_signature(self,
                                    signature: str,
                                    *,
                                    commitment: Literal["finalized", "confirmed", "processed"] = "finalized",
                                    enable_received_notification: bool = False,
                                    timeout: int = 60) -> bool:
        ...

    async def unsubscribe_signature(self, signature: str) -> bool:
        ...

    def get_subscribed_count(self) -> int:
        ...

    @property
    def is_connected(self) -> bool:
        ...


class SolanaTxAnalyzerProtocol(Protocol):
    """
    Interfaz para SolanaTxAnalyzer y DryRunSolanaTxAnalyzer.
    """

    async def __aenter__(self) -> "SolanaTxAnalyzerProtocol":
        ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        ...

    def set_open_position_queue(self, open_position_queue: "OpenPositionQueue") -> None:
        ...

    def set_system_wallet_address(self, system_wallet_address: str) -> None:
        ...

    async def analyze_transaction_by_signature(self, signature: str) -> "TransactionAnalysis":
        """
        Analiza una transacción por su signature.

        Args:
            signature: La signature de la transacción a analizar

        Returns:
            TransactionAnalysis con los resultados del análisis
        """
        ...

    async def get_signatures_with_statuses(
        self,
        signatures: List[str],
        *,
        search_transaction_history: bool = True,
    ) -> "SignaturesWithStatuses":
        """
        Obtiene el estado de múltiples signatures.

        Args:
            signatures: Lista de signatures a consultar
            search_transaction_history: Si buscar en el historial de transacciones

        Returns:
            SignaturesWithStatuses con el estado de cada signature
        """
        ...

    async def get_token_balances(
        self,
        owner_pubkey: str,
        *,
        mints: Optional[List[str]] = None,
        commitment: str = "finalized",
        encoding: str = "jsonParsed",
        include_zero_balances: bool = False,
    ) -> "BalanceResponse":
        """
        Obtiene balances de tokens para un propietario dado.

        Args:
            owner_pubkey: Wallet del propietario (follower/system wallet)
            mints: Lista opcional de mints a filtrar
            commitment: Nivel de confirmación simulado
            encoding: Tipo de encoding (compatibilidad)
            include_zero_balances: Incluir balances en cero

        Returns:
            BalanceResponse con los balances por mint
        """
        ...

    async def get_sol_balance(self, account_pubkey: str) -> str:
        """
        Obtiene el balance de SOL de una cuenta.

        Args:
            account_pubkey: Wallet del propietario (follower/system wallet)

        Returns:
            Balance en SOL como string formateado
        """
        ...
