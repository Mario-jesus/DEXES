# -*- coding: utf-8 -*-
"""
DryRunAnalysisProcessor: procesador de análisis simulado para modo Dry Run.
Delegado: DryRunSolanaTxAnalyzer extrae datos desde metadata por signature.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple
from decimal import Decimal

from logging_system import AppLogger
from copy_trading.protocols import SolanaTxAnalyzerProtocol
from ...data_management.models import TransactionAnalysis
from ...events import PositionEventBus, PositionAnalysisEvent
from ..models import Position, OpenPosition, ClosePosition


class DryRunAnalysisProcessor:
    """
    Procesador de análisis simulado para Dry Run que delega en DryRunSolanaTxAnalyzer.
    """

    def __init__(
        self,
        position_event_bus: Optional[PositionEventBus] = None,
        analyzer: Optional[SolanaTxAnalyzerProtocol] = None
    ):
        self._logger = AppLogger(self.__class__.__name__)
        self._lock = asyncio.Lock()
        self.position_event_bus = position_event_bus
        self.analyzer = analyzer
        self._logger.info("[DRY RUN] DryRunAnalysisProcessor inicializado - delegado en DryRunSolanaTxAnalyzer")

    def set_analyzer(self, analyzer: SolanaTxAnalyzerProtocol) -> None:
        self.analyzer = analyzer

    async def analyze_position(self, position: Position) -> Tuple[bool, Optional[TransactionAnalysis]]:
        if not position:
            self._logger.debug("No hay posición para analizar")
            return False, None

        try:
            self._logger.debug(f"[DRY RUN] Iniciando análisis simulado para posición {position.id}")

            async with self._lock:
                # Determinar signature (puede venir en execution_signature)
                signature = position.execution_signature
                if not signature:
                    self._logger.warning(f"[DRY RUN] Posición {position.id} sin execution_signature")
                    return False, None

                # Registrar metadata útil para el analizador (precio, montos, fees, side)
                try:
                    meta_to_register = {
                        "position_type": "open" if isinstance(position, OpenPosition) else "close",
                        "execution_price_sol_per_token": position.execution_price or position.get_metadata("execution_price_sol_per_token") or "0",
                        "amount_sol": position.amount_sol or "0",
                        "amount_tokens": position.amount_tokens or "0",
                        "fee_sol": position.fee_sol or position.get_metadata("simulated_fee_sol") or "0",
                    }
                    # Merge con metadata existente de la posición si hay claves relevantes en metadata
                    for key in ("market_price_sol_per_token", "simulated_total_cost_sol"):
                        val = position.get_metadata(key)
                        if val is not None:
                            meta_to_register[key] = val

                    self.analyzer.register_signature_metadata(signature, meta_to_register)  # type: ignore[arg-type]
                except Exception:
                    pass

                # Delegar análisis a DryRunSolanaTxAnalyzer
                if self.analyzer is None:
                    self._logger.warning(f"[DRY RUN] Analyzer no seteado para posición {position.id}")
                    return False, None
                analysis_result = await self.analyzer.analyze_transaction_by_signature(signature)

                if analysis_result and analysis_result.success:
                    # Aplicar análisis a la posición
                    await self._apply_analysis_to_position(position, analysis_result)

                    # Emitir evento de análisis
                    await self._emit_analysis_event(position, analysis_result)
                    self._logger.info(f"[DRY RUN] Análisis simulado completado para posición {position.id}")
                    return True, analysis_result
                else:
                    self._logger.warning(f"[DRY RUN] Análisis simulado no exitoso para {position.id}")
                    return False, analysis_result

        except Exception as e:
            self._logger.error(f"[DRY RUN] Error en análisis simulado: {e}", exc_info=True)
            return False, None

    async def _apply_analysis_to_position(self, position: Position, analysis_result: TransactionAnalysis) -> None:
        try:
            self._logger.debug(f"Aplicando análisis a posición {position.id}")
            if analysis_result.success:
                position.amount_tokens_executed = format(abs(Decimal(analysis_result.token_ui_delta or "0.0")), "f")
                position.amount_sol_executed = format(abs(Decimal(analysis_result.bonding_curve_sol_delta or "0.0")), "f")
                position.fee_sol = analysis_result.fee_sol or "0.0"
                position.total_cost_sol = analysis_result.total_cost_sol or "0.0"
                position.execution_price = analysis_result.price_sol_per_token or "0.0"
                self._logger.debug(f"Posición actualizada: amount_tokens_executed={position.amount_tokens_executed}, amount_sol_executed={position.amount_sol_executed}, fee_sol={position.fee_sol}, total_cost_sol={position.total_cost_sol}, execution_price={position.execution_price}, price_sol_per_token={analysis_result.price_sol_per_token}")
        except Exception as e:
            self._logger.error(f"Error aplicando análisis a posición {position.id}: {e}")

    async def _emit_analysis_event(self, position: Position, analysis: TransactionAnalysis) -> None:
        try:
            if not self.position_event_bus:
                return
            if isinstance(position, OpenPosition):
                position_type = "open"
            elif isinstance(position, ClosePosition):
                position_type = "close"
            else:
                position_type = "open"

            self.position_event_bus.emit_position_analysis(PositionAnalysisEvent(
                position_id=position.id,
                token_address=position.token_address,
                trader_wallet=position.trader_wallet,
                success=analysis.success,
                position_type=position_type,
                mint_address=position.token_address,
                signer_sol_delta=analysis.signer_sol_delta,
                token_ui_delta=analysis.token_ui_delta,
                fee_sol=analysis.fee_sol,
                total_cost_sol=analysis.total_cost_sol,
            ))
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error emitiendo PositionAnalysisEvent: {e}")
