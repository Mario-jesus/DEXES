# -*- coding: utf-8 -*-
"""
Módulo de inicialización para el sistema de logging.
"""
from .logger_config import (
    setup_logging, 
    get_logger,
    setup_logfire_global,
    add_logfire_to_logger,
    remove_logfire_from_logger,
    get_logfire_instance,
    is_logfire_globally_enabled
)
from .custom_logger import AppLogger

__all__ = [
    "setup_logging",
    "get_logger",
    "setup_logfire_global",
    "add_logfire_to_logger", 
    "remove_logfire_from_logger",
    "get_logfire_instance",
    "is_logfire_globally_enabled",
    "AppLogger"
]