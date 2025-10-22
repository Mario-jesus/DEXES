# -*- coding: utf-8 -*-
from typing import Optional

from .base import AsyncRepository
from ..orm.models import CopyTradingBot


class CopyTradingBotRepository(AsyncRepository):
    """Repositorio asíncrono para la tabla CopyTradingBot."""

    async def upsert_bot(self, system_wallet_address: str, name: str) -> CopyTradingBot:
        async with (await self._get_session()) as session:
            existing = await session.get(CopyTradingBot, system_wallet_address)
            if existing:
                if name and name.strip() != "":
                    existing.name = name
                await session.flush()
                await self._commit(session)
                return existing

            bot = CopyTradingBot(system_wallet_address=system_wallet_address, name=name or "")
            session.add(bot)
            await session.flush()
            await self._commit(session)
            return bot

    async def get(self, system_wallet_address: str) -> Optional[CopyTradingBot]:
        async with (await self._get_session()) as session:
            return await session.get(CopyTradingBot, system_wallet_address)
