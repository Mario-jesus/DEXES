# -*- coding: utf-8 -*-
"""
Caso de uso: Optimización de parámetros de backtest.

Orquesta múltiples ejecuciones de backtest con diferentes parámetros y validadores
para encontrar la configuración óptima de filtros y estrategias.
"""
import logging
from typing import List, Tuple, Dict, Optional, Any, Callable, Literal
from datetime import datetime, timezone

from ...domain.entities.backtest_statistics import BacktestStats
from ...domain.services.backtest_validator import BacktestValidator
from ...domain.services.exchange_registry import get_internal_name_by_address
from ..types.optimizer_types import BacktestDataEntry, PoolData, ParameterSearchConfig
from .backtest_runner import BacktestRunner

logger = logging.getLogger(__name__)


def _parse_date(date_value: Optional[Any]) -> Optional[datetime]:
    """
    Convierte un valor de fecha a datetime object con timezone UTC.
    
    Args:
        date_value: Puede ser string ("YYYY-MM-DD" o ISO 8601) o datetime object
    
    Returns:
        datetime object con timezone UTC, o None si date_value es None
    """
    if date_value is None:
        return None

    if isinstance(date_value, datetime):
        # Si ya es datetime, asegurar timezone UTC
        if date_value.tzinfo is None:
            return date_value.replace(tzinfo=timezone.utc)
        return date_value.astimezone(timezone.utc)

    if isinstance(date_value, str):
        # Intentar parsear como ISO 8601
        try:
            # Reemplazar Z por +00:00 para compatibilidad
            iso_str = date_value.replace('Z', '+00:00')
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                # Si no tiene timezone, agregar UTC
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except ValueError:
            # Intentar como fecha simple "YYYY-MM-DD"
            try:
                dt = datetime.strptime(date_value, "%Y-%m-%d")
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                raise ValueError(f"Formato de fecha inválido: {date_value}")

    raise ValueError(f"Tipo de fecha no soportado: {type(date_value)}")


