# -*- coding: utf-8 -*-
"""
Eventos desacoplados del ciclo de vida de posiciones usando pyee.AsyncIOEventEmitter.

Este módulo define:
- Dataclasses estrictamente tipadas para eventos de posiciones
- Un bus de eventos basado en AsyncIOEventEmitter con métodos de suscripción y emisión

Objetivo: desacoplar la comunicación entre módulos del sistema de copy trading.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Final, Literal, Optional, Protocol, TypeVar, List
from pyee.asyncio import AsyncIOEventEmitter


# Tipos de nombre de eventos soportados
PositionEventName = Literal[
    "position.validation.failed",
    "position.created",
    "position.queued",
    "position.execution.started",
    "position.executed",
    "position.execution.failed",
    "position.analysis",
    "position.analysis.finished",
    "position.opened",
    "position.updated",
    "position.close.requested",
    "position.close.executed",
    "position.closed",
    "position.partial_closed",
    "position.trader_trade_data",
    "position.failed",
    "mint.metadata.updated",
]


@dataclass(slots=True)
class BasePositionEvent:
    """Evento base para todas las notificaciones de posiciones.

    Nota: Mantener este modelo liviano para evitar dependencias fuertes.
    """
    position_id: str
    token_address: str
    trader_wallet: str
    timestamp: datetime = field(default_factory=datetime.now)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)


# Eventos específicos del ciclo de vida
@dataclass(slots=True)
class PositionValidationFailedEvent(BasePositionEvent):
    error_message: str = ""


@dataclass(slots=True)
class PositionCreatedEvent(BasePositionEvent):
    run_id: Optional[uuid.UUID] = None
    amount_sol: str = ""
    amount_tokens: str = ""
    side: Literal["buy", "sell"] = "buy"
    signature: str = ""
    is_liquidation: bool = False


@dataclass(slots=True)
class PositionQueuedEvent(BasePositionEvent):
    queue_name: Literal[
        "pending_position_queue",
        "analysis_position_queue",
        "open_position_queue",
        "closed_position_queue",
        "notification_queue"
    ] = "pending_position_queue"


@dataclass(slots=True)
class PositionExecutionStartedEvent(BasePositionEvent):
    attempt: int = 1


@dataclass(slots=True)
class PositionExecutedEvent(BasePositionEvent):
    signature: str = ""
    execution_price: str = ""
    fee_sol: str = ""
    total_cost_sol: str = ""


@dataclass(slots=True)
class PositionExecutionFailedEvent(BasePositionEvent):
    error_message: str = ""


@dataclass(slots=True)
class PositionAnalysisEvent(BasePositionEvent):
    success: bool = False
    position_type: Literal["open", "close"] = "open"
    mint_address: Optional[str] = None
    signer_sol_delta: Optional[str] = None
    token_ui_delta: Optional[str] = None
    amount_sol_executed: Optional[str] = None
    amount_tokens_executed: Optional[str] = None
    fee_sol: Optional[str] = None
    total_cost_sol: Optional[str] = None


@dataclass(slots=True)
class PositionAnalysisFinishedEvent(BasePositionEvent):
    success: bool = False
    position_type: Literal["open", "close"] = "open"
    error_kind: Optional[Literal["slippage", "insufficient_tokens", "insufficient_lamports", "transaction_not_found", "insufficient_funds_for_rent", "insufficient_compute_units", "unknown"]] = None
    error_message: Optional[str] = None


@dataclass(slots=True)
class PositionOpenedEvent(BasePositionEvent):
    amount_sol: str = ""
    description: Optional[str] = None


@dataclass(slots=True)
class PositionUpdatedEvent(BasePositionEvent):
    update_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PositionCloseRequestedEvent(BasePositionEvent):
    reason: Optional[str] = None


@dataclass(slots=True)
class PositionCloseExecutedEvent(BasePositionEvent):
    processed_open_position_ids: List[str] = field(default_factory=list)
    last_partial_closure: bool = False
    status: Literal["success", "failed"] = "success"

@dataclass(slots=True)
class PositionClosedEvent(BasePositionEvent):
    amount_sol: str = ""
    amount_tokens: str = ""


@dataclass(slots=True)
class PositionPartialClosedEvent(BasePositionEvent):
    close_position_id: str = ""
    open_position_id: str = ""
    amount_sol: str = ""
    amount_tokens: str = ""
    total_cost_sol: str = ""
    message_error: str = ""
    status: Literal["success", "failed"] = "success"


@dataclass(slots=True)
class PositionTraderTradeDataEvent(BasePositionEvent):
    signature: str = ""
    token_amount: str = ""
    amount_sol: str = ""
    tokens_in_pool: str = ""
    sol_in_pool: str = ""
    new_token_balance: str = ""
    bonding_curve_key: str = ""
    v_tokens_in_bonding_curve: str = ""
    v_sol_in_bonding_curve: str = ""
    market_cap_sol: str = ""
    pool: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(slots=True)
class PositionFailedEvent(BasePositionEvent):
    position_type: Literal["open", "close"] = "open"
    error_message: str = ""


@dataclass(slots=True)
class MintMetadataUpdatedEvent:
    """Evento para actualizar metadatos básicos del mint."""
    run_id: uuid.UUID
    mint_address: str
    name: Optional[str] = None
    symbol: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


# Handlers tipados
TEvent = TypeVar("TEvent", bound=BasePositionEvent, contravariant=True)


class AsyncEventHandler(Protocol[TEvent]):
    async def __call__(self, event: TEvent) -> None:  # pragma: no cover - typing only
        ...


class PositionEventBus:
    """Bus de eventos para posiciones basado en AsyncIOEventEmitter.

    Proporciona métodos tipados para suscribirse y emitir eventos específicos
    del ciclo de vida de posiciones, manteniendo módulos desacoplados.
    """

    # Nombres de eventos (constantes)
    EVT_VALIDATION_FAILED: Final[PositionEventName] = "position.validation.failed"
    EVT_CREATED: Final[PositionEventName] = "position.created"
    EVT_QUEUED: Final[PositionEventName] = "position.queued"
    EVT_EXECUTION_STARTED: Final[PositionEventName] = "position.execution.started"
    EVT_EXECUTED: Final[PositionEventName] = "position.executed"
    EVT_EXECUTION_FAILED: Final[PositionEventName] = "position.execution.failed"
    EVT_ANALYSIS: Final[PositionEventName] = "position.analysis"
    EVT_ANALYSIS_FINISHED: Final[PositionEventName] = "position.analysis.finished"
    EVT_OPENED: Final[PositionEventName] = "position.opened"
    EVT_UPDATED: Final[PositionEventName] = "position.updated"
    EVT_CLOSE_REQUESTED: Final[PositionEventName] = "position.close.requested"
    EVT_CLOSE_EXECUTED: Final[PositionEventName] = "position.close.executed"
    EVT_CLOSED: Final[PositionEventName] = "position.closed"
    EVT_PARTIAL_CLOSED: Final[PositionEventName] = "position.partial_closed"
    EVT_TRADER_TRADE_DATA: Final[PositionEventName] = "position.trader_trade_data"
    EVT_FAILED: Final[PositionEventName] = "position.failed"
    EVT_MINT_METADATA_UPDATED: Final[PositionEventName] = "mint.metadata.updated"

    def __init__(self, emitter: Optional[AsyncIOEventEmitter] = None, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._emitter: AsyncIOEventEmitter = emitter or AsyncIOEventEmitter(loop=self._loop)  # type: ignore[arg-type]

    # Suscriptores
    def on_position_validation_failed(self, handler: AsyncEventHandler[PositionValidationFailedEvent]) -> None:
        self._emitter.on(self.EVT_VALIDATION_FAILED, handler)

    def on_position_created(self, handler: AsyncEventHandler[PositionCreatedEvent]) -> None:
        self._emitter.on(self.EVT_CREATED, handler)

    def on_position_queued(self, handler: AsyncEventHandler[PositionQueuedEvent]) -> None:
        self._emitter.on(self.EVT_QUEUED, handler)

    def on_position_execution_started(self, handler: AsyncEventHandler[PositionExecutionStartedEvent]) -> None:
        self._emitter.on(self.EVT_EXECUTION_STARTED, handler)

    def on_position_executed(self, handler: AsyncEventHandler[PositionExecutedEvent]) -> None:
        self._emitter.on(self.EVT_EXECUTED, handler)

    def on_position_execution_failed(self, handler: AsyncEventHandler[PositionExecutionFailedEvent]) -> None:
        self._emitter.on(self.EVT_EXECUTION_FAILED, handler)

    def on_position_analysis(self, handler: AsyncEventHandler[PositionAnalysisEvent]) -> None:
        self._emitter.on(self.EVT_ANALYSIS, handler)

    def on_position_analysis_finished(self, handler: AsyncEventHandler[PositionAnalysisFinishedEvent]) -> None:
        self._emitter.on(self.EVT_ANALYSIS_FINISHED, handler)

    def on_position_opened(self, handler: AsyncEventHandler[PositionOpenedEvent]) -> None:
        self._emitter.on(self.EVT_OPENED, handler)

    def on_position_updated(self, handler: AsyncEventHandler[PositionUpdatedEvent]) -> None:
        self._emitter.on(self.EVT_UPDATED, handler)

    def on_position_close_requested(self, handler: AsyncEventHandler[PositionCloseRequestedEvent]) -> None:
        self._emitter.on(self.EVT_CLOSE_REQUESTED, handler)

    def on_position_close_executed(self, handler: AsyncEventHandler[PositionCloseExecutedEvent]) -> None:
        self._emitter.on(self.EVT_CLOSE_EXECUTED, handler)

    def on_position_closed(self, handler: AsyncEventHandler[PositionClosedEvent]) -> None:
        self._emitter.on(self.EVT_CLOSED, handler)

    def on_position_partial_closed(self, handler: AsyncEventHandler[PositionPartialClosedEvent]) -> None:
        self._emitter.on(self.EVT_PARTIAL_CLOSED, handler)

    def on_position_trader_trade_data(self, handler: AsyncEventHandler[PositionTraderTradeDataEvent]) -> None:
        self._emitter.on(self.EVT_TRADER_TRADE_DATA, handler)

    def on_position_failed(self, handler: AsyncEventHandler[PositionFailedEvent]) -> None:
        self._emitter.on(self.EVT_FAILED, handler)

    # Mint metadata events
    def on_mint_metadata_updated(self, handler: Callable[[MintMetadataUpdatedEvent], Any]) -> None:
        self._emitter.on(self.EVT_MINT_METADATA_UPDATED, handler)

    # Emisores
    def emit_position_validation_failed(self, event: PositionValidationFailedEvent) -> None:
        self._emitter.emit(self.EVT_VALIDATION_FAILED, event)

    def emit_position_created(self, event: PositionCreatedEvent) -> None:
        self._emitter.emit(self.EVT_CREATED, event)

    def emit_position_queued(self, event: PositionQueuedEvent) -> None:
        self._emitter.emit(self.EVT_QUEUED, event)

    def emit_position_execution_started(self, event: PositionExecutionStartedEvent) -> None:
        self._emitter.emit(self.EVT_EXECUTION_STARTED, event)

    def emit_position_executed(self, event: PositionExecutedEvent) -> None:
        self._emitter.emit(self.EVT_EXECUTED, event)

    def emit_position_execution_failed(self, event: PositionExecutionFailedEvent) -> None:
        self._emitter.emit(self.EVT_EXECUTION_FAILED, event)

    def emit_position_analysis(self, event: PositionAnalysisEvent) -> None:
        self._emitter.emit(self.EVT_ANALYSIS, event)

    def emit_position_analysis_finished(self, event: PositionAnalysisFinishedEvent) -> None:
        self._emitter.emit(self.EVT_ANALYSIS_FINISHED, event)

    def emit_position_opened(self, event: PositionOpenedEvent) -> None:
        self._emitter.emit(self.EVT_OPENED, event)

    def emit_position_updated(self, event: PositionUpdatedEvent) -> None:
        self._emitter.emit(self.EVT_UPDATED, event)

    def emit_position_close_requested(self, event: PositionCloseRequestedEvent) -> None:
        self._emitter.emit(self.EVT_CLOSE_REQUESTED, event)

    def emit_position_close_executed(self, event: PositionCloseExecutedEvent) -> None:
        self._emitter.emit(self.EVT_CLOSE_EXECUTED, event)

    def emit_position_closed(self, event: PositionClosedEvent) -> None:
        self._emitter.emit(self.EVT_CLOSED, event)

    def emit_position_partial_closed(self, event: PositionPartialClosedEvent) -> None:
        self._emitter.emit(self.EVT_PARTIAL_CLOSED, event)

    def emit_position_trader_trade_data(self, event: PositionTraderTradeDataEvent) -> None:
        self._emitter.emit(self.EVT_TRADER_TRADE_DATA, event)

    def emit_position_failed(self, event: PositionFailedEvent) -> None:
        self._emitter.emit(self.EVT_FAILED, event)

    def emit_mint_metadata_updated(self, event: MintMetadataUpdatedEvent) -> None:
        self._emitter.emit(self.EVT_MINT_METADATA_UPDATED, event)

    # Utilidades
    def off(self, event_name: PositionEventName, handler: Callable[..., Any]) -> None:
        self._emitter.remove_listener(event_name, handler)

    def remove_all_listeners(self, event_name: Optional[PositionEventName] = None) -> None:
        if event_name:
            self._emitter.remove_all_listeners(event_name)
        else:
            self._emitter.remove_all_listeners()

    @property
    def emitter(self) -> AsyncIOEventEmitter:
        return self._emitter
