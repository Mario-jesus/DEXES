# -*- coding: utf-8 -*-
"""
Módulo de suscriptores de eventos de posiciones y mints
"""

from .position_events_subscriber import attach_position_events_subscriber
from .mint_events_subscriber import attach_mint_events_subscriber

__all__ = [
    "attach_position_events_subscriber",
    "attach_mint_events_subscriber",
]
