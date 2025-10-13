# -*- coding: utf-8 -*-
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from .config import DATABASE_URL, ECHO_SQL

if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL is not configured. Please set either: Individual PostgreSQL variables: PGUSER, PGPASSWORD, PGDATABASE"
    )

engine = create_async_engine(DATABASE_URL, echo=ECHO_SQL, future=True, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session() -> AsyncSession:
    return SessionLocal()
