# -*- coding: utf-8 -*-
from logging import getLogger

from copy_trading.events import PositionEventBus, MintMetadataUpdatedEvent
from ..repositories.trader_mint_repository import TraderMintRepository

_logger = getLogger(__name__)

def attach_mint_events_subscriber(bus: PositionEventBus) -> None:
    bus.on_mint_metadata_updated(_on_mint_metadata_updated)


async def _on_mint_metadata_updated(event: MintMetadataUpdatedEvent) -> None:
    try:
        repo = TraderMintRepository()
        await repo.add_mint_to_run(
            run_id=event.run_id,
            mint_address=event.mint_address,
            name=event.name if event.name else None,
            symbol=event.symbol if event.symbol else None,
        )
        _logger.debug(
            f"Mint metadata added to run: {event.mint_address} name={event.name!r} symbol={event.symbol!r}"
        )
    except Exception as e:
        _logger.error(f"Error adding mint metadata to run {event.run_id} for {event.mint_address}: {e}")
