"""
BitQuery Temp - Módulo Simplificado y Optimizado (Asíncrono)

Solo contiene lo esencial que se usa en los notebooks:
- Cliente HTTP asíncrono para consultas  
- Cliente WebSocket para tiempo real
- Queries centralizadas
- Funciones de análisis

Completamente asíncrono para mejor rendimiento.
"""

from .http_client import BitQueryHTTPClient
from .websocket_client import BitQueryWebSocketClient
from .queries import BitQueryQueries, BitQuerySubscriptions
from .analysis import (
    filter_and_calculate_pnl_corrected,
    display_trader_analysis,
    display_pumpfun_traders,
    analyze_trader_summary,
    analyze_token_summary,
    custom_trader_callback,
    pumpfun_callback
)

__version__ = "1.0.0"
__author__ = "Mario Jesús Arias Hernández"

# Exportaciones principales - solo lo que se usa en notebooks
__all__ = [
    # Clientes
    "BitQueryHTTPClient",
    "BitQueryWebSocketClient",

    # Queries
    "BitQueryQueries", 
    "BitQuerySubscriptions",

    # Funciones de análisis
    "filter_and_calculate_pnl_corrected",
    "display_trader_analysis", 
    "display_pumpfun_traders",
    "analyze_trader_summary",
    "analyze_token_summary",

    # Callbacks
    "custom_trader_callback",
    "pumpfun_callback"
]
