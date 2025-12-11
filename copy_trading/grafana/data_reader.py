# -*- coding: utf-8 -*-
"""
Lector de datos desde la base de datos usando ORM.
Lee capital inicial y PnL desde las tablas correspondientes.
"""
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from logging_system import AppLogger
from ..persistence.session import get_session
from ..persistence.orm.models import (
    Run,
    PNLRealizedPosition,
    OpenPosition,
    Position,
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

    async def get_pnl_realized_positions(
        self,
        runs_id: uuid.UUID,
        *,
        last_timestamp: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Obtiene PnL realizado de posiciones con sus timestamps.

        Adapta la consulta SQL:
        SELECT p.created_at::timestamptz AS time, 
                prp.pnl_without_cost_sol, 
                prp.pnl_with_cost_sol
            FROM pnl_realized_position AS prp
        INNER JOIN open_positions AS op ON prp.open_positions_id = op.positions_id
        INNER JOIN positions AS p ON op.positions_id = p.id
        WHERE p.runs_id = runs_id
        [AND p.created_at > last_timestamp]

        Args:
            runs_id: ID del run
            last_timestamp: Timestamp opcional para lectura incremental

        Returns:
            Lista de diccionarios con: timestamp, trader_wallet, pnl_without_cost_sol, pnl_with_cost_sol
        """
        async with (await self._get_session()) as session:
            # Construir query con joins (incluyendo traders_id)
            query = (
                select(
                    Position.created_at.label("timestamp"),
                    Position.traders_id.label("trader_wallet"),
                    PNLRealizedPosition.pnl_without_cost_sol,
                    PNLRealizedPosition.pnl_with_cost_sol,
                )
                .select_from(PNLRealizedPosition)
                .join(OpenPosition, PNLRealizedPosition.open_positions_id == OpenPosition.positions_id)
                .join(Position, OpenPosition.positions_id == Position.id)
                .where(Position.runs_id == runs_id)
            )

            # Filtrar por timestamp si se proporciona
            if last_timestamp:
                query = query.where(Position.created_at > last_timestamp)

            # Ordenar por timestamp ascendente
            query = query.order_by(Position.created_at.asc())

            result = await session.execute(query)
            rows = result.all()

            pnl_data = []
            for row in rows:
                pnl_data.append({
                    "timestamp": row.timestamp,
                    "trader_wallet": row.trader_wallet,
                    "pnl_without_cost_sol": row.pnl_without_cost_sol,
                    "pnl_with_cost_sol": row.pnl_with_cost_sol,
                })

            self._logger.debug(
                f"Obtenidos {len(pnl_data)} registros de PnL para run {runs_id}"
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
