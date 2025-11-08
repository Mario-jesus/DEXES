# -*- coding: utf-8 -*-
"""
DryRunSolanaTxAnalyzer: Mock de SolanaTxAnalyzer para modo Dry Run.
Simula únicamente los métodos usados por AnalysisPositionQueue y TradeAnalysisProcessor:
- get_signatures_with_statuses(signatures)
- analyze_transaction_by_signature(signature)

Construye TransactionAnalysis a partir de metadata registrada previamente por signature.
"""
from __future__ import annotations

from typing import Dict, Optional, List, Literal
from decimal import Decimal, ROUND_DOWN

from logging_system import AppLogger
from ..models.analyzer_models import (
    TransactionAnalysis,
    SignatureStatus,
    SignaturesWithStatuses,
    TokenBalance,
    BalanceResponse,
)

# Importaciones diferidas para evitar dependencias circulares en tiempo de carga
from ...position_management.services.position_calculation_service import PositionCalculationService
from ...position_management.queues import OpenPositionQueue
from ...config import CopyTradingConfig


class DryRunSolanaTxAnalyzer:
    """
    Mock que genera resultados de análisis de transacción a partir de metadata.
    """

    def __init__(self, *, config: CopyTradingConfig, open_position_queue: Optional[OpenPositionQueue] = None, system_wallet_address: Optional[str] = None):
        self._config = config
        self._logger = AppLogger(self.__class__.__name__)
        self._sig_metadata: Dict[str, Dict[str, str]] = {}
        self._open_position_queue: Optional[OpenPositionQueue] = open_position_queue
        self._system_wallet_address: Optional[str] = system_wallet_address
        self._logger.info("[DRY RUN] DryRunSolanaTxAnalyzer inicializado")

    async def __aenter__(self) -> "DryRunSolanaTxAnalyzer":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def set_open_position_queue(self, open_position_queue: OpenPositionQueue) -> None:
        self._open_position_queue = open_position_queue
        self._logger.debug(f"[DRY RUN] OpenPositionQueue seteado: {open_position_queue}")

    def set_system_wallet_address(self, system_wallet_address: str) -> None:
        self._system_wallet_address = system_wallet_address
        self._logger.debug(f"[DRY RUN] System wallet address seteado: {system_wallet_address}")

    def register_signature_metadata(self, signature: str, metadata: Dict[str, str]) -> None:
        """
        Registra metadata asociada a una signature para análisis posterior.
        """
        self._sig_metadata[signature] = dict(metadata)
        self._logger.debug(f"[DRY RUN] Metadata registrada para signature {signature}")

    async def get_signatures_with_statuses(
        self,
        signatures: List[str],
        *,
        search_transaction_history: bool = True,
    ) -> SignaturesWithStatuses:
        """
        Simula estados de firmas: todas existen y están confirmadas.
        """
        result: Dict[str, Optional[SignatureStatus]] = {}
        for sig in signatures:
            result[sig] = SignatureStatus(
                confirmationStatus="confirmed",
                confirmations=1,
                slot=0,
                success=True,
                type_error=None
            )
        return SignaturesWithStatuses(
            data=result,
            all_success=True,
            all_exists=True
        )

    async def analyze_transaction_by_signature(self, signature: str) -> TransactionAnalysis:
        """
        Construye TransactionAnalysis usando metadata registrada para la signature.
        Espera claves como:
        - position_type: "open" | "close"
        - execution_price_sol_per_token (o market_price_sol_per_token)
        - amount_sol, amount_tokens
        - simulated_fee_sol (o fee_sol)
        """
        meta = self._sig_metadata.get(signature, {})
        if not meta:
            self._logger.warning(f"[DRY RUN] No hay metadata para signature {signature}")
            return TransactionAnalysis(
                success=False,
                op_type=None,
                error_kind="unknown",
                error_message="No metadata available for signature"
            )

        # Extraer datos con fallbacks
        position_type = meta.get("position_type") or meta.get("side") or "open"
        price_str = meta.get("execution_price_sol_per_token") or meta.get("market_price_sol_per_token") or meta.get("execution_price") or "0"
        fee_str = meta.get("simulated_fee_sol") or meta.get("fee_sol") or "0"
        amount_sol_str = meta.get("amount_sol") or "0"
        amount_tokens_str = meta.get("amount_tokens") or "0"

        try:
            price = Decimal(price_str)
        except Exception:
            price = Decimal("0")
        try:
            fee = Decimal(fee_str)
        except Exception:
            fee = Decimal("0")
        try:
            amount_sol = Decimal(amount_sol_str)
        except Exception:
            amount_sol = Decimal("0")
        try:
            amount_tokens = Decimal(amount_tokens_str)
        except Exception:
            amount_tokens = Decimal("0")

        # Cálculos por tipo
        if position_type == "open":
            # BUY
            tokens_received = Decimal("0") if price <= 0 else (amount_sol / price)
            signer_sol_delta = -(amount_sol + fee)
            bonding_curve_sol_delta = amount_sol
            token_ui_delta = tokens_received
            total_cost_sol = amount_sol + fee
            side: Literal["buy", "sell"] = "buy"
        else:
            # SELL
            sol_received = amount_tokens * price
            signer_sol_delta = sol_received - fee
            bonding_curve_sol_delta = -sol_received
            token_ui_delta = -amount_tokens
            total_cost_sol = fee
            side = "sell"

        # Formatear strings
        def fs(x: Decimal, q: str = "0.000000001") -> str:
            try:
                return format(x.quantize(Decimal(q), rounding=ROUND_DOWN).normalize(), "f")
            except Exception:
                return format(x, "f")

        analysis = TransactionAnalysis(
            success=True,
            op_type=side,
            token_ui_delta=fs(token_ui_delta),
            bonding_curve_sol_delta=fs(bonding_curve_sol_delta),
            signer_sol_delta=fs(signer_sol_delta),
            fee_sol=fs(fee),
            total_cost_sol=fs(total_cost_sol),
            price_sol_per_token=fs(price, "0.000000000001")
        )

        return analysis

    async def get_token_balances(
        self,
        owner_pubkey: str,
        *,
        mints: Optional[List[str]] = None,
        commitment: str = "finalized",
        encoding: str = "jsonParsed",
        include_zero_balances: bool = False,
    ) -> BalanceResponse:
        """
        Simula get_token_balances leyendo las posiciones abiertas y sumando tokens restantes por mint.
        """
        try:
            if self._open_position_queue is None:
                self._logger.warning("[DRY RUN] OpenPositionQueue no configurada; retornando lista vacía de balances")
                return BalanceResponse(owner=owner_pubkey, tokens=[])

            # Obtener todas las posiciones abiertas actuales
            positions = self._open_position_queue.get_open_positions()

            # Agregar por mint el total de tokens restantes
            totals_by_mint: Dict[str, Decimal] = {}
            for pos in positions:
                try:
                    mint = pos.token_address
                    if not mint:
                        continue
                    if mints and mint not in mints:
                        continue
                    remaining_tokens_str = PositionCalculationService.calculate_remaining_tokens(pos, exact=True)
                    remaining = Decimal(remaining_tokens_str)
                    if remaining <= 0:
                        continue
                    totals_by_mint[mint] = totals_by_mint.get(mint, Decimal("0")) + remaining
                except Exception as e:
                    self._logger.warning(f"[DRY RUN] Error acumulando remaining para posición {getattr(pos, 'id', '?')}: {e}")
                    continue

            # Convertir a TokenBalance simulados
            tokens: List[TokenBalance] = []
            default_decimals = 9
            ten_pow = Decimal(10) ** default_decimals
            for idx, (mint, total_ui) in enumerate(totals_by_mint.items(), start=1):
                if total_ui <= 0 and not include_zero_balances:
                    continue
                try:
                    amount_int = int((total_ui * ten_pow).to_integral_value(rounding=ROUND_DOWN))
                except Exception:
                    amount_int = 0

                tokens.append(
                    TokenBalance(
                        pubkey=f"DRYRUN_{mint[:8]}_{idx}",
                        mint=mint,
                        amount=amount_int,
                        decimals=default_decimals,
                        ui_amount=float(total_ui) if total_ui > 0 else 0.0,
                        ui_amount_string=format(total_ui, "f"),
                        lamports=0,
                    )
                )

            # Filtrar cero si es necesario (seguridad extra)
            if not include_zero_balances:
                tokens = [t for t in tokens if Decimal(t.ui_amount_string) > 0]

            owner = owner_pubkey or self._system_wallet_address or ""
            return BalanceResponse(owner=owner, tokens=tokens)
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error simulando get_token_balances: {e}", exc_info=True)
            return BalanceResponse(owner=owner_pubkey, tokens=[])

    async def get_sol_balance(self, account_pubkey: str) -> str:
        """
        Simula el balance de SOL basado en el presupuesto global configurado
        (general_available_balance_to_invest) menos el monto comprometido en
        posiciones de apertura (total_cost_sol restante por posición).

        Args:
            account_pubkey: Wallet (no se usa para DRY RUN, solo por compatibilidad)

        Returns:
            Balance disponible simulado en SOL como string decimal.
        """
        try:
            self._logger.info(f"[DRY RUN] Getting SOL balance for {account_pubkey[:8]}...")
            # Presupuesto base desde configuración
            try:
                base_budget = Decimal(self._config.general_available_balance_to_invest or "0.0")
            except Exception:
                base_budget = Decimal("0.0")

            # Si no hay cola de posiciones abiertas, retornar presupuesto completo
            if self._open_position_queue is None:
                return format(base_budget, "f")

            # Sumar costo total restante (incluye fee) de todas las posiciones abiertas
            committed = Decimal("0")
            positions = self._open_position_queue.get_open_positions()
            for pos in positions:
                try:
                    _, _, remaining_total_cost_sol = PositionCalculationService.calculate_remaining_amounts(pos, exact=True)
                    committed += Decimal(remaining_total_cost_sol or "0")
                except Exception:
                    # Si falla el cálculo para una posición, ignorarla en la suma
                    continue

            available = base_budget - committed
            if available < 0:
                available = Decimal("0")
            return format(available, "f")
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error simulando get_sol_balance: {e}", exc_info=True)
            return "0"
