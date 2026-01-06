# -*- coding: utf-8 -*-
"""
Puertos (interfaces) del dominio.

Los puertos definen las operaciones que el dominio necesita del mundo exterior,
sin especificar cómo se implementan. Las implementaciones concretas (adaptadores)
estarán en la capa de infraestructura.
"""

from .transaction_repository import ITransactionRepository
from .cache_service import ICacheService

__all__ = [
    'ITransactionRepository',
    'ICacheService',
]
