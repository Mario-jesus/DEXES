# -*- coding: utf-8 -*-
"""
Base para validaciones de dominio.

Define la clase base abstracta y tipos relacionados para crear
validaciones de transacciones durante el backtest.
"""
import logging
from typing import Dict, Any, List, TypedDict, Literal, Union, TYPE_CHECKING
from abc import ABC, abstractmethod

if TYPE_CHECKING:
    from ...entities.transactions import SwapTransaction
    from .validation_result import ValidationResult


# Tipo para validaciones: puede ser BaseValidation o un diccionario con grupo
class GroupValidationType(TypedDict):
    """Grupo de validaciones"""
    validations: List[Union['BaseValidation', 'GroupValidationType']]
    logical_operator: Literal['AND', 'OR']


ValidationItem = Union['BaseValidation', 'GroupValidationType']


class BaseValidation(ABC):
    """Clase base abstracta para validaciones de backtest"""

    def __init__(self, enabled: bool = True):
        """
        Args:
            enabled: Si True, la validación está activa
        """
        self.enabled = enabled
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._rejected_count: int = 0  # Contador de rechazos

    @abstractmethod
    def validate(self, transaction: 'SwapTransaction', context: Dict[str, Any]) -> 'ValidationResult':
        """
        Valida una transacción.
        
        Args:
            transaction: SwapTransaction a validar
            context: Contexto compartido entre validaciones (puede contener estado, config, etc.)
        
        Returns:
            ValidationResult con el resultado de la validación
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre de la validación"""
        pass

    def get_metrics(self) -> Dict[str, Any]:
        """
        Retorna las métricas de esta validación.
        
        Las subclases deben sobrescribir este método para agregar sus propias
        métricas personalizadas. Deben llamar a super().get_metrics() primero
        para obtener las métricas base.
        
        Returns:
            Diccionario con las métricas específicas de la validación.
            Debe incluir al menos 'enabled' y 'rejected_count'.
            Las subclases pueden agregar métricas adicionales.
        """
        return {
            'enabled': self.enabled,
            'rejected_count': self._rejected_count
        }

    def reset_metrics(self) -> None:
        """
        Reinicia los contadores de métricas.
        
        Las subclases deben sobrescribir este método si tienen contadores
        personalizados adicionales (además de _rejected_count).
        """
        self._rejected_count = 0

    def _record_rejection(self) -> None:
        """Registra un rechazo en las métricas"""
        self._rejected_count += 1
