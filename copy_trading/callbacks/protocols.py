# -*- coding: utf-8 -*-
"""
Protocolos para callbacks del sistema (mínimo balance, etc.).
"""
from __future__ import annotations

from typing import Protocol, Dict, Any


class MinimumBalanceHandlerProtocol(Protocol):
    """
    Interfaz para handlers de balance mínimo.
    Debe ser invocable como callback asíncrono.
    """

    async def __call__(self, error_data: Dict[str, Any]) -> bool:  # noqa: D401
        ...

    async def get_stats(self) -> Dict[str, Any]:
        ...
