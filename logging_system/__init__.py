# -*- coding: utf-8 -*-
"""
Módulo de inicialización para el sistema de logging.
"""
from .logger_config import setup_logging
from .custom_logger import AppLogger

__all__ = [
    "setup_logging",
    "AppLogger"
]