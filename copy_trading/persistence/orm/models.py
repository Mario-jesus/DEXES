# -*- coding: utf-8 -*-
import uuid
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Enum, ForeignKey, UUID, DECIMAL, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .enums import OpenPositionStatus, CloseOrderStatus, Side, PartialCloseOrderStatus
from ..base import Base

DEC_SOL = DECIMAL(18, 9)
DEC_TOK = DECIMAL(18, 6)


class CopyTradingBot(Base):
    __tablename__ = "copy_trading_bots"

    system_wallet_address: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    runs: Mapped[List["Run"]] = relationship(back_populates="copy_trading_bot", uselist=True, cascade="all")


class Trader(Base):
    __tablename__ = "traders"

    wallet_address: Mapped[str] = mapped_column(String(50), primary_key=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    positions: Mapped[List["Position"]] = relationship(back_populates="trader", uselist=True)
    run_traders: Mapped[List["RunTrader"]] = relationship(back_populates="trader", uselist=True, cascade="all, delete-orphan", single_parent=True, passive_deletes=True)


class Mint(Base):
    __tablename__ = "mints"

    mint_address: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    positions: Mapped[List["Position"]] = relationship(back_populates="mint", uselist=True)
    run_mints: Mapped[List["RunMint"]] = relationship(back_populates="mint", uselist=True, cascade="all, delete-orphan", single_parent=True, passive_deletes=True)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    is_dry_run: Mapped[bool] = mapped_column(default=False, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    copy_trading_bots_id: Mapped[str] = mapped_column(
        ForeignKey("copy_trading_bots.system_wallet_address", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    copy_trading_bot: Mapped["CopyTradingBot"] = relationship(back_populates="runs", uselist=False)
    run_traders: Mapped[List["RunTrader"]] = relationship(back_populates="run", uselist=True, cascade="all, delete-orphan", single_parent=True, passive_deletes=True)
    run_mints: Mapped[List["RunMint"]] = relationship(back_populates="run", uselist=True, cascade="all, delete-orphan", single_parent=True, passive_deletes=True)
    positions: Mapped[List["Position"]] = relationship(back_populates="run", uselist=True, cascade="all, delete-orphan", single_parent=True, passive_deletes=True)


class RunTrader(Base):
    __tablename__ = "run_traders"

    runs_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    traders_id: Mapped[str] = mapped_column(ForeignKey("traders.wallet_address", ondelete="CASCADE"), primary_key=True)

    run: Mapped["Run"] = relationship(back_populates="run_traders", uselist=False)
    trader: Mapped["Trader"] = relationship(back_populates="run_traders", uselist=False)


class RunMint(Base):
    __tablename__ = "run_mints"

    runs_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    mints_id: Mapped[str] = mapped_column(ForeignKey("mints.mint_address", ondelete="CASCADE"), primary_key=True)

    run: Mapped["Run"] = relationship(back_populates="run_mints", uselist=False)
    mint: Mapped["Mint"] = relationship(back_populates="run_mints", uselist=False)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    fee_sol: Mapped[Optional[Decimal]] = mapped_column(DEC_SOL, nullable=True)
    total_cost_sol: Mapped[Optional[Decimal]] = mapped_column(DEC_SOL, nullable=True)
    signature: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)
    side: Mapped[Side] = mapped_column(Enum(Side), nullable=False)
    is_analyzed: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_liquidation: Mapped[bool] = mapped_column(default=False, nullable=False)
    message_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    runs_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False)
    mints_id: Mapped[str] = mapped_column(ForeignKey("mints.mint_address", ondelete="RESTRICT"), index=True, nullable=False)
    # Relación débil: nullable=True para permitir liquidaciones automáticas del sistema sin trader específico
    traders_id: Mapped[Optional[str]] = mapped_column(ForeignKey("traders.wallet_address", ondelete="RESTRICT"), index=True, nullable=True)

    mint: Mapped["Mint"] = relationship(back_populates="positions", uselist=False)
    trader: Mapped["Trader"] = relationship(back_populates="positions", uselist=False)
    run: Mapped["Run"] = relationship(back_populates="positions", uselist=False)
    open_position: Mapped["OpenPosition"] = relationship(back_populates="position", uselist=False, cascade="all, delete-orphan", single_parent=True, passive_deletes=True)
    close_orders: Mapped["CloseOrder"] = relationship(back_populates="position", uselist=False, cascade="all, delete-orphan", single_parent=True, passive_deletes=True)
    trade_data: Mapped["TraderTradeData"] = relationship(back_populates="position", uselist=False, cascade="all, delete-orphan", single_parent=True, passive_deletes=True)


class OpenPosition(Base):
    __tablename__ = "open_positions"

    positions_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), primary_key=True)
    sol_amount_sent: Mapped[Decimal] = mapped_column(DEC_SOL, nullable=False)
    sol_amount_executed: Mapped[Optional[Decimal]] = mapped_column(DEC_SOL, nullable=True)
    token_amount_received: Mapped[Optional[Decimal]] = mapped_column(DEC_TOK, nullable=True)
    status: Mapped[OpenPositionStatus] = mapped_column(Enum(OpenPositionStatus), default=OpenPositionStatus.PENDING)

    position: Mapped["Position"] = relationship(back_populates="open_position", uselist=False)
    close_orders: Mapped[List["CloseOrder"]] = relationship(back_populates="open_position", uselist=True, cascade="all")
    partials: Mapped[List["PartialCloseOrder"]] = relationship(back_populates="open_position", uselist=True, cascade="all")


