# -*- coding: utf-8 -*-
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from .base import AsyncRepository
from ..orm.models import Trader, Mint


class TraderMintRepository(AsyncRepository):
    """Repositorio asíncrono para upsert de Traders y Mints."""

    async def upsert_trader(self, wallet_address: str, nickname: Optional[str] = None) -> Trader:
        async with (await self._get_session()) as session:
            trader = await self._upsert_trader(session, wallet_address, nickname)
            await self._commit(session)
            return trader

    async def bulk_upsert_traders(self, items: List[Tuple[str, Optional[str]]]) -> int:
        """
        Inserta o actualiza múltiples traders en una misma transacción.

        Args:
            items: Lista de tuplas (wallet_address, nickname)

        Returns:
            Cantidad de registros procesados
        """
        if not items:
            return 0

        async with (await self._get_session()) as session:
            for wallet_address, nickname in items:
                await self._upsert_trader(session, wallet_address, nickname)
            await self._commit(session)
            return len(items)

    async def upsert_mint(self, mint_address: str, name: Optional[str] = None, symbol: Optional[str] = None) -> Mint:
        async with (await self._get_session()) as session:
            mint = await self._upsert_mint(session, mint_address, name, symbol)
            await self._commit(session)
            return mint

    async def bulk_upsert_mints(self, items: List[Tuple[str, Optional[str], Optional[str]]]) -> int:
        """
        Inserta o actualiza múltiples mints en una misma transacción.

        Args:
            items: Lista de tuplas (mint_address, name, symbol)

        Returns:
            Cantidad de registros procesados
        """
        if not items:
            return 0

        async with (await self._get_session()) as session:
            for mint_address, name, symbol in items:
                await self._upsert_mint(session, mint_address, name, symbol)
            await self._commit(session)
            return len(items)

    # ==================== MÉTODOS PRIVADOS ====================

    async def _upsert_trader(self, session: AsyncSession, wallet_address: str, nickname: Optional[str]) -> Trader:
        # Buscar existente por PK
        existing = await session.get(Trader, wallet_address)
        if existing:
            if nickname and nickname.strip() != "":
                existing.nickname = nickname
            await session.flush()
            return existing

        # Crear nuevo
        trader = Trader(wallet_address=wallet_address, nickname=nickname)
        session.add(trader)
        await session.flush()
        return trader

    async def _upsert_mint(self, session: AsyncSession, mint_address: str, name: Optional[str], symbol: Optional[str]) -> Mint:
        # Buscar existente por PK
        existing = await session.get(Mint, mint_address)
        if existing:
            # Actualizar campos si vienen valores no vacíos
            if name and name.strip() != "":
                existing.name = name
            if symbol and symbol.strip() != "":
                existing.symbol = symbol
            await session.flush()
            return existing

        # Crear nuevo
        mint = Mint(mint_address=mint_address, name=name, symbol=symbol)
        session.add(mint)
        await session.flush()
        return mint
