# -*- coding: utf-8 -*-
"""
Objeto de Valor: Resultado de validación.

Representa el resultado de validar una transacción dentro del sistema de validaciones
del dominio. Es parte del modelo de dominio del sistema de validaciones.
"""
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class ValidationResult:
    """
    Resultado de una validación de transacción.
    
    Representa el resultado de validar una transacción, indicando si fue aceptada
    o rechazada y proporcionando detalles adicionales.
    
    Este es un objeto de valor (Value Object) del dominio que forma parte del
    sistema de validaciones. No es un DTO ya que se usa internamente dentro del
    dominio, no para transferir datos desde/hacia capas externas.
    """
    is_valid: bool
    """Si True, la transacción pasó la validación; si False, fue rechazada"""

    validation_name: str
    """Nombre de la validación que generó este resultado"""

    message: str = ""
    """Mensaje descriptivo del resultado"""

    details: Dict[str, Any] = field(default_factory=dict)
    """Detalles adicionales del resultado de la validación (puede incluir códigos, valores, etc.)"""
