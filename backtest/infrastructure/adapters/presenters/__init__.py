# -*- coding: utf-8 -*-
"""
Adaptadores de presentación.

Contiene presentadores que formatean y muestran datos del dominio/aplicación
en diferentes formatos (consola, reportes, etc.).
"""

from .console_stats_presenter import show_stats
from .optimizer_results_presenter import show_optimizer_results
from .comparison_presenter import show_comparison
from .losing_trades_comparison_presenter import show_losing_trades_comparison

__all__ = [
    'show_stats',
    'show_optimizer_results',
    'show_comparison',
    'show_losing_trades_comparison',
]
