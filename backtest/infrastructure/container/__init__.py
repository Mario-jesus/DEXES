# -*- coding: utf-8 -*-
"""
Container: Composition Root.

Configura y orquesta todas las dependencias de la aplicación.
Este es el único lugar donde se instancian las implementaciones concretas
y se conectan con las interfaces del dominio.
"""

from .container import Container

__all__ = [
    'Container',
]
