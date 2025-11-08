# -*- coding: utf-8 -*-
"""
DryRunTransactionExecutor: ejecutor simulado para modo Dry Run.
Obtiene precios reales vía Moralis API, simula slippage y fees, no ejecuta
on-chain y mantiene la misma interfaz que TransactionExecutor para compatibilidad.
"""
from __future__ import annotations

import uuid
from typing import Dict, Any, Optional, Tuple
from decimal import Decimal

from logging_system import AppLogger
from ..config import CopyTradingConfig
from ..position_management.models import PositionTraderTradeData
from ..events import PositionEventBus, PositionCreatedEvent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data_management import MoralisPriceClient


class DryRunTransactionExecutor:
    """
    Ejecutor simulado para el sistema de copy trading (modo Dry Run) usando Moralis.
    """

    # Mint de WSOL para obtener precio de SOL en USD desde Moralis cuando sea necesario
    SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"

    def __init__(
        self,
        config: CopyTradingConfig,
        moralis_client: "MoralisPriceClient",
        position_event_bus: PositionEventBus
    ):
        self.config = config
        self.moralis_client = moralis_client
        self.position_event_bus = position_event_bus

        self._logger = AppLogger(self.__class__.__name__)
        self._logger.info("[DRY RUN] DryRunTransactionExecutor inicializado (Moralis) - No se ejecutarán trades reales")

        # Parámetros simulados realistas
        self.SIMULATED_PRIORITY_FEE_SOL = Decimal("0.0005")
        self.SIMULATED_BASE_FEE_SOL = Decimal("0.000005")
        self.SIMULATED_SLIPPAGE_PERCENT = Decimal("1.0")

    async def _get_prices_from_moralis(self, token_address: str) -> Optional[Dict[str, str]]:
        """
        Obtiene sol_per_token y usd_per_token usando Moralis API.
        Prioriza native_price; si no está, calcula sol/token = usd_token / usd_sol.
        """
        try:
            token_price = await self.moralis_client.get_token_price(token_address)

            # Precio USD por token (string)
            usd_per_token = token_price.get('usd_price', '0')

            sol_per_token: Optional[str] = None
            native = token_price.get('native_price')
            if native and isinstance(native, dict):
                try:
                    value = Decimal(str(native.get('value', '0')))
                    decimals = int(native.get('decimals', 9))
                    if decimals < 0:
                        decimals = 0
                    divisor = Decimal(10) ** Decimal(decimals)
                    if divisor > 0:
                        sol_per_token = f"{(value / divisor):f}"
                except Exception:
                    sol_per_token = None

            if not sol_per_token:
                # Fallback: obtener USD de SOL desde Moralis usando WSOL mint
                try:
                    sol_price = await self.moralis_client.get_token_price(self.SOL_MINT_ADDRESS)
                    usd_per_sol = Decimal(sol_price.get('usd_price', '0'))
                    usd_per_token_dec = Decimal(usd_per_token)
                    if usd_per_sol > 0:
                        sol_per_token = f"{(usd_per_token_dec / usd_per_sol):f}"
                except Exception:
                    sol_per_token = None

            name = token_price.get('name', '')
            symbol = token_price.get('symbol', '')

            if sol_per_token and Decimal(sol_per_token) > 0:
                return {
                    'name': name,
                    'symbol': symbol,
                    'sol_per_token': sol_per_token,
                    'usd_per_token': usd_per_token
                }

            return None
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error obteniendo precios con Moralis: {e}")
            return None

    async def execute_trade(self, trade_data: PositionTraderTradeData) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Simula la ejecución de un trade. Devuelve (success, signature, error_message).
        """
        try:
            side = trade_data.side
            token = trade_data.token_address

            self._logger.warning(
                f"[DRY RUN] Simulando trade: {side.upper()} {token} por "
                f"{trade_data.copy_amount_sol + ' SOL' if side == 'buy' else trade_data.copy_amount_tokens + ' Tokens'}"
            )

            # 1) Obtener precio de mercado (SOL por token) y USD por token desde Moralis
            token_info = await self._get_prices_from_moralis(token)
            if not token_info:
                error_msg = f"[DRY RUN] No se pudo obtener precio del token {token[:8]}... desde Moralis"
                self._logger.error(error_msg)
                return False, None, error_msg

            market_price_sol_per_token = Decimal(token_info['sol_per_token'])
            price_usd_per_token = token_info['usd_per_token']
            token_symbol = token_info.get('symbol', 'UNK')

            # 2) Calcular precio de ejecución con slippage simulado
            if side == "buy":
                execution_price = market_price_sol_per_token * (Decimal("1") + self.SIMULATED_SLIPPAGE_PERCENT / Decimal("100"))
            else:
                execution_price = market_price_sol_per_token * (Decimal("1") - self.SIMULATED_SLIPPAGE_PERCENT / Decimal("100"))

            # 3) Fees y costos
            total_fee_sol = self.SIMULATED_PRIORITY_FEE_SOL + self.SIMULATED_BASE_FEE_SOL

            if side == "buy":
                amount_sol = Decimal(trade_data.copy_amount_sol)
                #tokens_received = amount_sol / execution_price if execution_price > 0 else Decimal("0")
                total_cost_sol = amount_sol + total_fee_sol
            else:
                """ tokens_sold = Decimal(trade_data.copy_amount_tokens)
                sol_received = tokens_sold * execution_price """
                total_cost_sol = total_fee_sol

            # 4) Signature simulada
            simulated_signature = f"DRY_RUN_{uuid.uuid4().hex[:32]}"

            # 5) Logs informativos
            self._logger.info(
                f"[DRY RUN] Trade simulado exitosamente:\n"
                f"  • Signature: {simulated_signature}\n"
                f"  • Token: {token_symbol}\n"
                f"  • Precio mercado: {market_price_sol_per_token} SOL/token (Moralis)\n"
                f"  • Precio ejecución: {execution_price} SOL/token (slippage {self.SIMULATED_SLIPPAGE_PERCENT}%)\n"
                f"  • Precio USD: ${price_usd_per_token}/token\n"
                f"  • Fee total: {total_fee_sol} SOL\n"
                f"  • Costo total: {total_cost_sol} SOL"
            )

            # 6) Emitir evento PositionCreated con metadata enriquecida
            self.position_event_bus.emit_position_created(
                PositionCreatedEvent(
                    position_id=trade_data.id,
                    token_address=trade_data.token_address,
                    trader_wallet=trade_data.trader_wallet,
                    run_id=self.config.system_run_id,
                    amount_sol=trade_data.copy_amount_sol,
                    amount_tokens=trade_data.copy_amount_tokens,
                    side=trade_data.side,
                    signature=simulated_signature,
                    is_liquidation=trade_data.is_liquidation,
                    timestamp=trade_data.created_at,
                    metadata={
                        "dry_run": True,
                        "price_source": "moralis",
                        "market_price_sol_per_token": f"{market_price_sol_per_token}",
                        "execution_price_sol_per_token": f"{execution_price}",
                        "price_usd_per_token": f"{price_usd_per_token}",
                        "simulated_slippage_percent": f"{self.SIMULATED_SLIPPAGE_PERCENT}",
                        "simulated_fee_sol": f"{total_fee_sol}",
                        "simulated_total_cost_sol": f"{total_cost_sol}",
                        "token_symbol": token_symbol
                    }
                )
            )

            return True, simulated_signature, None

        except Exception as e:
            error_msg = f"[DRY RUN] Error simulando trade: {e}"
            self._logger.error(error_msg, exc_info=True)
            return False, None, error_msg

    def get_transaction_type_info(self) -> Dict[str, Any]:
        return {
            'transaction_type': 'DRY_RUN',
            'mode': 'simulation',
            'price_source': 'moralis',
            'slippage_tolerance_for_buy': self.config.slippage_tolerance_for_buy,
            'slippage_tolerance_for_sell': self.config.slippage_tolerance_for_sell,
            'simulated_priority_fee': f"{self.SIMULATED_PRIORITY_FEE_SOL}",
            'simulated_base_fee': f"{self.SIMULATED_BASE_FEE_SOL}",
            'simulated_slippage': f"{self.SIMULATED_SLIPPAGE_PERCENT}%"
        }
