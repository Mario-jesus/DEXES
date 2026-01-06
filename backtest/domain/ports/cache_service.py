# -*- coding: utf-8 -*-
"""
Puerto: Servicio de caché.

Define la interfaz para almacenar y recuperar resultados de backtest en caché,
permitiendo evitar recálculos costosos cuando se ejecutan los mismos parámetros.
"""
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..entities import BacktestStats


class ICacheService(ABC):
    """
    Puerto para servicio de caché de resultados de backtest.
    
    Define las operaciones necesarias para almacenar y recuperar
    resultados cacheados sin acoplar a una implementación específica
    (memoria, Redis, archivo, etc.).
    """

    @abstractmethod
    def get(self, key: str) -> Optional['BacktestStats']:
        """
        Obtiene un resultado del caché.
        
        Args:
            key: Clave única que identifica el resultado
        
        Returns:
            BacktestStats si existe en caché, None en caso contrario
        """
        pass

    @abstractmethod
    def set(self, key: str, value: 'BacktestStats') -> None:
        """
        Almacena un resultado en el caché.
        
        Args:
            key: Clave única que identifica el resultado
            value: Estadísticas del backtest a almacenar
        """
        pass

    @abstractmethod
    def generate_key(
        self,
        validator_config: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str]
    ) -> str:
        """
        Genera una clave única para el caché basada en la configuración.
        
        Args:
            validator_config: Configuración serializada del validador (opcional)
            start_date: Fecha de inicio en formato ISO string (opcional)
            end_date: Fecha de fin en formato ISO string (opcional)
        
        Returns:
            String que identifica de manera única la configuración
        """
        pass
