# -*- coding: utf-8 -*-
"""
Modelos de validaciones.

Contiene los modelos de validaciones para el dominio.
"""

from .base_validation import BaseValidation, ValidationItem
from .validation_result import ValidationResult

__all__ = [
    'BaseValidation',
    'ValidationItem',
    'ValidationResult',
]
