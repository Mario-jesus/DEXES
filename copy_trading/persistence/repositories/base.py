# -*- coding: utf-8 -*-
from typing import Optional, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession

from ..session import get_session


class AsyncRepository:
    """Repositorio base asíncrono con proveedor de sesión."""

    def __init__(self, session_factory: Optional[Callable[[], Awaitable[AsyncSession]]] = None) -> None:
        self._session_factory: Callable[[], Awaitable[AsyncSession]] = session_factory or get_session

    async def _get_session(self) -> AsyncSession:
        return await self._session_factory()

    async def _commit(self, session: AsyncSession) -> None:
        await session.commit()
