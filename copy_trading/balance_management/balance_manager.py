# -*- coding: utf-8 -*-
"""
BalanceManager asíncrono para Copy Trading.

Responsabilidades:
- Mantener en memoria balances de SOL y tokens con mínima latencia.
- Sincronizar bajo demanda con la red (SolanaAccountInfo).
- Exponer lecturas de balance consistentes para Validations y flujo de posiciones.
- Reaccionar a aperturas/cierres y análisis para ajustar balances locales.
- Respetar configuraciones: general_available_balance_to_invest, max_amount_to_invest_per_trader,
    y AmountMode.DISTRIBUTED (para cálculo de disponibilidad por trader/token si aplica).

Política de coherencia:
- Si existen análisis pendientes sobre una posición relacionada, privilegia lectura real (on-chain) para evitar inconsistencias.
- Si no hay análisis pendientes, utiliza balances locales ajustados por operaciones en curso.

Notas de integración:
- El módulo es independiente, pero está pensado para ser inyectado en ValidationEngine y PositionQueueManager.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from decimal import Decimal, getcontext

from logging_system import AppLogger
from copy_trading.data_management import SolanaTxAnalyzer

from ..config import CopyTradingConfig, AmountMode

getcontext().prec = 26


@dataclass
class TraderBalances:
    """Contenedor de balances por trader."""
    sol: str = "0.0"
    # mint_address -> balance (string decimal)
    tokens: Dict[str, str] = field(default_factory=dict)


class BalanceManager:
    """
    Gestor de balances asíncrono, cacheado y consistente con eventos del sistema.
    """

    def __init__(self, config: CopyTradingConfig, solana_analyzer: SolanaTxAnalyzer):
        self.config = config
        self._logger = AppLogger(self.__class__.__name__)

        # Cliente on-chain (inicializado asíncronamente)
        self._solana_analyzer: SolanaTxAnalyzer = solana_analyzer

        # Estado en memoria
        # Nota: clave del diccionario es el wallet del sistema (el follower), no los traders seguidos
        self._system_wallet: Optional[str] = None
        self._balances_by_trader: Dict[str, TraderBalances] = {}

        # Track de posiciones en análisis por token para decidir fuente de verdad
        # token_address -> número de análisis pendientes
        self._pending_analysis_by_token: Dict[str, int] = {}

        # Locks
        self._lock = asyncio.Lock()

    async def start(self, system_wallet_address: str) -> None:
        """
        Inicializa recursos y hace una sincronización completa.
        """
        async with self._lock:
            self._system_wallet = system_wallet_address
            if system_wallet_address not in self._balances_by_trader:
                self._balances_by_trader[system_wallet_address] = TraderBalances()

        await self.refresh_all_balances(force_onchain=True)

    async def stop(self) -> None:
        """Detiene recursos y cierra cliente on-chain."""
        # No hay tareas de fondo que detener
        pass

    # ==================== API PÚBLICA: LECTURAS ====================

    async def get_sol_balance(self, only_in_memory: bool = False) -> str:
        """Retorna el balance SOL del wallet del sistema."""
        async with self._lock:
            wallet = self._require_system_wallet()
            # Si hay análisis pendientes de cualquier token, preferimos on-chain para SOL también
            if not only_in_memory and self._has_pending_analysis_any():
                return await self._get_onchain_sol_balance(wallet)
            return self._balances_by_trader.get(wallet, TraderBalances()).sol

    async def get_token_balance(self, mint_addresses: List[str], only_in_memory: bool = False) -> Dict[str, str]:
        """Retorna el balance de un token del wallet del sistema."""
        async with self._lock:
            wallet = self._require_system_wallet()
            if not only_in_memory and self._has_pending_analysis(mint_addresses):
                return await self._get_onchain_token_balance(wallet, mint_addresses)
            tb = self._balances_by_trader.get(wallet, TraderBalances())
            return {mint_address: tb.tokens.get(mint_address, "0.0") for mint_address in mint_addresses}

    async def get_effective_available_sol_for_trade(self, trade_amount_sol: str) -> Tuple[str, bool]:
        """
        Calcula SOL disponible efectivo para abrir nuevas posiciones, considerando configuraciones.
        Retorna (available_sol_string, is_enough: bool).
        """
        current_sol = Decimal(await self.get_sol_balance())

        # Aplicar límites de presupuesto global
        global_budget = Decimal(self.config.general_available_balance_to_invest or "0")
        effective_budget = min(current_sol, global_budget) if global_budget > 0 else current_sol

        # Si AmountMode es DISTRIBUTED, estimar asignación media por token/posición según config
        # No bloqueamos si params no están completos: solo devolvemos effective_budget
        if self.config.amount_mode == AmountMode.DISTRIBUTED:
            # Global distributed
            if (
                self.config.max_amount_to_invest_per_trader is not None and
                self.config.max_open_tokens_per_trader is not None and
                self.config.max_open_positions_per_token_per_trader is not None and
                self.config.use_balanced_allocation_per_trader
            ):
                max_amount = Decimal(self.config.max_amount_to_invest_per_trader)
                max_tokens = int(self.config.max_open_tokens_per_trader)
                max_positions = int(self.config.max_open_positions_per_token_per_trader)
                per_position = (max_amount / Decimal(max_tokens)) / Decimal(max_positions)
                # El disponible efectivo no puede ser más que el presupuesto por posición
                effective_budget = min(effective_budget, per_position)

        is_enough = Decimal(trade_amount_sol) <= effective_budget
        return (format(effective_budget, "f"), is_enough)

    # ==================== API PÚBLICA: MUTACIONES POR EVENTO ====================

    async def on_position_opened(self, signer_sol_delta: str) -> None:
        """Ajusta balance local de SOL y marca dependencias por apertura de posición."""
        async with self._lock:
            wallet = self._require_system_wallet()
            tb = self._balances_by_trader.setdefault(wallet, TraderBalances())
            try:
                tb.sol = format(Decimal(tb.sol) + Decimal(signer_sol_delta), "f")
            except Exception:
                # Si algo falla, forzar refresh on-chain en siguiente ciclo
                pass

    async def on_position_closed(self, signer_sol_delta: str) -> None:
        """Ajusta balance local de SOL al cierre de posición (ingreso de SOL)."""
        async with self._lock:
            wallet = self._require_system_wallet()
            tb = self._balances_by_trader.setdefault(wallet, TraderBalances())
            try:
                tb.sol = format(Decimal(tb.sol) + Decimal(signer_sol_delta), "f")
            except Exception:
                pass

    async def on_token_received(self, mint_address: str, token_ui_delta: str) -> None:
        async with self._lock:
            wallet = self._require_system_wallet()
            tb = self._balances_by_trader.setdefault(wallet, TraderBalances())
            current = Decimal(tb.tokens.get(mint_address, "0.0"))
            tb.tokens[mint_address] = format(current + Decimal(token_ui_delta), "f")

    async def on_token_spent(self, mint_address: str, token_ui_delta: str) -> None:
        async with self._lock:
            wallet = self._require_system_wallet()
            tb = self._balances_by_trader.setdefault(wallet, TraderBalances())
            current = Decimal(tb.tokens.get(mint_address, "0.0"))
            tb.tokens[mint_address] = format(max(Decimal("0"), current + Decimal(token_ui_delta)), "f")

    async def on_analysis_enqueued(self, token_address: str) -> None:
        async with self._lock:
            self._pending_analysis_by_token[token_address] = self._pending_analysis_by_token.get(token_address, 0) + 1

    async def on_analysis_finished(self, token_address: str) -> None:
        async with self._lock:
            current = self._pending_analysis_by_token.get(token_address, 0)
            self._pending_analysis_by_token[token_address] = max(0, current - 1)

    # ==================== SYNC / REFRESH ====================

    async def refresh_all_balances(self, force_onchain: bool = False) -> None:
        """Refresca balances de SOL y subset de tokens cuando aplica."""
        async with self._lock:
            wallet = self._require_system_wallet()
        try:
            onchain_sol = await self._get_onchain_sol_balance(wallet)
            async with self._lock:
                tb = self._balances_by_trader.setdefault(wallet, TraderBalances())
                tb.sol = onchain_sol
        except Exception as e:
            self._logger.error(f"Error refrescando balance SOL: {e}")

        if force_onchain or self._has_pending_analysis_any():
            try:
                onchain_tokens = await self._get_onchain_token_balance(wallet)
                async with self._lock:
                    tb = self._balances_by_trader.setdefault(wallet, TraderBalances())
                    tb.tokens = onchain_tokens
            except Exception as e:
                self._logger.error(f"Error refrescando balance de tokens: {e}")

    # ==================== HELPERS ====================

    def _require_system_wallet(self) -> str:
        if not self._system_wallet:
            raise ValueError("BalanceManager no inicializado con system wallet")
        return self._system_wallet

    def _has_pending_analysis(self, token_addresses: List[str]) -> bool:
        return any(self._pending_analysis_by_token.get(token_address, 0) > 0 for token_address in token_addresses)

    def _has_pending_analysis_any(self) -> bool:
        return any(count > 0 for count in self._pending_analysis_by_token.values())

    async def _get_onchain_sol_balance(self, wallet_address: str) -> str:
        bal = await self._solana_analyzer.get_sol_balance(wallet_address)
        return format(Decimal(bal), "f")

    async def _get_onchain_token_balance(self, wallet_address: str, mint_addresses: Optional[List[str]] = None) -> Dict[str, str]:
        balance_response = await self._solana_analyzer.get_token_balances(wallet_address, mints=mint_addresses)
        if balance_response["total_tokens"] == 0:
            return {}
        return {token["mint"]: token["ui_amount_string"] for token in balance_response["tokens"]}
