# -*- coding: utf-8 -*-
"""
Puerto: Repositorio de transacciones.

Define la interfaz para acceder y obtener transacciones desde diferentes fuentes
(archivos, base de datos, APIs, etc.) sin acoplar el dominio a implementaciones concretas.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from ..entities.transactions import SwapTransaction


class ITransactionRepository(ABC):
    """
    Puerto para acceso a transacciones de swap.
    
    Define las operaciones necesarias para cargar y obtener transacciones
    sin importar la fuente de datos (archivo, base de datos, API, etc.).
    
    Los métodos de carga (load_from_file, load_from_data, load_from_database) son
    opcionales: cada implementación puede implementar solo los que necesita.
    Los métodos no implementados lanzan NotImplementedError por defecto.
    """

    def load_from_file(self, file_path: str) -> None:
        """
        Carga transacciones desde un archivo.
        
        Implementación por defecto: lanza NotImplementedError.
        Sobrescribir en implementaciones que soporten carga desde archivos.
        
        Args:
            file_path: Ruta del archivo a cargar
        
        Raises:
            NotImplementedError: Si el repositorio no soporta carga desde archivos
            FileNotFoundError: Si el archivo no existe
            ValueError: Si el formato es inválido o la fuente no está soportada
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} no soporta carga desde archivos. "
            f"Usa load_from_data() o load_from_database() según corresponda."
        )

    def load_from_data(self, data: List[Dict[str, Any]]) -> None:
        """
        Carga transacciones desde datos en memoria.
        
        Implementación por defecto: lanza NotImplementedError.
        Sobrescribir en implementaciones que soporten carga desde memoria.
        
        Args:
            data: Lista de diccionarios con datos de transacciones.
                    Puede ser lista de páginas o lista de transacciones directamente.
        
        Raises:
            NotImplementedError: Si el repositorio no soporta carga desde memoria
            ValueError: Si el formato es inválido o la fuente no está soportada
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} no soporta carga desde memoria. "
            f"Usa load_from_file() o load_from_database() según corresponda."
        )

    def load_from_database(
        self,
        system_wallet_address: str,
        trader_wallet: str,
        run_id: Optional[Any] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        include_liquidations: bool = False,
        limit: Optional[int] = None,
        **kwargs
    ) -> None:
        """
        Carga transacciones desde una base de datos.
        
        Implementación por defecto: lanza NotImplementedError.
        Sobrescribir en implementaciones que soporten carga desde bases de datos.
        
        Args:
            system_wallet_address: Dirección de wallet del sistema
            trader_wallet: Wallet address del trader
            run_id: ID del run a usar (opcional)
            start_date: Fecha de inicio del rango (opcional)
            end_date: Fecha de fin del rango (opcional)
            include_liquidations: Si True, incluye posiciones de liquidación (por defecto False)
            limit: Límite de registros a cargar (opcional)
            **kwargs: Parámetros adicionales para el loader específico
        
        Raises:
            NotImplementedError: Si el repositorio no soporta carga desde base de datos
            ValueError: Si la fuente no está soportada
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} no soporta carga desde base de datos. "
            f"Usa load_from_file() o load_from_data() según corresponda."
        )

    @abstractmethod
    def get_all(self) -> List['SwapTransaction']:
        """
        Obtiene todas las transacciones cargadas.
        
        Returns:
            Lista de SwapTransaction
        """
        pass

    @abstractmethod
    def filter_by_date_range(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime]
    ) -> List['SwapTransaction']:
        """
        Filtra transacciones por rango de fechas.
        
        Args:
            start_date: Fecha de inicio (inclusive). Si es None, no filtra por inicio
            end_date: Fecha de fin (inclusive). Si es None, no filtra por fin
        
        Returns:
            Lista de SwapTransaction filtradas
        """
        pass
