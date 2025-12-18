# -*- coding: utf-8 -*-
"""
Lector de datos desde la base de datos usando ORM.
Lee capital inicial y PnL desde las tablas correspondientes.
"""
import uuid
from typing import List, Optional, Dict, Any
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logging_system import AppLogger
from ..persistence.session import get_session
from ..persistence.orm.models import (
    Run,
    PNLRealizedTrader,
)


class TradingDataReader:
    """Lee datos de trading desde la base de datos usando ORM."""

    def __init__(self):
        self._logger = AppLogger(self.__class__.__name__)

    async def _get_session(self) -> AsyncSession:
        """Obtiene una sesión de base de datos."""
        return await get_session()

    async def get_initial_capital(self, runs_id: uuid.UUID) -> Optional[Decimal]:
        """
        Obtiene el capital inicial de un run.

        Args:
            runs_id: ID del run

        Returns:
            Capital inicial en SOL o None si no existe
        """
        async with (await self._get_session()) as session:
            run = await session.get(Run, runs_id)
            if not run:
                self._logger.warning(f"Run {runs_id} no encontrado")
                return None

            return run.initial_capital_sol

    async def get_pnl_realized_traders(
        self,
        runs_id: uuid.UUID,
    ) -> List[Dict[str, Any]]:
        """
        Obtiene PnL acumulado por trader desde PNLRealizedTrader.

        Los datos en PNLRealizedTrader ya están acumulados por trader,
        por lo que este método retorna un snapshot de los valores actuales.

        Args:
            runs_id: ID del run

        Returns:
            Lista de diccionarios con: trader_wallet, pnl_with_cost_sol
        """
        async with (await self._get_session()) as session:
            query = (
                select(
                    PNLRealizedTrader.traders_id.label("trader_wallet"),
                    PNLRealizedTrader.pnl_with_cost_sol,
                )
                .where(PNLRealizedTrader.runs_id == runs_id)
            )

            result = await session.execute(query)
            rows = result.all()

            pnl_data = []
            for row in rows:
                # Solo incluir traders con PnL válido
                if row.pnl_with_cost_sol is not None:
                    pnl_data.append({
                        "trader_wallet": row.trader_wallet,
                        "pnl_with_cost_sol": row.pnl_with_cost_sol,
                    })

            self._logger.debug(
                f"Obtenidos {len(pnl_data)} traders con PnL acumulado para run {runs_id}"
            )

            return pnl_data

    async def get_run_info(self, runs_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """
        Obtiene información completa de un run.

        Args:
            runs_id: ID del run

        Returns:
            Diccionario con información del run o None si no existe
        """
        async with (await self._get_session()) as session:
            run = await session.get(Run, runs_id)
            if not run:
                return None

            return {
                "id": str(run.id),
                "is_dry_run": run.is_dry_run,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "initial_capital_sol": run.initial_capital_sol,
                "final_capital_sol": run.final_capital_sol,
                "copy_trading_bots_id": run.copy_trading_bots_id,
            }
