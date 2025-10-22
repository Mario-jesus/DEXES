# -*- coding: utf-8 -*-
import uuid
from typing import Optional
from sqlalchemy import func

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

    async def get(self, run_id: uuid.UUID) -> Optional[Run]:
        async with (await self._get_session()) as session:
            return await session.get(Run, run_id)
