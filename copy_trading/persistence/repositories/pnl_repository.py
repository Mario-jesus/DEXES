# -*- coding: utf-8 -*-
"""Repositorio para gestión de PNL realizado."""

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .base import AsyncRepository
from ..orm.models import (
    PNLRealizedMint,
    PNLRealizedPosition,
    PNLRealizedTrader,
    RunMint,
    RunTrader,
)


class PNLRepository(AsyncRepository):
    """Gestiona los registros de PNL realizado para posiciones, traders y mints."""

    async def record_realized_pnl(
        self,
        *,
        open_positions_id: uuid.UUID,
        pnl_without_cost_sol: Optional[Decimal],
        pnl_without_cost_pct_sol: Optional[Decimal],
        pnl_with_cost_sol: Optional[Decimal],
        pnl_with_cost_pct_sol: Optional[Decimal],
        runs_id: uuid.UUID,
        wallet_address: str,
        mint_address: str,
        volume_sol: Optional[Decimal] = None,
    ) -> None:
        """Registra el PNL realizado para una posición y acumula para trader y mint.

        Args:
            open_positions_id: Identificador del registro en ``open_positions``.
            pnl_without_cost_sol: PNL en SOL sin costos.
            pnl_without_cost_pct_sol: PNL porcentual sin costos.
            pnl_with_cost_sol: PNL en SOL con costos.
            pnl_with_cost_pct_sol: PNL porcentual con costos.
            runs_id: Identificador del run al que pertenece la operación.
            wallet_address: Wallet del trader asociado.
            mint_address: Mint de la posición evaluada.
            volume_sol: Volumen en SOL de la posición (monto invertido inicial).
        """

        async with (await self._get_session()) as session:
            await self._upsert_position_pnl(
                session=session,
                open_positions_id=open_positions_id,
                pnl_without_cost_sol=pnl_without_cost_sol,
                pnl_without_cost_pct_sol=pnl_without_cost_pct_sol,
                pnl_with_cost_sol=pnl_with_cost_sol,
                pnl_with_cost_pct_sol=pnl_with_cost_pct_sol,
            )

            await self._accumulate_trader_pnl(
                session=session,
                runs_id=runs_id,
                wallet_address=wallet_address,
                pnl_without_cost_sol=pnl_without_cost_sol,
                pnl_with_cost_sol=pnl_with_cost_sol,
                volume_sol=volume_sol,
            )

            await self._accumulate_mint_pnl(
                session=session,
                runs_id=runs_id,
                mint_address=mint_address,
                pnl_without_cost_sol=pnl_without_cost_sol,
                pnl_with_cost_sol=pnl_with_cost_sol,
                volume_sol=volume_sol,
            )

            await self._commit(session)

    async def _upsert_position_pnl(
        self,
        *,
        session: AsyncSession,
        open_positions_id: uuid.UUID,
        pnl_without_cost_sol: Optional[Decimal],
        pnl_without_cost_pct_sol: Optional[Decimal],
        pnl_with_cost_sol: Optional[Decimal],
        pnl_with_cost_pct_sol: Optional[Decimal],
    ) -> None:
        result = await session.execute(
            select(PNLRealizedPosition).where(
                PNLRealizedPosition.open_positions_id == open_positions_id
            )
        )
        existing = result.scalars().first()

        if existing:
            existing.pnl_without_cost_sol = pnl_without_cost_sol
            existing.pnl_without_cost_pct_sol = pnl_without_cost_pct_sol
            existing.pnl_with_cost_sol = pnl_with_cost_sol
            existing.pnl_with_cost_pct_sol = pnl_with_cost_pct_sol
            await session.flush()
            return

        position_pnl = PNLRealizedPosition(
            id=uuid.uuid4(),
            open_positions_id=open_positions_id,
            pnl_without_cost_sol=pnl_without_cost_sol,
            pnl_without_cost_pct_sol=pnl_without_cost_pct_sol,
            pnl_with_cost_sol=pnl_with_cost_sol,
            pnl_with_cost_pct_sol=pnl_with_cost_pct_sol,
        )
        session.add(position_pnl)
        await session.flush()

    async def _accumulate_trader_pnl(
        self,
        *,
        session: AsyncSession,
        runs_id: uuid.UUID,
        wallet_address: str,
        pnl_without_cost_sol: Optional[Decimal],
        pnl_with_cost_sol: Optional[Decimal],
        volume_sol: Optional[Decimal],
    ) -> None:
        run_trader = await session.get(RunTrader, (runs_id, wallet_address))
        if not run_trader:
            raise ValueError(
                f"No existe relación RunTrader para run {runs_id} y trader {wallet_address}."
            )

        result = await session.execute(
            select(PNLRealizedTrader).where(
                PNLRealizedTrader.runs_id == runs_id,
                PNLRealizedTrader.traders_id == wallet_address,
            )
        )
        trader_pnl = result.scalars().first()

        if trader_pnl is None:
            # Primer registro: calcular porcentajes iniciales
            pnl_without_cost_pct = self._calculate_percentage(pnl_without_cost_sol, volume_sol)
            pnl_with_cost_pct = self._calculate_percentage(pnl_with_cost_sol, volume_sol)

            trader_pnl = PNLRealizedTrader(
                id=uuid.uuid4(),
                runs_id=runs_id,
                traders_id=wallet_address,
                pnl_without_cost_sol=pnl_without_cost_sol,
                pnl_without_cost_pct_sol=pnl_without_cost_pct,
                pnl_with_cost_sol=pnl_with_cost_sol,
                pnl_with_cost_pct_sol=pnl_with_cost_pct,
                total_volume_sol=volume_sol,
            )
            session.add(trader_pnl)
            await session.flush()
            return

        # Acumular PnL en SOL
        trader_pnl.pnl_without_cost_sol = self._add(trader_pnl.pnl_without_cost_sol, pnl_without_cost_sol)
        trader_pnl.pnl_with_cost_sol = self._add(trader_pnl.pnl_with_cost_sol, pnl_with_cost_sol)

        # Acumular volumen
        trader_pnl.total_volume_sol = self._add(trader_pnl.total_volume_sol, volume_sol)

        # Recalcular porcentajes basados en totales acumulados
        trader_pnl.pnl_without_cost_pct_sol = self._calculate_percentage(
            trader_pnl.pnl_without_cost_sol, 
            trader_pnl.total_volume_sol
        )
        trader_pnl.pnl_with_cost_pct_sol = self._calculate_percentage(
            trader_pnl.pnl_with_cost_sol, 
            trader_pnl.total_volume_sol
        )

        await session.flush()

    async def _accumulate_mint_pnl(
        self,
        *,
        session: AsyncSession,
        runs_id: uuid.UUID,
        mint_address: str,
        pnl_without_cost_sol: Optional[Decimal],
        pnl_with_cost_sol: Optional[Decimal],
        volume_sol: Optional[Decimal],
    ) -> None:
        run_mint = await session.get(RunMint, (runs_id, mint_address))
        if not run_mint:
            raise ValueError(
                f"No existe relación RunMint para run {runs_id} y mint {mint_address}."
            )

        result = await session.execute(
            select(PNLRealizedMint).where(
                PNLRealizedMint.runs_id == runs_id,
                PNLRealizedMint.mints_id == mint_address,
            )
        )
        mint_pnl = result.scalars().first()

        if mint_pnl is None:
            # Primer registro: calcular porcentajes iniciales
            pnl_without_cost_pct = self._calculate_percentage(pnl_without_cost_sol, volume_sol)
            pnl_with_cost_pct = self._calculate_percentage(pnl_with_cost_sol, volume_sol)

            mint_pnl = PNLRealizedMint(
                id=uuid.uuid4(),
                runs_id=runs_id,
                mints_id=mint_address,
                pnl_without_cost_sol=pnl_without_cost_sol,
                pnl_without_cost_pct_sol=pnl_without_cost_pct,
                pnl_with_cost_sol=pnl_with_cost_sol,
                pnl_with_cost_pct_sol=pnl_with_cost_pct,
                total_volume_sol=volume_sol,
            )
            session.add(mint_pnl)
            await session.flush()
            return

        # Acumular PnL en SOL
        mint_pnl.pnl_without_cost_sol = self._add(mint_pnl.pnl_without_cost_sol, pnl_without_cost_sol)
        mint_pnl.pnl_with_cost_sol = self._add(mint_pnl.pnl_with_cost_sol, pnl_with_cost_sol)

        # Acumular volumen
        mint_pnl.total_volume_sol = self._add(mint_pnl.total_volume_sol, volume_sol)

        # Recalcular porcentajes basados en totales acumulados
        mint_pnl.pnl_without_cost_pct_sol = self._calculate_percentage(
            mint_pnl.pnl_without_cost_sol, 
            mint_pnl.total_volume_sol
        )
        mint_pnl.pnl_with_cost_pct_sol = self._calculate_percentage(
            mint_pnl.pnl_with_cost_sol, 
            mint_pnl.total_volume_sol
        )

        await session.flush()

    @staticmethod
    def _add(current: Optional[Decimal], delta: Optional[Decimal]) -> Optional[Decimal]:
        if delta is None:
            return current
        if current is None:
            return delta
        return current + delta

    @staticmethod
    def _calculate_percentage(pnl: Optional[Decimal], volume: Optional[Decimal]) -> Optional[Decimal]:
        """Calcula el porcentaje de PnL basado en el volumen.
        
        Args:
            pnl: PnL en SOL
            volume: Volumen total en SOL
            
        Returns:
            Porcentaje como Decimal o None si no se puede calcular
        """
        if pnl is None or volume is None or volume == Decimal('0'):
            return None
        return (pnl / volume) * Decimal('100')
