# -*- coding: utf-8 -*-
"""
Container: Composition Root para inyección de dependencias.

Este módulo es responsable de:
- Instanciar todas las implementaciones concretas (adaptadores)
- Conectar servicios de dominio
- Crear casos de uso con sus dependencias
- Proporcionar una interfaz centralizada para obtener servicios configurados

Para proyectos pequeños/medianos, un container manual es simple y suficiente.
Si el proyecto crece, se puede migrar a una librería como 'dependency-injector'.
"""
import logging
import os
from typing import Optional, Literal, Dict, cast

from ...domain.ports.transaction_repository import ITransactionRepository
from ...domain.ports.cache_service import ICacheService
from ...domain.services.fifo_matcher import FIFOMatcher
from ...domain.services.metrics_calculator import MetricsCalculator
from ...application.use_cases.backtest_runner import BacktestRunner
from ...application.use_cases.backtest_optimizer import BacktestOptimizer
from ...application.use_cases.backtest_comparator import BacktestComparator

from ..adapters.repositories import (
    MoralisTransactionRepository,
    PumpPortalTransactionRepository,
    SystemTransactionRepository
)
from ..adapters.cache.memory_cache_service import MemoryCacheService

logger = logging.getLogger(__name__)


class Container:
    """
    Container de dependencias (Composition Root).
    
    Centraliza la creación y configuración de todas las dependencias de la aplicación.
    Proporciona métodos factory para obtener instancias configuradas de servicios.
    """

    def __init__(self):
        """Inicializa el container."""
        # Diccionario para mantener múltiples repositorios por tipo
        self._repositories: Dict[str, ITransactionRepository] = {}
        # Servicios compartidos (stateless)
        self._metrics_calculator: Optional[MetricsCalculator] = None
        # Diccionario para mantener múltiples cache_services por tipo de repositorio
        # Cada runner necesita su propio cache para evitar conflictos de claves
        self._cache_services: Dict[str, ICacheService] = {}
        # Diccionario para mantener múltiples fifo_matchers por tipo de repositorio
        # Cada runner necesita su propio matcher para evitar conflictos de estado
        self._fifo_matchers: Dict[str, FIFOMatcher] = {}
        # Diccionario para mantener múltiples runners por tipo de repositorio
        self._backtest_runners: Dict[str, BacktestRunner] = {}
        # Diccionario para mantener múltiples optimizers por tipo de repositorio
        self._backtest_optimizers: Dict[str, BacktestOptimizer] = {}
        self._backtest_comparator: Optional[BacktestComparator] = None

    def get_repository(self, source: str = 'moralis') -> ITransactionRepository:
        """
        Obtiene un repositorio configurado según la fuente especificada.
        
        Cada tipo de repositorio se mantiene en un diccionario separado,
        permitiendo tener múltiples repositorios activos simultáneamente.
        
        Args:
            source: Tipo de repositorio ('moralis', 'pumpportal', 'system')
        
        Returns:
            Instancia configurada de ITransactionRepository
        
        Raises:
            ValueError: Si la fuente no está soportada
        """
        source_lower = source.lower()

        # Si ya existe el repositorio de este tipo, retornarlo
        if source_lower in self._repositories:
            return self._repositories[source_lower]

        # Crear nuevo repositorio según el tipo
        if source_lower == 'moralis':
            repository = MoralisTransactionRepository()
            logger.debug("Repositorio Moralis creado")

        elif source_lower == 'pumpportal':
            # Usar variables de entorno para la conexión
            connection_string = self._get_postgres_connection_string()
            repository = PumpPortalTransactionRepository(connection_string=connection_string)
            logger.debug("Repositorio PumpPortal creado")

        elif source_lower == 'system':
            # Usar variables de entorno para la conexión
            connection_string = self._get_postgres_connection_string()
            repository = SystemTransactionRepository(connection_string=connection_string)
            logger.debug("Repositorio System creado")

        else:
            available = ['moralis', 'pumpportal', 'system']
            raise ValueError(
                f"Fuente de repositorio no soportada: {source}. "
                f"Fuentes disponibles: {available}"
            )

        # Guardar en el diccionario
        self._repositories[source_lower] = repository
        return repository

    def get_cache_service(self, repository_source: Optional[str] = None) -> ICacheService:
        """
        Obtiene el servicio de caché configurado.
        
        Si se proporciona repository_source, retorna un cache específico para ese tipo
        de repositorio. Esto evita conflictos cuando múltiples runners con los mismos
        parámetros generan la misma clave de caché.
        
        Args:
            repository_source: Tipo de repositorio ('moralis', 'pumpportal', 'system')
                                Si es None, retorna un cache compartido (legacy)
        
        Returns:
            Instancia configurada de ICacheService
        """
        if repository_source is None:
            # Modo legacy: retornar un cache compartido
            # Esto se mantiene para compatibilidad con código existente
            if 'shared' not in self._cache_services:
                self._cache_services['shared'] = MemoryCacheService()
                logger.debug("Servicio de caché compartido creado")
            return self._cache_services['shared']

        repository_source_lower = repository_source.lower()

        # Si ya existe un cache para este tipo de repositorio, retornarlo
        if repository_source_lower in self._cache_services:
            return self._cache_services[repository_source_lower]

        # Crear nuevo cache para este tipo de repositorio
        cache_service = MemoryCacheService()
        self._cache_services[repository_source_lower] = cache_service
        logger.debug(f"Servicio de caché creado para repositorio: {repository_source_lower}")
        return cache_service

    def get_fifo_matcher(self, repository_source: Optional[str] = None) -> FIFOMatcher:
        """
        Obtiene el servicio de matching FIFO.
        
        Si se proporciona repository_source, retorna un matcher específico para ese tipo
        de repositorio. Esto evita conflictos cuando múltiples runners se ejecutan
        simultáneamente o secuencialmente.
        
        Args:
            repository_source: Tipo de repositorio ('moralis', 'pumpportal', 'system')
                                Si es None, retorna un matcher compartido (legacy)
        
        Returns:
            Instancia de FIFOMatcher
        """
        if repository_source is None:
            # Modo legacy: retornar un matcher compartido
            # Esto se mantiene para compatibilidad con código existente
            if 'shared' not in self._fifo_matchers:
                self._fifo_matchers['shared'] = FIFOMatcher()
                logger.debug("FIFO Matcher compartido creado")
            return self._fifo_matchers['shared']

        repository_source_lower = repository_source.lower()

        # Si ya existe un matcher para este tipo de repositorio, retornarlo
        if repository_source_lower in self._fifo_matchers:
            return self._fifo_matchers[repository_source_lower]

        # Crear nuevo matcher para este tipo de repositorio
        matcher = FIFOMatcher()
        self._fifo_matchers[repository_source_lower] = matcher
        logger.debug(f"FIFO Matcher creado para repositorio: {repository_source_lower}")
        return matcher

    def get_metrics_calculator(self) -> MetricsCalculator:
        """
        Obtiene el calculador de métricas.
        
        Returns:
            Instancia de MetricsCalculator
        """
        if self._metrics_calculator is None:
            self._metrics_calculator = MetricsCalculator()
            logger.debug("Metrics Calculator creado")
        return self._metrics_calculator

    def get_backtest_runner(self, repository_source: Literal['moralis', 'pumpportal', 'system'] = 'moralis') -> BacktestRunner:
        """
        Obtiene el caso de uso BacktestRunner con todas sus dependencias inyectadas.
        
        Cada tipo de repositorio tiene su propio runner asociado con su propio
        FIFOMatcher, permitiendo tener múltiples runners activos simultáneamente
        sin conflictos de estado.
        
        Args:
            repository_source: Tipo de repositorio a usar ('moralis', 'pumpportal', 'system')
        
        Returns:
            Instancia configurada de BacktestRunner
        """
        repository_source_lower = repository_source.lower()
        repository = self.get_repository(repository_source_lower)
        # Cada runner tiene su propio CacheService y FIFOMatcher para evitar conflictos
        cache_service = self.get_cache_service(repository_source_lower)
        fifo_matcher = self.get_fifo_matcher(repository_source_lower)
        metrics_calculator = self.get_metrics_calculator()

        # Si ya existe un runner para este tipo de repositorio, verificar que use el mismo repositorio
        if repository_source_lower in self._backtest_runners:
            existing_runner = self._backtest_runners[repository_source_lower]
            # Si el repositorio cambió (aunque no debería), recrear el runner
            if existing_runner.repository is not repository:
                logger.warning(
                    f"Repositorio cambió para {repository_source_lower}, recreando BacktestRunner"
                )
                self._backtest_runners[repository_source_lower] = BacktestRunner(
                    repository=repository,
                    cache_service=cache_service,
                    fifo_matcher=fifo_matcher,
                    metrics_calculator=metrics_calculator
                )
            return self._backtest_runners[repository_source_lower]

        # Crear nuevo runner para este tipo de repositorio
        runner = BacktestRunner(
            repository=repository,
            cache_service=cache_service,
            fifo_matcher=fifo_matcher,
            metrics_calculator=metrics_calculator
        )
        self._backtest_runners[repository_source_lower] = runner
        logger.debug(f"BacktestRunner creado con repositorio: {repository_source_lower}")

        return runner

    def get_backtest_optimizer(self, repository_source: Literal['moralis', 'pumpportal', 'system'] = 'moralis') -> BacktestOptimizer:
        """
        Obtiene el caso de uso BacktestOptimizer con BacktestRunner inyectado.
        
        Cada tipo de repositorio tiene su propio optimizer asociado, permitiendo
        tener múltiples optimizers activos simultáneamente.
        
        Args:
            repository_source: Tipo de repositorio a usar ('moralis', 'pumpportal', 'system')
        
        Returns:
            Instancia configurada de BacktestOptimizer
        """
        repository_source_lower = repository_source.lower()
        # Cast explícito para satisfacer el tipo Literal
        runner = self.get_backtest_runner(cast(Literal['moralis', 'pumpportal', 'system'], repository_source_lower))

        # Si ya existe un optimizer para este tipo de repositorio, verificar que use el mismo runner
        if repository_source_lower in self._backtest_optimizers:
            existing_optimizer = self._backtest_optimizers[repository_source_lower]
            # Si el runner cambió, recrear el optimizer
            if existing_optimizer.backtest_runner is not runner:
                logger.warning(
                    f"BacktestRunner cambió para {repository_source_lower}, recreando BacktestOptimizer"
                )
                self._backtest_optimizers[repository_source_lower] = BacktestOptimizer(backtest_runner=runner)
            return self._backtest_optimizers[repository_source_lower]

        # Crear nuevo optimizer para este tipo de repositorio
        optimizer = BacktestOptimizer(backtest_runner=runner)
        self._backtest_optimizers[repository_source_lower] = optimizer
        logger.debug(f"BacktestOptimizer creado con BacktestRunner para repositorio: {repository_source_lower}")
        return optimizer

    def get_backtest_comparator(self) -> BacktestComparator:
        """
        Obtiene el caso de uso BacktestComparator con todas sus dependencias inyectadas.
        
        Returns:
            Instancia configurada de BacktestComparator
        """
        metrics_calculator = self.get_metrics_calculator()
        if self._backtest_comparator is None:
            self._backtest_comparator = BacktestComparator(metrics_calculator=metrics_calculator)
            logger.debug("BacktestComparator creado")
        return self._backtest_comparator

    def _get_postgres_connection_string(self) -> Optional[str]:
        """
        Obtiene el string de conexión PostgreSQL desde variables de entorno.
        
        Returns:
            String de conexión o None si no está configurado
        """
        user = os.getenv("BACKTEST_PGUSER", "postgres")
        password = os.getenv("BACKTEST_PGPASSWORD", "")
        host = os.getenv("BACKTEST_PGHOST", "localhost")
        port = os.getenv("BACKTEST_PGPORT", "5432")
        database = os.getenv("BACKTEST_PGDATABASE", "postgres")

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    def reset(self) -> None:
        """
        Resetea todas las instancias del container.
        
        Útil para testing o cuando se necesita recrear las dependencias.
        """
        self._repositories.clear()
        self._cache_services.clear()
        self._fifo_matchers.clear()
        self._metrics_calculator = None
        self._backtest_runners.clear()
        self._backtest_optimizers.clear()
        self._backtest_comparator = None
        logger.debug("Container reseteado")
