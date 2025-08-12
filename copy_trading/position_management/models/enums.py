# -*- coding: utf-8 -*-
"""
Enumerados para los modelos de posiciones de trading.
"""
from enum import Enum


class PositionStatus(Enum):
    """Estado de la posición"""
    PENDING = "pending"                     # En cola esperando ejecución
    OPEN = "open"                           # Abierta y activa
    PARTIALLY_CLOSED = "partially_closed"   # Parcialmente cerrada
    CLOSED = "closed"                       # Cerrada correctamente
    FAILED = "failed"                       # Falló la ejecución


class ClosePositionStatus(Enum):
    """Estado de un cierre de posición"""
    PENDING = "pending"                     # En cola esperando ejecución
    PARTIAL = "partial"                     # Cerrada parcialmente
    SUCCESS = "success"                     # Cerrada correctamente
    FAILED = "failed"                       # Falló la ejecución
