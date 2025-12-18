# -*- coding: utf-8 -*-
"""
Monitor para procesar datos de trading y generar métricas para todos los sistemas.
"""
import uuid
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
from collections import defaultdict

from logging_system import AppLogger

from .data_reader import TradingDataReader
from .metrics_calculator import TradingMetricsCalculator
from ..persistence.repositories import (
    TradingMetricsRepository,
    RunRepository,
    CopyTradingBotRepository,
)
from ..data_management.solana_manager import SolanaTxAnalyzer


class SystemMonitor:
    """Monitor individual para un sistema específico."""

    def __init__(
        self,
        system_wallet_address: str,
        runs_id: uuid.UUID,
        execution_mode: str,
        data_reader: TradingDataReader,
        metrics_repository: TradingMetricsRepository,
        solana_manager: SolanaTxAnalyzer,
    ):
        self.system_wallet_address = system_wallet_address
        self.runs_id = runs_id
        self.execution_mode = execution_mode
        self.data_reader = data_reader
        self.metrics_repository = metrics_repository
        self.metrics_calculator = TradingMetricsCalculator()
        self._logger = AppLogger(f"{self.__class__.__name__}[{system_wallet_address[:8]}]")
        self.solana_manager = solana_manager

    async def initialize(self) -> None:
        """Inicializa el monitor del sistema."""
        # Obtener capital inicial del run
        initial_capital = await self.data_reader.get_initial_capital(self.runs_id)
        if initial_capital:
            self.metrics_calculator.set_initial_capital(initial_capital)
            self._logger.debug(f"Capital inicial: {initial_capital} SOL")
        else:
            self._logger.warning(f"Capital inicial no encontrado para run {self.runs_id}")

        # Obtener última métrica guardada para lectura incremental
        last_metric = await self.metrics_repository.get_latest_metric(
            system_name=self.system_wallet_address,
            metric_name="PNL_Total_Cumulative",
            execution_mode=self.execution_mode,
        )

        if last_metric:
            self.metrics_calculator.last_pnl_timestamp = last_metric.timestamp
            self._logger.debug(
                f"Última métrica encontrada: {last_metric.timestamp}, "
                f"continuando desde ahí"
            )

    async def process_cycle(self) -> List[Dict[str, Any]]:
        """
        Procesa un ciclo de monitoreo para este sistema.

        Returns:
            Lista de métricas generadas
        """
        metrics_to_write = []

        # Leer datos acumulados de PnL por trader
        pnl_data = await self.data_reader.get_pnl_realized_traders(
            self.runs_id,
        )

        # Obtener balance SOL on-chain de la wallet del sistema
        current_capital_onchain: Optional[Decimal] = None
        try:
            sol_balance_str = await self.solana_manager.get_sol_balance(self.system_wallet_address)
            current_capital_onchain = Decimal(sol_balance_str)
            self._logger.debug(
                f"Balance on-chain obtenido para {self.system_wallet_address[:8]}...: {current_capital_onchain} SOL"
            )
        except Exception as e:
            self._logger.warning(
                f"Error obteniendo balance on-chain para {self.system_wallet_address[:8]}...: {e}"
            )

        # Procesar PnL y generar métricas (comparando con valores anteriores)
        if pnl_data:
            current_timestamp = datetime.now()
            pnl_metrics = self.metrics_calculator.process_pnl_snapshot(
                pnl_data,
                current_timestamp=current_timestamp,
                current_capital_onchain=current_capital_onchain,
            )
            metrics_to_write.extend(pnl_metrics)
            self._logger.debug(
                f"Procesados {len(pnl_data)} traders con PnL acumulado, "
                f"generadas {len(pnl_metrics)} métricas"
            )

        return metrics_to_write

    async def get_current_metrics(self, current_timestamp: datetime) -> List[Dict[str, Any]]:
        """
        Obtiene métricas actuales del sistema.

        Args:
            current_timestamp: Timestamp actual

        Returns:
            Lista de métricas actuales
        """
        # Obtener balance SOL on-chain de la wallet del sistema
        current_capital_onchain: Optional[Decimal] = None
        try:
            sol_balance_str = await self.solana_manager.get_sol_balance(self.system_wallet_address)
            current_capital_onchain = Decimal(sol_balance_str)
            self._logger.debug(
                f"Balance on-chain obtenido para métricas actuales {self.system_wallet_address[:8]}...: {current_capital_onchain} SOL"
            )
        except Exception as e:
            self._logger.warning(
                f"Error obteniendo balance on-chain para métricas actuales {self.system_wallet_address[:8]}...: {e}"
            )

        return self.metrics_calculator.get_current_metrics(
            current_timestamp=current_timestamp,
            current_capital_onchain=current_capital_onchain,
        )

    def get_total_pnl(self) -> Decimal:
        """Obtiene el PnL total acumulado del sistema."""
        traders_only = {
            k: v
            for k, v in self.metrics_calculator.cumulative_pnl_by_trader.items()
            if k != "ALL_TRADERS"
        }
        if not traders_only:
            return Decimal("0.0")
        total = sum(traders_only.values())
        # Asegurar que siempre retorne Decimal
        if isinstance(total, Decimal):
            return total
        return Decimal(str(total))

    def get_current_capital(self) -> Optional[Decimal]:
        """Obtiene el capital actual del sistema."""
        return self.metrics_calculator.get_current_capital()


