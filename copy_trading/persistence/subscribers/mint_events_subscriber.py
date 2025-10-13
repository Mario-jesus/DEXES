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
        await repo.upsert_mint(
            mint_address=event.mint_address,
            name=event.name,
            symbol=event.symbol,
        )
        _logger.debug(
            f"Mint metadata upserted: {event.mint_address} name={event.name!r} symbol={event.symbol!r}"
        )
    except Exception as e:
        _logger.error(f"Error upsert mint metadata for {event.mint_address}: {e}")