class CloseOrder(Base):
    __tablename__ = "close_orders"

    positions_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), primary_key=True)
    open_positions_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("open_positions.positions_id", ondelete="SET NULL"), nullable=True)
    token_amount_sent: Mapped[Optional[Decimal]] = mapped_column(DEC_TOK, nullable=True)
    sol_amount_received: Mapped[Optional[Decimal]] = mapped_column(DEC_SOL, nullable=True)
    status: Mapped[CloseOrderStatus] = mapped_column(Enum(CloseOrderStatus), default=CloseOrderStatus.PENDING)

    position: Mapped["Position"] = relationship(back_populates="close_orders", uselist=False)
    open_position: Mapped["OpenPosition"] = relationship(back_populates="close_orders", uselist=False)
    partials: Mapped[List["PartialCloseOrder"]] = relationship(back_populates="close_order", uselist=True, cascade="all, delete-orphan", single_parent=True, passive_deletes=True)


class PartialCloseOrder(Base):
    __tablename__ = "partial_close_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    close_orders_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("close_orders.positions_id", ondelete="CASCADE"))
    open_positions_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("open_positions.positions_id", ondelete="SET NULL"), nullable=True)
    token_amount_sent: Mapped[Optional[Decimal]] = mapped_column(DEC_TOK, nullable=True)
    sol_amount_received: Mapped[Optional[Decimal]] = mapped_column(DEC_SOL, nullable=True)
    total_cost_sol: Mapped[Optional[Decimal]] = mapped_column(DEC_SOL, nullable=True)
    message_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[PartialCloseOrderStatus] = mapped_column(Enum(PartialCloseOrderStatus), default=PartialCloseOrderStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    close_order: Mapped["CloseOrder"] = relationship(back_populates="partials", uselist=False)
    open_position: Mapped["OpenPosition"] = relationship(back_populates="partials", uselist=False)


class TraderTradeData(Base):
    __tablename__ = "trader_trade_data"

    positions_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), primary_key=True)
    sol_amount: Mapped[Decimal] = mapped_column(DEC_SOL, nullable=False)
    token_amount: Mapped[Decimal] = mapped_column(DEC_TOK, nullable=False)
    new_token_balance: Mapped[Decimal] = mapped_column(DEC_TOK, nullable=False)
    signature: Mapped[str] = mapped_column(String(100), nullable=False)
    pool: Mapped[str] = mapped_column(String(15), nullable=False)
    bonding_curve_key: Mapped[str] = mapped_column(String(50), nullable=False)
    v_sol_in_bonding_curve: Mapped[Decimal] = mapped_column(DEC_SOL, nullable=False)
    v_tokens_in_bonding_curve: Mapped[Decimal] = mapped_column(DEC_TOK, nullable=False)
    market_cap_sol: Mapped[Decimal] = mapped_column(DEC_SOL, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    position: Mapped["Position"] = relationship(back_populates="trade_data", uselist=False)