class BacktestOptimizer:
    """
    Caso de uso: Optimización de parámetros de backtest.
    
    Orquesta múltiples ejecuciones de backtest con diferentes parámetros y validadores
    para encontrar la configuración óptima de filtros y estrategias.
    
    El repositorio debe estar cargado antes de usar este caso de uso.
    La carga de datos es responsabilidad del cliente o de otro caso de uso.
    """

    def __init__(self, backtest_runner: BacktestRunner):
        """
        Inicializa el optimizador de backtest.
        
        Args:
            backtest_runner: Instancia de BacktestRunner para ejecutar los backtests
        """
        self.backtest_runner = backtest_runner
        logger.debug("BacktestOptimizer inicializado")

    def search_parameters(
        self,
        filter_type: str,
        params_to_process: List[Dict[str, Any]],
        date_range: Optional[List[Tuple[str, str]]] = None,
        *,
        build_validator: Callable[[Dict[str, Any]], BacktestValidator]
    ) -> List[BacktestDataEntry]:
        """
        Ejecuta múltiples backtests iterando sobre diferentes parámetros y rangos de fechas.

        Args:
            filter_type: Identificador del tipo de filtro/estrategia que se está evaluando.
            params_to_process: Lista de diccionarios con parámetros para construir validadores.
            date_range: Lista opcional de tuplas (start_date, end_date) con rangos de fechas.
            build_validator: Función que recibe un diccionario de parámetros y retorna un BacktestValidator.

        Returns:
            Lista de BacktestDataEntry con los resultados de cada backtest ejecutado.
        """
        data: List[BacktestDataEntry] = []
        for params in params_to_process:
            if date_range is None:
                validator = build_validator(params)
                stats = self.backtest_runner.run(validator=validator)
                data.append(self._build_data_entry(
                    stats=stats,
                    filter_type=filter_type,
                    filter_params=params,
                    start_date=None,
                    end_date=None
                ))
                continue

            for start_date_str, end_date_str in date_range:
                validator = build_validator(params)
                # Convertir strings a datetime para el runner
                start_dt = _parse_date(start_date_str)
                end_dt = _parse_date(end_date_str)
                stats = self.backtest_runner.run(
                    validator=validator,
                    start_date=start_dt,
                    end_date=end_dt
                )
                data.append(self._build_data_entry(
                    stats=stats,
                    filter_type=filter_type,
                    filter_params=params,
                    start_date=start_date_str,
                    end_date=end_date_str
                ))

        return data

    def search_from_configs(
        self,
        configs: List[ParameterSearchConfig],
        date_range: Optional[List[Tuple[str, str]]] = None
    ) -> List[BacktestDataEntry]:
        """
        Ejecuta múltiples búsquedas de parámetros usando configuraciones estructuradas.

        Esta es una versión alternativa de `search_parameters` que acepta múltiples
        configuraciones de búsqueda en una lista. Ejecuta una búsqueda para cada
        configuración y retorna todos los resultados combinados.

        Args:
            configs: Lista de configuraciones de búsqueda. Cada configuración contiene
                filter_type, filter_params y build_validator.
            date_range: Lista opcional de tuplas (start_date, end_date) con rangos de fechas.
                Si se proporciona, se aplica a todas las búsquedas ejecutadas.

        Returns:
            Lista de BacktestDataEntry con los resultados de todas las búsquedas ejecutadas,
            combinados en una sola lista.
        """
        data = []
        for search_config in configs:
            data.extend(self.search_parameters(
                filter_type=search_config["filter_type"],
                params_to_process=search_config["filter_params"],
                date_range=date_range,
                build_validator=search_config["build_validator"]
            ))
        return data

    @staticmethod
    def data_sorted_by_key(data: List[BacktestDataEntry], key: str, reverse: bool = True) -> List[BacktestDataEntry]:
        """
        Ordena la lista de datos de backtest por una clave específica.

        Args:
            data: Lista de datos de backtest.
            key: Clave por la cual se ordenará la lista.
            reverse: Si True, se ordenará de forma descendente. Si False, se ordenará de forma ascendente.

        Returns:
            Lista de datos de backtest ordenada.
        """
        filtered_data = list(filter(lambda backtest_data: key in backtest_data, data))
        return sorted(filtered_data, key=lambda backtest_data: backtest_data[key], reverse=reverse)  # type: ignore

    @staticmethod
    def data_sorted_by_pool_key(
        data: List[BacktestDataEntry],
        pool_name: Literal["pump_fun", "pump_swap"],
        key_in_pool: str,
        reverse: bool = True
    ) -> List[BacktestDataEntry]:
        """
        Ordena la lista de datos de backtest por una clave específica de un pool.

        Args:
            data: Lista de datos de backtest.
            pool_name: Nombre del pool/exchange.
            key_in_pool: Clave por la cual se ordenará la lista.
            reverse: Si True, se ordenará de forma descendente. Si False, se ordenará de forma ascendente.

        Returns:
            Lista de datos de backtest ordenada.
        """
        filtered_data = list(filter(lambda backtest_data: pool_name in backtest_data and backtest_data[pool_name], data))  # type: ignore
        return sorted(filtered_data, key=lambda backtest_data: backtest_data[pool_name][key_in_pool], reverse=reverse)  # type: ignore

    @staticmethod
    def _build_data_entry(
        stats: Optional[BacktestStats],
        filter_type: str,
        filter_params: Dict[str, Any],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> BacktestDataEntry:
        """
        Construye un registro de datos de backtest.
        """
        if stats is None:
            return BacktestDataEntry(
                filter_type=filter_type,
                filter_params=filter_params,
                has_available_data=False,
                date_start=start_date,
                date_end=end_date
            )
        data = BacktestDataEntry(
            filter_type=filter_type,
            filter_params=filter_params,
            has_available_data=True,
            date_start=start_date,
            date_end=end_date,
            total_trades=stats.total_trades,
            total_sol_invested=stats.total_sol_invested,
            total_sol_recovered=stats.total_sol_recovered,
            net_profit_sol=stats.net_profit_sol,
            win_rate=stats.win_rate,
            roi=stats.roi,
            profit_factor=stats.profit_factor,
            gain_expectancy=stats.gain_expectancy,
            gain_expectancy_adjusted=stats.gain_expectancy_adjusted,
            sharpe_ratio=stats.sharpe_ratio,
            sortino_ratio=stats.sortino_ratio
        )
        # Buscar pools por nombre interno usando direcciones
        # pool_stats ahora usa exchange_address como clave, necesitamos buscar por nombre interno
        for exchange_address_key, pool_stat in stats.pool_stats.items():
            internal_name = pool_stat.exchange_name or get_internal_name_by_address(exchange_address_key)

            if internal_name == "pump_fun":
                data["pump_fun"] = PoolData(
                    total_trades=pool_stat.total_trades,
                    total_sol_invested=pool_stat.total_sol_invested,
                    total_sol_recovered=pool_stat.total_sol_recovered,
                    net_profit_sol=pool_stat.net_profit_sol,
                    win_rate=pool_stat.win_rate,
                    roi=pool_stat.roi,
                    profit_factor=pool_stat.profit_factor,
                    gain_expectancy=pool_stat.gain_expectancy,
                    gain_expectancy_adjusted=pool_stat.gain_expectancy_adjusted,
                    sharpe_ratio=pool_stat.sharpe_ratio,
                    sortino_ratio=pool_stat.sortino_ratio,
                )
            elif internal_name == "pump_swap":
                data["pump_swap"] = PoolData(
                    total_trades=pool_stat.total_trades,
                    total_sol_invested=pool_stat.total_sol_invested,
                    total_sol_recovered=pool_stat.total_sol_recovered,
                    net_profit_sol=pool_stat.net_profit_sol,
                    win_rate=pool_stat.win_rate,
                    roi=pool_stat.roi,
                    profit_factor=pool_stat.profit_factor,
                    gain_expectancy=pool_stat.gain_expectancy,
                    gain_expectancy_adjusted=pool_stat.gain_expectancy_adjusted,
                    sharpe_ratio=pool_stat.sharpe_ratio,
                    sortino_ratio=pool_stat.sortino_ratio,
                )
        return data
