# -*- coding: utf-8 -*-
"""
Adaptador: Servicio de caché en memoria.

Implementa ICacheService usando un diccionario en memoria.
"""
import hashlib
import logging
from typing import Optional, Dict

from ....domain.ports.cache_service import ICacheService
from ....domain.entities.backtest_statistics import BacktestStats

logger = logging.getLogger(__name__)


class MemoryCacheService(ICacheService):
    """
    Implementación de caché en memoria.
    
    Almacena resultados de backtest en un diccionario en memoria.
    Simple y eficiente para uso durante una sesión, pero se pierde al reiniciar.
    """

    def __init__(self):
        """
        Inicializa el servicio de caché en memoria.
        """
        self._cache: Dict[str, BacktestStats] = {}
        logger.debug("MemoryCacheService inicializado")

    def get(self, key: str) -> Optional[BacktestStats]:
        """
        Obtiene un resultado del caché.
        
        Args:
            key: Clave única que identifica el resultado
        
        Returns:
            BacktestStats si existe en caché, None en caso contrario
        """
        result = self._cache.get(key)
        if result:
            logger.debug(f"Resultado encontrado en caché (key: {key[:16]}...)")
        return result

    def set(self, key: str, value: BacktestStats) -> None:
        """
        Almacena un resultado en el caché.
        
        Args:
            key: Clave única que identifica el resultado
            value: Estadísticas del backtest a almacenar
        """
        self._cache[key] = value
        logger.debug(f"Resultado guardado en caché (key: {key[:16]}...)")

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
            String que identifica de manera única la configuración (hash SHA256)
        """
        cache_parts = []

        if validator_config:
            cache_parts.append(validator_config)
        else:
            cache_parts.append("no_validator")

        if start_date:
            cache_parts.append(f"start:{start_date}")
        if end_date:
            cache_parts.append(f"end:{end_date}")

        # Generar hash de la configuración completa
        combined_str = "|".join(cache_parts)
        cache_key = hashlib.sha256(combined_str.encode('utf-8')).hexdigest()

        return cache_key

    def clear(self) -> None:
        """
        Limpia todo el caché.
        
        Método adicional útil para testing o cuando se quiere resetear el caché.
        """
        self._cache.clear()
        logger.debug("Caché limpiado")

    def size(self) -> int:
        """
        Obtiene el número de elementos en el caché.
        
        Returns:
            Número de elementos almacenados
        """
        return len(self._cache)