class TradingMetricsMonitor:
    """Monitor que procesa datos y genera métricas para todos los sistemas."""

    def __init__(self, systems_to_monitor: Optional[List[str]] = None):
        """
        Inicializa el monitor.

        Args:
            systems_to_monitor: Lista opcional de system_wallet_address a monitorear.
                Si es None, monitorea todos los sistemas encontrados.
        """
        self._logger = AppLogger(self.__class__.__name__)

        self.data_reader = TradingDataReader()
        self.metrics_repository = TradingMetricsRepository()
        self.run_repository = RunRepository()
        self.bot_repository = CopyTradingBotRepository()

        self.systems_to_monitor: Optional[List[str]] = systems_to_monitor
        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._system_monitors: Dict[str, SystemMonitor] = {}
        self.solana_manager = SolanaTxAnalyzer(base_rpc_url="https://api.mainnet-beta.solana.com")

    async def start(
        self,
        *,
        interval_seconds: int = 10,
        periodic_write_seconds: int = 60,
        refresh_systems: bool = False,
        refresh_systems_interval_seconds: int = 300,  # Refrescar sistemas cada 5 minutos
        delete_previous_metrics: bool = True,
    ) -> None:
        """
        Inicia el monitor para todos los sistemas.

        Args:
            interval_seconds: Intervalo para verificar nuevos datos
            periodic_write_seconds: Intervalo para escritura periódica de métricas
            refresh_systems: Si True, refresca la lista de sistemas periódicamente.
                Si False, solo usa los sistemas cargados inicialmente.
            refresh_systems_interval_seconds: Intervalo para refrescar lista de sistemas
                                            (solo aplica si refresh_systems=True)
        """
        if self._is_running:
            self._logger.warning("Monitor ya está corriendo")
            return

        if self.systems_to_monitor:
            self._logger.info(
                f"Iniciando monitor para {len(self.systems_to_monitor)} sistemas específicos"
            )
        else:
            self._logger.info("Iniciando monitor para todos los sistemas")

        # Borrar todos los datos de TradingMetrics al iniciar
        if delete_previous_metrics:
            self._logger.info("Borrando todos los datos de TradingMetrics al iniciar...")
            deleted_count = await self.metrics_repository.delete_all()
            self._logger.info(f"Eliminadas {deleted_count} métricas de la tabla TradingMetrics")
        else:
            self._logger.info("No se borrarán los datos de TradingMetrics al iniciar")

        self._is_running = True

        # Cargar sistemas iniciales
        await self._refresh_systems()

        # Iniciar loop de monitoreo
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(
                interval_seconds,
                periodic_write_seconds,
                refresh_systems,
                refresh_systems_interval_seconds,
            )
        )

    async def stop(self) -> None:
        """Detiene el monitor."""
        self._logger.info("Deteniendo monitor...")
        self._is_running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        self._system_monitors.clear()
        self._logger.info("Monitor detenido")

    async def _refresh_systems(self) -> None:
        """Refresca la lista de sistemas y sus runs más recientes."""
        try:
            # Obtener sistemas según configuración
            if self.systems_to_monitor:
                # Solo obtener los sistemas especificados
                all_systems = []
                for system_address in self.systems_to_monitor:
                    system = await self.bot_repository.get(system_address)
                    if system:
                        all_systems.append(system)
                    else:
                        self._logger.warning(
                            f"Sistema {system_address[:8]}... no encontrado en la BD"
                        )
                self._logger.debug(
                    f"Filtrando {len(self.systems_to_monitor)} sistemas específicos, "
                    f"encontrados {len(all_systems)}"
                )
            else:
                # Obtener todos los sistemas
                all_systems = await self.bot_repository.get_all()
                self._logger.debug(f"Encontrados {len(all_systems)} sistemas")

            # Obtener runs más recientes para cada sistema
            if self.systems_to_monitor:
                # Obtener run más reciente solo para los sistemas especificados
                latest_runs = []
                for system_address in self.systems_to_monitor:
                    latest_run = await self.run_repository.get_latest_by_system_wallet(
                        system_address
                    )
                    if latest_run:
                        latest_runs.append(latest_run)
                runs_by_system = {run.copy_trading_bots_id: run for run in latest_runs}
            else:
                # Obtener runs más recientes para todos los sistemas
                latest_runs = await self.run_repository.get_all_latest_runs()
                runs_by_system = {run.copy_trading_bots_id: run for run in latest_runs}

            # Crear o actualizar monitores por sistema
            current_systems = set()
            for system in all_systems:
                system_address = system.system_wallet_address
                current_systems.add(system_address)

                # Obtener run más reciente para este sistema
                latest_run = runs_by_system.get(system_address)
                if not latest_run:
                    self._logger.debug(
                        f"No se encontró run para sistema {system_address[:8]}..."
                    )
                    continue

                # Crear o actualizar monitor del sistema
                if system_address not in self._system_monitors:
                    execution_mode = "dry_run" if latest_run.is_dry_run else "live"
                    monitor = SystemMonitor(
                        system_wallet_address=system_address,
                        runs_id=latest_run.id,
                        execution_mode=execution_mode,
                        data_reader=self.data_reader,
                        metrics_repository=self.metrics_repository,
                        solana_manager=self.solana_manager,
                    )
                    await monitor.initialize()
                    self._system_monitors[system_address] = monitor
                    self._logger.info(
                        f"Monitor creado para sistema {system_address[:8]}... "
                        f"(run: {latest_run.id}, mode: {execution_mode})"
                    )
                else:
                    # Verificar si el run cambió
                    existing_monitor = self._system_monitors[system_address]
                    if existing_monitor.runs_id != latest_run.id:
                        self._logger.info(
                            f"Run actualizado para sistema {system_address[:8]}...: "
                            f"{existing_monitor.runs_id} -> {latest_run.id}"
                        )
                        execution_mode = "dry_run" if latest_run.is_dry_run else "live"
                        existing_monitor.runs_id = latest_run.id
                        existing_monitor.execution_mode = execution_mode
                        # Resetear calculador para el nuevo run
                        existing_monitor.metrics_calculator.reset_state()

            # Eliminar monitores de sistemas que ya no existen
            systems_to_remove = set(self._system_monitors.keys()) - current_systems
            for system_address in systems_to_remove:
                del self._system_monitors[system_address]
                self._logger.info(f"Monitor eliminado para sistema {system_address[:8]}...")

            self._logger.info(
                f"Sistemas monitoreados: {len(self._system_monitors)}"
            )

        except Exception as e:
            self._logger.error(f"Error refrescando sistemas: {e}", exc_info=True)

    async def _monitor_loop(
        self,
        interval_seconds: int,
        periodic_write_seconds: int,
        refresh_systems: bool,
        refresh_systems_interval_seconds: int,
    ) -> None:
        """Loop principal de monitoreo."""
        last_periodic_write: Optional[datetime] = None
        last_systems_refresh: Optional[datetime] = None

        try:
            while self._is_running:
                current_time = datetime.now()
                self._logger.debug(f"Ciclo de monitoreo - {current_time}")

                # Refrescar sistemas periódicamente (solo si está habilitado)
                if refresh_systems:
                    if (
                        last_systems_refresh is None
                        or (current_time - last_systems_refresh).total_seconds()
                        >= refresh_systems_interval_seconds
                    ):
                        await self._refresh_systems()
                        last_systems_refresh = current_time

                # Procesar cada sistema
                all_metrics_by_system: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
                all_systems_total_pnl: Dict[str, Decimal] = {}
                all_systems_capital: Dict[str, Optional[Decimal]] = {}

                for system_address, monitor in self._system_monitors.items():
                    try:
                        # Procesar ciclo del sistema
                        system_metrics = await monitor.process_cycle()
                        if system_metrics:
                            all_metrics_by_system[system_address].extend(system_metrics)

                        # Obtener PnL total del sistema para agregación
                        total_pnl = monitor.get_total_pnl()
                        all_systems_total_pnl[system_address] = total_pnl

                        # Obtener capital actual del sistema para agregación
                        current_capital = monitor.get_current_capital()
                        all_systems_capital[system_address] = current_capital

                    except Exception as e:
                        self._logger.error(
                            f"Error procesando sistema {system_address[:8]}...: {e}",
                            exc_info=True,
                        )

                # Verificar si necesitamos escritura periódica
                should_write_periodic = False
                if last_periodic_write is None:
                    if any(
                        monitor.metrics_calculator.cumulative_pnl_by_trader
                        for monitor in self._system_monitors.values()
                    ):
                        should_write_periodic = True
                        last_periodic_write = current_time
                        self._logger.debug("Primera escritura periódica de métricas")
                else:
                    time_since_last = (current_time - last_periodic_write).total_seconds()
                    if time_since_last >= periodic_write_seconds:
                        should_write_periodic = True
                        last_periodic_write = current_time
                        self._logger.debug(
                            f"Escritura periódica de métricas (cada {periodic_write_seconds}s)"
                        )

                # Generar métricas periódicas si es necesario
                if should_write_periodic:
                    for system_address, monitor in self._system_monitors.items():
                        periodic_metrics = await monitor.get_current_metrics(current_time)
                        if periodic_metrics:
                            all_metrics_by_system[system_address].extend(periodic_metrics)

                # Escribir métricas por sistema
                for system_address, metrics in all_metrics_by_system.items():
                    if metrics:
                        monitor = self._system_monitors[system_address]
                        await self._write_metrics(metrics, monitor)

                # Generar y escribir métricas agregadas de ALL_SYSTEMS
                if should_write_periodic and all_systems_total_pnl:
                    await self._write_all_systems_metrics(
                        all_systems_total_pnl, all_systems_capital, current_time
                    )

                # Esperar antes del siguiente ciclo
                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            self._logger.debug("Loop de monitoreo cancelado")
        except Exception as e:
            self._logger.error(f"Error en loop de monitoreo: {e}", exc_info=True)

    async def _write_metrics(
        self, metrics: List[Dict[str, Any]], monitor: SystemMonitor
    ) -> None:
        """
        Escribe métricas a la base de datos para un sistema específico.

        Args:
            metrics: Lista de métricas a escribir
            monitor: Monitor del sistema
        """
        if not metrics:
            return

        metrics_to_save = []

        for metric in metrics:
            # Validar valor
            value = metric.get("metric_value")
            if value is None or not isinstance(value, (int, float)):
                self._logger.warning(f"Métrica inválida, saltando: {metric}")
                continue

            # Convertir a Decimal y validar
            try:
                metric_value = Decimal(str(value))
                if metric_value.is_nan() or metric_value.is_infinite():
                    self._logger.warning(f"Métrica con NaN/Inf, saltando: {metric}")
                    continue
            except (ValueError, TypeError) as e:
                self._logger.warning(f"Error convirtiendo valor de métrica: {e}")
                continue

            metrics_to_save.append({
                "timestamp": metric["timestamp"],
                "metric_name": metric["metric_name"],
                "metric_value": metric_value,
                "system_name": monitor.system_wallet_address,
                "execution_mode": monitor.execution_mode,
                "trader": metric.get("trader", "ALL_TRADERS"),
            })

        if not metrics_to_save:
            return

        # Guardar en lote
        try:
            count = await self.metrics_repository.bulk_create(metrics_to_save)
            self._logger.debug(
                f"Guardadas {count} métricas para sistema {monitor.system_wallet_address[:8]}..."
            )
        except Exception as e:
            self._logger.error(
                f"Error guardando métricas del sistema {monitor.system_wallet_address[:8]}...: {e}",
                exc_info=True,
            )

    async def _write_all_systems_metrics(
        self,
        systems_total_pnl: Dict[str, Decimal],
        systems_capital: Dict[str, Optional[Decimal]],
        timestamp: datetime,
    ) -> None:
        """
        Escribe métricas agregadas de ALL_SYSTEMS.

        Args:
            systems_total_pnl: Diccionario con PnL total por sistema
            systems_capital: Diccionario con capital actual por sistema
            timestamp: Timestamp para las métricas
        """
        if not systems_total_pnl:
            return

        # Calcular total agregado de todos los sistemas
        total_all_systems_pnl = sum(systems_total_pnl.values())

        # Calcular capital total de todos los sistemas (suma de capitales actuales)
        total_all_systems_capital = Decimal("0.0")
        for system_address, capital in systems_capital.items():
            if capital is not None:
                total_all_systems_capital = total_all_systems_capital + capital

        # Agrupar por execution_mode
        pnl_by_mode: Dict[str, Decimal] = defaultdict(lambda: Decimal("0.0"))
        capital_by_mode: Dict[str, Decimal] = defaultdict(lambda: Decimal("0.0"))

        for system_address, monitor in self._system_monitors.items():
            if system_address in systems_total_pnl:
                pnl_by_mode[monitor.execution_mode] += systems_total_pnl[system_address]
            if system_address in systems_capital:
                capital = systems_capital[system_address]
                if capital is not None:
                    capital_by_mode[monitor.execution_mode] = capital_by_mode[monitor.execution_mode] + capital

        # Crear métricas para cada modo de ejecución
        all_systems_metrics = []
        for execution_mode, total_pnl in pnl_by_mode.items():
            # PnL Total
            all_systems_metrics.append({
                "timestamp": timestamp,
                "metric_name": "PNL_Total_Cumulative",
                "metric_value": float(total_pnl),
                "system_name": "ALL_SYSTEMS",
                "execution_mode": execution_mode,
                "trader": "ALL_TRADERS",
            })

            # Capital Total
            if execution_mode in capital_by_mode:
                all_systems_metrics.append({
                    "timestamp": timestamp,
                    "metric_name": "Capital_Total",
                    "metric_value": float(capital_by_mode[execution_mode]),
                    "system_name": "ALL_SYSTEMS",
                    "execution_mode": execution_mode,
                    "trader": "ALL_TRADERS",
                })

        # También crear métrica total combinada (live + dry_run)
        if len(pnl_by_mode) > 1:
            # PnL Total combinado
            all_systems_metrics.append({
                "timestamp": timestamp,
                "metric_name": "PNL_Total_Cumulative",
                "metric_value": float(total_all_systems_pnl),
                "system_name": "ALL_SYSTEMS",
                "execution_mode": "all",  # Para indicar que incluye todos los modos
                "trader": "ALL_TRADERS",
            })

            # Capital Total combinado
            if total_all_systems_capital > 0:
                all_systems_metrics.append({
                    "timestamp": timestamp,
                    "metric_name": "Capital_Total",
                    "metric_value": float(total_all_systems_capital),
                    "system_name": "ALL_SYSTEMS",
                    "execution_mode": "all",
                    "trader": "ALL_TRADERS",
                })

        if all_systems_metrics:
            try:
                count = await self.metrics_repository.bulk_create(all_systems_metrics)
                self._logger.debug(f"Guardadas {count} métricas para ALL_SYSTEMS")
            except Exception as e:
                self._logger.error(f"Error guardando métricas de ALL_SYSTEMS: {e}", exc_info=True)
