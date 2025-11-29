# -*- coding: utf-8 -*-
import uuid, asyncio
from typing import Callable, Awaitable, Type, Optional, Tuple, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal
from logging import getLogger
from logging import Logger
from cachetools import TTLCache
from ..session import get_session
from ..orm.models import Position, OpenPosition, CloseOrder, PartialCloseOrder, TraderTradeData, Mint
from ..orm.enums import Side, OpenPositionStatus, CloseOrderStatus, PartialCloseOrderStatus
from ..repositories.trader_mint_repository import TraderMintRepository
from copy_trading.events import (
    PositionCreatedEvent, PositionOpenedEvent,
    PositionPartialClosedEvent, PositionClosedEvent, PositionEventBus,
    PositionTraderTradeDataEvent, PositionAnalysisFinishedEvent, PositionAnalysisEvent, PositionCloseExecutedEvent, PositionFailedEvent, BasePositionEvent
)

_logger = getLogger(__name__)

class PositionEventsSubscriber:

    def __init__(self, session_factory: Callable[[], Awaitable[AsyncSession]] = get_session, trader_mint_repository_cls: Type[TraderMintRepository] = TraderMintRepository, logger: Optional[Logger] = None) -> None:
        self._get_session = session_factory
        self._trader_mint_repository_cls = trader_mint_repository_cls
        self._logger = logger or getLogger(__name__)
        self._lock = asyncio.Lock()
        # (id, entity_parent) -> {has_parent: bool, event_id1: PositionEventName1, event_id2: PositionEventName2, ...}
        self._event_cache: TTLCache[Tuple[str, str], Dict[str, Any]] = TTLCache(maxsize=1000, ttl=60)

    def attach(self, bus: PositionEventBus) -> None:
        self._logger.info("Registrando suscriptores de eventos de posiciones")
        bus.on_position_created(self._process_position_created_and_flush_children)
        bus.on_position_opened(self._buffer_or_dispatch_position_event)
        bus.on_position_closed(self._buffer_or_dispatch_position_event)
        bus.on_position_close_executed(self._on_closed_executed)
        bus.on_position_partial_closed(self._buffer_or_dispatch_close_event)
        bus.on_position_trader_trade_data(self._buffer_or_dispatch_position_event)
        bus.on_position_analysis_finished(self._on_analysis_finished)
        bus.on_position_analysis(self._on_analysis)
        bus.on_position_failed(self._on_failed)

    async def _process_position_created_and_flush_children(self, event: PositionCreatedEvent) -> None:
        self._logger.debug(f"Procesando PositionCreatedEvent para posición {event.position_id}")
        await self._on_created(event)

        # Mover eventos pendientes fuera del candado para procesarlos sin bloquear
        pending_events: Dict[str, Any] = {}
        async with self._lock:
            key = (event.position_id, "position")
            if key in self._event_cache:
                pending_events = {k: v for k, v in self._event_cache[key].items() if k != "has_parent"}
                self._event_cache[key]["has_parent"] = True
                self._logger.debug(
                    f"Eventos pendientes encontrados para posición {event.position_id}: {list(pending_events.keys())}"
                )
            else:
                self._event_cache[key] = {"has_parent": True}

        for event_id, evnt in pending_events.items():
            if isinstance(evnt, PositionTraderTradeDataEvent):
                await self._on_trader_trade_data(evnt)
            elif isinstance(evnt, PositionOpenedEvent):
                await self._on_opened(evnt)
            elif isinstance(evnt, PositionClosedEvent):
                await self._process_position_closed_and_flush_children(evnt)
            else:
                self._logger.warning(f"Evento {event_id} no soportado para position_id={event.position_id}")

    async def _buffer_or_dispatch_position_event(self, event: BasePositionEvent) -> None:
        self._logger.debug(
            f"Recibido evento {event.__class__.__name__} para posición {event.position_id} (event_id={event.event_id})"
        )
        async with self._lock:
            key = (event.position_id, "position")
            has_parent: bool = self._event_cache.get(key, {}).get("has_parent", False)
            self._logger.debug(
                f"key={key}, has_parent={has_parent}, event_id={event.event_id}"
            )
            if key not in self._event_cache:
                self._logger.debug(
                    f"No existe key en _event_cache, guardando evento temporalmente para posición {event.position_id} (event_id={event.event_id})"
                )
                self._event_cache[key] = {event.event_id: event}
                return
            elif not has_parent:
                self._logger.debug(
                    f"Key existe pero no tiene padre, agregando evento {event.event_id} a _event_cache[position_id={event.position_id}]"
                )
                self._event_cache[key][event.event_id] = event
                return

        self._logger.debug(f"Procesando evento {event.__class__.__name__} para posición {event.position_id} inmediatamente")
        if isinstance(event, PositionTraderTradeDataEvent):
            await self._on_trader_trade_data(event)
        elif isinstance(event, PositionOpenedEvent):
            await self._on_opened(event)
        elif isinstance(event, PositionClosedEvent):
            await self._process_position_closed_and_flush_children(event)

    async def _process_position_closed_and_flush_children(self, event: PositionClosedEvent) -> None:
        self._logger.debug(f"Procesando PositionClosedEvent para posición {event.position_id}")
        await self._on_closed(event)

        pending_events: Dict[str, Any] = {}
        async with self._lock:
            key = (event.position_id, "close")
            self._logger.debug(f"[closed_and_flush_children] Accediendo _event_cache con key={key}")
            if key in self._event_cache:
                pending_events = {k: v for k, v in self._event_cache[key].items() if k != "has_parent"}
                self._event_cache[key]["has_parent"] = True
                self._logger.debug(
                    f"[closed_and_flush_children] Eventos pendientes encontrados para posición {event.position_id}: {list(pending_events.keys())}"
                )
            else:
                self._event_cache[key] = {"has_parent": True}
                self._logger.debug(
                    f"[closed_and_flush_children] No se encontraron eventos pendientes para posición {event.position_id}"
                )

        for event_id, evnt in pending_events.items():
            if isinstance(evnt, PositionPartialClosedEvent):
                self._logger.debug(f"Llamando _on_partial_closed para event_id={event_id}, position_id={event.position_id}")
                await self._on_partial_closed(evnt)
            else:
                self._logger.warning(f"Evento {event_id} no soportado para position_id={event.position_id}")

    async def _buffer_or_dispatch_close_event(self, event: PositionPartialClosedEvent) -> None:
        self._logger.debug(
            f"[buffer_or_dispatch_close_event] Recibido evento {event.__class__.__name__} para posición {event.position_id} (event_id={event.event_id})"
        )
        async with self._lock:
            key = (event.close_position_id, "close")
            has_parent: bool = self._event_cache.get(key, {}).get("has_parent", False)
            self._logger.debug(
                f"[buffer_or_dispatch_close_event] key={key}, has_parent={has_parent}, event_id={event.event_id}"
            )
            if key not in self._event_cache:
                self._logger.debug(
                    f"[buffer_or_dispatch_close_event] No existe key en _event_cache, guardando evento temporalmente para posición {event.position_id} (event_id={event.event_id})"
                )
                self._event_cache[key] = {event.event_id: event}
                return
            elif not has_parent:
                self._logger.debug(
                    f"[buffer_or_dispatch_close_event] Key existe pero no tiene padre, agregando evento {event.event_id} a _event_cache[position_id={event.position_id}]"
                )
                self._event_cache[key][event.event_id] = event
                return

        if isinstance(event, PositionPartialClosedEvent):
            self._logger.debug(f"[buffer_or_dispatch_close_event] Procesando PositionPartialClosedEvent para posición {event.position_id} inmediatamente")
            await self._on_partial_closed(event)

    async def _on_trader_trade_data(self, event: PositionTraderTradeDataEvent) -> None:
        self._logger.debug(f"Recibido evento PositionTraderTradeDataEvent para posición {event.position_id}")
        async with (await self._get_session()) as s:
            self._logger.debug(
                f"Creando TraderTradeData con: "
                f"signature={event.signature}, token_amount={event.token_amount}, "
                f"sol_amount={event.amount_sol}, tokens_in_pool={event.tokens_in_pool}, "
                f"sol_in_pool={event.sol_in_pool}, new_token_balance={event.new_token_balance}, "
                f"bonding_curve_key={event.bonding_curve_key}, "
                f"v_tokens_in_bonding_curve={event.v_tokens_in_bonding_curve}, "
                f"v_sol_in_bonding_curve={event.v_sol_in_bonding_curve}, "
                f"market_cap_sol={event.market_cap_sol}, pool={event.pool}"
            )
            trader_trade_data = TraderTradeData(
                positions_id=uuid.UUID(event.position_id),
                signature=event.signature,
                token_amount=Decimal(event.token_amount),
                sol_amount=Decimal(event.amount_sol),
                tokens_in_pool=Decimal(event.tokens_in_pool) if event.tokens_in_pool and event.tokens_in_pool.strip() else None,
                sol_in_pool=Decimal(event.sol_in_pool) if event.sol_in_pool and event.sol_in_pool.strip() else None,
                new_token_balance=Decimal(event.new_token_balance) if event.new_token_balance and event.new_token_balance.strip() else None,
                bonding_curve_key=event.bonding_curve_key if event.bonding_curve_key and event.bonding_curve_key.strip() else None,
                v_tokens_in_bonding_curve=Decimal(event.v_tokens_in_bonding_curve) if event.v_tokens_in_bonding_curve and event.v_tokens_in_bonding_curve.strip() else None,
                v_sol_in_bonding_curve=Decimal(event.v_sol_in_bonding_curve) if event.v_sol_in_bonding_curve and event.v_sol_in_bonding_curve.strip() else None,
                market_cap_sol=Decimal(event.market_cap_sol) if event.market_cap_sol and event.market_cap_sol.strip() else Decimal("0"),
                pool=event.pool
            )
            s.add(trader_trade_data)
            try:
                self._logger.debug(f"[on_trader_trade_data] TraderTradeData agregado a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)

    async def _on_created(self, event: PositionCreatedEvent) -> None:
        if not event.run_id:
            self._logger.warning(f"Run ID is required for position created event: {event}")
            return

        async with (await self._get_session()) as s:
            mint = await s.get(Mint, event.token_address)
            if not mint:
                self._logger.debug(f"Mint {event.token_address} no existe, creando registro")
                repo = self._trader_mint_repository_cls()
                await repo.add_mint_to_run(
                    run_id=event.run_id,
                    mint_address=event.token_address,
                    name=None,
                    symbol=None,
                )

            self._logger.info(f"Creando posición {event.position_id} para trader {event.trader_wallet}")
            position = Position(
                id=uuid.UUID(event.position_id),
                mints_id=event.token_address,
                side=Side(event.side.upper()),
                is_liquidation=event.is_liquidation,
                runs_id=event.run_id
            )

            if event.signature.strip() != "":
                position.signature = event.signature
            # Solo se setea el trader si no es una liquidación
            if event.trader_wallet.strip() != "" and not event.is_liquidation:
                position.traders_id = event.trader_wallet

            s.add(position)

            try:
                self._logger.debug(f"[on_created] Position agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)

    async def _on_opened(self, event: PositionOpenedEvent) -> None:
        async with (await self._get_session()) as s:
            self._logger.debug(f"Abriendo posición {event.position_id} con {event.amount_sol} SOL")
            open_position = OpenPosition(
                positions_id=uuid.UUID(event.position_id),
                status=OpenPositionStatus.PENDING,
                sol_amount_sent=Decimal(event.amount_sol) if event.amount_sol else Decimal(0)
            )
            if event.description:
                open_position.description = event.description
            s.add(open_position)

            try:
                self._logger.debug(f"[on_opened] OpenPosition agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)

    async def _on_closed(self, event: PositionClosedEvent) -> None:
        async with (await self._get_session()) as s:
            self._logger.debug(f"Cerrando posición {event.position_id}")
            close_order = CloseOrder(
                positions_id=uuid.UUID(event.position_id),
                status=CloseOrderStatus.PENDING
            )
            if event.amount_sol.strip() != "":
                close_order.sol_amount_received = Decimal(event.amount_sol)
            if event.amount_tokens.strip() != "":
                close_order.token_amount_sent = Decimal(event.amount_tokens)
            s.add(close_order)

            try:
                self._logger.debug(f"[on_closed] CloseOrder agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)

    async def _on_closed_executed(self, event: PositionCloseExecutedEvent) -> None:
        async with (await self._get_session()) as s:
            position = await s.get(Position, uuid.UUID(event.position_id))
            if not position:
                self._logger.warning(f"Position {event.position_id} not found")
                return

            close_order = await s.get(CloseOrder, uuid.UUID(event.position_id))
            if not close_order:
                self._logger.warning(f"Close order {event.position_id} not found")
                return

            close_status = CloseOrderStatus(event.status.upper())
            close_order.status = close_status
            self._logger.debug(f"Ejecutando cierre de posición {event.position_id} con estado {event.status}")

            if not event.processed_open_position_ids:
                message_error = "Processed open position ids is empty for position"
                self._logger.warning(f"{message_error} {event.position_id}")
                position.message_error = message_error
                close_order.status = CloseOrderStatus.FAILED

                try:
                    self._logger.debug(f"[on_closed_executed] Position agregada a la sesión. Commiteando en base de datos.")
                    await s.commit()
                except Exception as e:
                    self._logger.error(f"Error committing session: {e}", exc_info=True)
                return

            for idx, open_position_id in enumerate(event.processed_open_position_ids):
                open_position = await s.get(OpenPosition, uuid.UUID(open_position_id))
                if not open_position:
                    message_error = "Open position not found"
                    self._logger.warning(f"{message_error} {open_position_id}")

                    # Si es el último open position, la posición de cierre se marca como failed
                    if idx == len(event.processed_open_position_ids) - 1:
                        position.message_error = message_error
                        close_order.status = CloseOrderStatus.FAILED
                    continue

                # Si es el último open position y es parcial, la posición de cierre se marca como parcial
                if idx == len(event.processed_open_position_ids) - 1 and event.last_partial_closure:
                    open_position.status = OpenPositionStatus.PARTIALLY_CLOSED
                    break

                open_position.status = OpenPositionStatus.CLOSED

            close_order.open_positions_id = uuid.UUID(event.processed_open_position_ids[-1])

            try:
                self._logger.debug(f"[on_closed_executed] Position agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)
            self._logger.info(f"Cierre de posición {event.position_id} ejecutado: {close_status.value}")

    async def _on_partial_closed(self, event: PositionPartialClosedEvent) -> None:
        async with (await self._get_session()) as s:
            self._logger.debug(f"Procesando cierre parcial {event.position_id}")
            partial_close_order = PartialCloseOrder(
                id=uuid.UUID(event.position_id),
                close_orders_id=uuid.UUID(event.close_position_id),
                status=PartialCloseOrderStatus(event.status.upper()),
            )
            if event.open_position_id.strip() != "":
                partial_close_order.open_positions_id = uuid.UUID(event.open_position_id)
            else:
                partial_close_order.message_error = "Open position id is empty for partial close order"
                partial_close_order.status = PartialCloseOrderStatus.FAILED
            if event.amount_sol.strip() != "":
                partial_close_order.sol_amount_received = Decimal(event.amount_sol)
            if event.amount_tokens.strip() != "":
                partial_close_order.token_amount_sent = Decimal(event.amount_tokens)
            if event.total_cost_sol.strip() != "":
                partial_close_order.total_cost_sol = Decimal(event.total_cost_sol)
            if event.message_error.strip() != "":
                partial_close_order.message_error = event.message_error
            s.add(partial_close_order)
            await s.flush()

            if event.open_position_id.strip() != "":
                open_position = await s.get(OpenPosition, uuid.UUID(event.open_position_id))
                if not open_position:
                    message_error = "Open position not found"
                    self._logger.warning(f"{message_error} {event.open_position_id}")
                    partial_close_order.message_error = message_error
                    partial_close_order.status = PartialCloseOrderStatus.FAILED
                    try:
                        self._logger.debug(f"[on_partial_closed] PartialCloseOrder agregada a la sesión. Commiteando en base de datos.")
                        await s.commit()
                    except Exception as e:
                        self._logger.error(f"Error committing session: {e}", exc_info=True)
                    return

                if open_position.status == OpenPositionStatus.OPEN:
                    open_position.status = OpenPositionStatus.PARTIALLY_CLOSED

            try:
                self._logger.debug(f"[on_partial_closed] PartialCloseOrder agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)

    async def _on_analysis(self, event: PositionAnalysisEvent) -> None:
        async with (await self._get_session()) as s:
            position = await s.get(Position, uuid.UUID(event.position_id))
            if not position:
                self._logger.warning(f"Position {event.position_id} not found")
                return

            self._logger.debug(f"Analizando transacción de posición {event.position_id} tipo {event.position_type}")

            if event.fee_sol and event.fee_sol.strip() != "":
                position.fee_sol = Decimal(event.fee_sol)
            if event.total_cost_sol and event.total_cost_sol.strip() != "":
                position.total_cost_sol = Decimal(event.total_cost_sol)

            try:
                self._logger.debug(f"[on_analysis] Position agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)
                return

        async with (await self._get_session()) as s:
            if event.position_type == "open":
                open_position = await s.get(OpenPosition, event.position_id)
                if not open_position:
                    self._logger.warning(f"Open position {event.position_id} not found")
                    return

                sol_amount_executed = Decimal(event.amount_sol_executed) if event.amount_sol_executed else Decimal(0)
                open_position.sol_amount_executed = abs(sol_amount_executed) if event.amount_sol_executed else None
                token_amount_executed = Decimal(event.amount_tokens_executed) if event.amount_tokens_executed else Decimal(0)
                open_position.token_amount_received = abs(token_amount_executed) if event.amount_tokens_executed else None
                open_position.status = OpenPositionStatus.FAILED if not event.success else OpenPositionStatus.OPEN
                self._logger.debug(
                    f"Open position {event.position_id} updated: sol_amount_executed={open_position.sol_amount_executed}, token_amount_received={open_position.token_amount_received}, status={open_position.status}"
                )
            elif event.position_type == "close":
                close_order = await s.get(CloseOrder, event.position_id)
                if not close_order:
                    self._logger.warning(f"Close order {event.position_id} not found")
                    return

                token_amount_sent = Decimal(event.amount_tokens_executed) if event.amount_tokens_executed else Decimal(0)
                close_order.token_amount_sent = abs(token_amount_sent) if event.amount_tokens_executed else None
                sol_amount_received = Decimal(event.amount_sol_executed) if event.amount_sol_executed else Decimal(0)
                close_order.sol_amount_received = abs(sol_amount_received) if event.amount_sol_executed else None
                close_order.status = CloseOrderStatus.FAILED if not event.success else CloseOrderStatus.SUCCESS
                self._logger.debug(
                    f"Close order {event.position_id} updated: token_amount_sent={close_order.token_amount_sent}, sol_amount_received={close_order.sol_amount_received}, status={close_order.status}"
                )

            try:
                self._logger.debug(f"[on_analysis] Position {event.position_type} agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)
                return

    async def _on_analysis_finished(self, event: PositionAnalysisFinishedEvent) -> None:
        async with (await self._get_session()) as s:
            position = await s.get(Position, uuid.UUID(event.position_id))
            if not position:
                self._logger.warning(f"Position {event.position_id} not found")
                return

            position.is_analyzed = True

            if not event.success:
                message_error = event.error_message or event.error_kind
                position.message_error = message_error
                self._logger.warning(f"Análisis de posición {event.position_id} falló: {message_error}")

            try:
                self._logger.debug(f"[on_analysis_finished] Position agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)
                return

        if not event.success:
            async with (await self._get_session()) as s:
                if event.position_type == "open":
                    open_position = await s.get(OpenPosition, event.position_id)
                    if not open_position:
                        self._logger.warning(f"Open position {event.position_id} not found")
                        return
                    open_position.status = OpenPositionStatus.FAILED
                    self._logger.debug(f"Open position {event.position_id} updated: status={OpenPositionStatus.FAILED}")
                elif event.position_type == "close":
                    close_order = await s.get(CloseOrder, event.position_id)
                    if not close_order:
                        self._logger.warning(f"Close order {event.position_id} not found")
                        return
                    close_order.status = CloseOrderStatus.FAILED
                    self._logger.debug(f"Close order {event.position_id} updated: status={CloseOrderStatus.FAILED}")

                try:
                    self._logger.debug(f"[on_analysis_finished] Position agregada a la sesión. Commiteando en base de datos.")
                    await s.commit()
                except Exception as e:
                    self._logger.error(f"Error committing session: {e}", exc_info=True)
                    return
        else:
            self._logger.info(f"Análisis de posición {event.position_id} completado exitosamente")

    async def _on_failed(self, event: PositionFailedEvent) -> None:
        async with (await self._get_session()) as s:
            position = await s.get(Position, uuid.UUID(event.position_id))
            if not position:
                self._logger.warning(f"Position {event.position_id} not found")
                return

            error_message = event.error_message or "Unknown error occurred during position operation."
            position.message_error = error_message
            self._logger.error(f"Posición {event.position_id} falló ({event.position_type}): {error_message}")

            try:
                self._logger.debug(f"[on_failed] Position agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)
                return

        async with (await self._get_session()) as s:
            if event.position_type == "open":
                open_position = await s.get(OpenPosition, event.position_id)
                if not open_position:
                    self._logger.warning(f"Open position {event.position_id} not found")
                    return
                open_position.status = OpenPositionStatus.FAILED
                self._logger.debug(f"Open position {event.position_id} updated: status={OpenPositionStatus.FAILED}")
            elif event.position_type == "close":
                close_order = await s.get(CloseOrder, event.position_id)
                if not close_order:
                    self._logger.warning(f"Close order {event.position_id} not found")
                    return
                close_order.status = CloseOrderStatus.FAILED
                self._logger.debug(f"Close order {event.position_id} updated: status={CloseOrderStatus.FAILED}")

            try:
                self._logger.debug(f"[on_failed] Position agregada a la sesión. Commiteando en base de datos.")
                await s.commit()
            except Exception as e:
                self._logger.error(f"Error committing session: {e}", exc_info=True)
                return


def attach_position_events_subscriber(bus: PositionEventBus) -> None:
    subscriber = PositionEventsSubscriber()
    subscriber.attach(bus)
