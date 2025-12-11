# -*- coding: utf-8 -*-
import uuid
from typing import Optional, List
from decimal import Decimal
from sqlalchemy import func, select

from .base import AsyncRepository
from ..orm.models import Run


class RunRepository(AsyncRepository):
    """Repositorio asíncrono para la tabla Run."""

    async def create(self, run_id: uuid.UUID, copy_trading_bots_id: str, is_dry_run: bool = False) -> Run:
        async with (await self._get_session()) as session:
            run = Run(id=run_id, copy_trading_bots_id=copy_trading_bots_id, is_dry_run=is_dry_run)
            session.add(run)
            await session.flush()
            await self._commit(session)
            return run

    async def set_started(self, run_id: uuid.UUID) -> Optional[Run]:
        async with (await self._get_session()) as session:
            run = await session.get(Run, run_id)
            if not run:
                return None
            run.started_at = func.now()
            await session.flush()
            await self._commit(session)
            return run

    async def set_ended(self, run_id: uuid.UUID) -> Optional[Run]:
        async with (await self._get_session()) as session:
            run = await session.get(Run, run_id)
            if not run:
                return None
            run.ended_at = func.now()
            await session.flush()
            await self._commit(session)
            return run

    async def set_initial_capital_sol(self, run_id: uuid.UUID, initial_capital_sol: Decimal) -> Optional[Run]:
        async with (await self._get_session()) as session:
            run = await session.get(Run, run_id)
            if not run:
                return None
            run.initial_capital_sol = initial_capital_sol
            await session.flush()
            await self._commit(session)
            return run

    async def set_final_capital_sol(self, run_id: uuid.UUID, final_capital_sol: Decimal) -> Optional[Run]:
        async with (await self._get_session()) as session:
            run = await session.get(Run, run_id)
            if not run:
                return None
            run.final_capital_sol = final_capital_sol
            await session.flush()
            await self._commit(session)
            return run

    async def get(self, run_id: uuid.UUID) -> Optional[Run]:
        async with (await self._get_session()) as session:
            return await session.get(Run, run_id)

    async def get_latest_by_system_wallet(self, system_wallet_address: str) -> Optional[Run]:
        """
        Obtiene la corrida más reciente (run) para un system_wallet_address específico.
        
        La búsqueda se realiza ordenando por started_at descendente y tomando el primero.
        Si no hay started_at, se ordena por created_at implícito o por id.
        
        Args:
            system_wallet_address: Dirección de wallet del sistema (copy_trading_bots_id)
            
        Returns:
            Run más reciente o None si no existe
        """
        async with (await self._get_session()) as session:
            query = select(Run).where(
                Run.copy_trading_bots_id == system_wallet_address
            ).order_by(
                Run.started_at.desc().nulls_last()
            ).limit(1)

            result = await session.execute(query)
            return result.scalars().first()

    async def get_all_latest_runs(self) -> List[Run]:
        """
        Obtiene el run más reciente para cada sistema (copy_trading_bots_id).
        
        Para cada sistema, obtiene el run con started_at más reciente.
        
        Returns:
            Lista de Runs más recientes por sistema
        """
        async with (await self._get_session()) as session:
            # Subquery para obtener el máximo started_at por sistema
            from sqlalchemy import func, distinct

            # Obtener todos los sistemas únicos
            systems_query = select(distinct(Run.copy_trading_bots_id))
            systems_result = await session.execute(systems_query)
            system_addresses = [row[0] for row in systems_result.all()]

            latest_runs = []
            for system_address in system_addresses:
                latest_run = await self.get_latest_by_system_wallet(system_address)
                if latest_run:
                    latest_runs.append(latest_run)

            return latest_runs
