# -*- coding: utf-8 -*-
"""
Caso de uso: Ejecutar backtest completo.

Orquesta el flujo completo de ejecución de un backtest, incluyendo:
- Carga de transacciones
- Filtrado por fechas
- Validación de transacciones
- Matching FIFO
- Cálculo de métricas
- Gestión de caché
"""
import logging
from typing import Optional, Any, Dict, List
from datetime import datetime, timezone
from decimal import Decimal

from ...domain.ports.transaction_repository import ITransactionRepository
from ...domain.ports.cache_service import ICacheService
from ...domain.entities.backtest_statistics import BacktestStats, ValidationMetrics
from ...domain.services.backtest_validator import BacktestValidator
from ...domain.services.fifo_matcher import FIFOMatcher
from ...domain.services.metrics_calculator import MetricsCalculator
from ...domain.validations.models import BaseValidation

logger = logging.getLogger(__name__)


class BacktestRunner:
    """
    Caso de uso: Ejecutar backtest completo.
    
    Orquesta todos los servicios y puertos necesarios para ejecutar un backtest,
    desde la carga de transacciones hasta el cálculo de métricas finales.
    """

    def __init__(
        self,
        repository: ITransactionRepository,
        cache_service: ICacheService,
        fifo_matcher: FIFOMatcher,
        metrics_calculator: MetricsCalculator
    ):
        """
        Inicializa el runner de backtest.
        
        Args:
            repository: Repositorio de transacciones
            cache_service: Servicio de caché
            fifo_matcher: Servicio de matching FIFO
            metrics_calculator: Calculador de métricas
        """
        self.repository = repository
        self.cache_service = cache_service
        self.fifo_matcher = fifo_matcher
        self.metrics_calculator = metrics_calculator

    def run(
        self,
        validator: Optional[BacktestValidator] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None
    ) -> Optional[BacktestStats]:
        """
        Ejecuta el backtest completo.
        
        Flujo:
        1. Parsear fechas
        2. Generar clave de caché
        3. Verificar caché
        4. Obtener y filtrar transacciones por fecha
        5. Filtrar transacciones con validador (si se proporciona)
        6. Procesar transacciones con FIFO matcher
        7. Calcular métricas
        8. Guardar en caché
        9. Retornar estadísticas
        
        Args:
            start_date: Fecha de inicio del rango. Opcional. Puede ser:
                - String con fecha simple: "2025-01-01"
                - String ISO 8601: "2025-01-01T00:00:00Z"
                - datetime object
            end_date: Fecha de fin del rango. Opcional. Puede ser:
                - String con fecha simple: "2025-12-31"
                - String ISO 8601: "2025-12-31T23:59:59Z"
                - datetime object
            validator: Validador opcional de transacciones. Si se proporciona,
                        se aplicarán las validaciones a las transacciones antes de procesarlas.
        
        Returns:
            BacktestStats con todas las estadísticas calculadas o None si no hay trades cerrados
        """
        # Parsear fechas
        start_dt = self._parse_date_input(start_date)
        end_dt = self._parse_date_input(end_date)

        # Convertir a strings ISO para la clave de caché y métricas
        start_date_str = start_dt.isoformat() if start_dt else None
        end_date_str = end_dt.isoformat() if end_dt else None

        # Generar clave de caché
        validator_config = self._serialize_validator_config(validator) if validator else None
        cache_key = self.cache_service.generate_key(
            validator_config=validator_config,
            start_date=start_date_str,
            end_date=end_date_str
        )

        # Verificar caché
        cached_stats = self.cache_service.get(cache_key)
        if cached_stats:
            logger.info(f"Resultado encontrado en caché (key: {cache_key[:16]}...)")
            return cached_stats

        logger.info("Iniciando backtest...")

        # Resetear estado del matcher
        self.fifo_matcher.reset()

        # Resetear métricas del validador si existe
        if validator:
            validator.reset_all_metrics()
            logger.debug("Métricas de validación reiniciadas")

        # Obtener todas las transacciones
        all_transactions = self.repository.get_all()

        if not all_transactions:
            logger.warning("No hay transacciones cargadas")
            return None

        # Ordenar todas las transacciones por timestamp primero (una sola vez)
        all_sorted_txs = sorted(
            all_transactions,
            key=lambda x: x.block_timestamp
        )

        # Guardar total antes del filtro de fecha
        total_before_filter = len(all_sorted_txs)

        # Calcular tiempo mínimo y máximo de TODAS las transacciones (sin filtros)
        # Usar las transacciones ya ordenadas para calcular min/max eficientemente
        min_timestamp_dt_all: Optional[datetime] = None
        max_timestamp_dt_all: Optional[datetime] = None

        if all_sorted_txs:
            # Primera y última transacción ya ordenadas
            first_tx_dt = self._parse_timestamp(all_sorted_txs[0].block_timestamp)
            last_tx_dt = self._parse_timestamp(all_sorted_txs[-1].block_timestamp)
            if first_tx_dt is not None:
                min_timestamp_dt_all = first_tx_dt
            if last_tx_dt is not None:
                max_timestamp_dt_all = last_tx_dt

        # Filtrar por rango de fechas si se proporcionaron (inline, más eficiente)
        if start_dt is not None or end_dt is not None:
            filtered_by_date_txs = []
            for tx in all_sorted_txs:
                tx_dt = self._parse_timestamp(tx.block_timestamp)
                # Aplicar filtros de fecha
                if start_dt is not None and tx_dt is not None and tx_dt < start_dt:
                    continue
                if end_dt is not None and tx_dt is not None and tx_dt > end_dt:
                    continue
                filtered_by_date_txs.append(tx)
            sorted_transactions = filtered_by_date_txs
            date_filtered_count = len(sorted_transactions)
            logger.info(
                f"Filtrado por fecha: {date_filtered_count}/{total_before_filter} "
                f"transacciones en el rango {start_date_str or 'sin inicio'} a {end_date_str or 'sin fin'}"
            )
        else:
            sorted_transactions = all_sorted_txs
            date_filtered_count = total_before_filter

        # Contexto compartido para validaciones
        validation_context: Dict[str, Any] = {
            'token_activity_state': {}
        }

        # Contador de posiciones abiertas por token (para validar sells)
        open_positions_count: Dict[str, int] = {}

        # Filtrar transacciones según validaciones (si hay validador)
        accepted_transactions = []
        total_buy_transactions = 0
        accepted_buy_transactions = 0

        for tx in sorted_transactions:
            token_address = tx.base_token_address
            tx_type = tx.side

            # Las ventas: si no hay validador, se procesan todas; si hay validador, solo si hay posiciones abiertas
            if tx_type == 'sell':
                if validator is None:
                    # Sin validador: procesar todas las ventas
                    accepted_transactions.append(tx)
                    logger.debug(f"SELL aceptado (sin filtros): token={token_address[:8]}")
                elif open_positions_count.get(token_address, 0) > 0:
                    # Con validador: solo si hay posiciones abiertas
                    accepted_transactions.append(tx)
                    logger.debug(
                        f"SELL aceptado: token={token_address[:8]} "
                        f"posiciones_abiertas={open_positions_count.get(token_address, 0)}"
                    )
                else:
                    logger.debug(
                        f"SELL rechazado: token={token_address[:8]} "
                        f"sin posiciones abiertas (hash={tx.signature[:10]})"
                    )
                continue

            # Para compras, aplicar validaciones (si hay validador)
            if tx_type == 'buy':
                total_buy_transactions += 1

                # Si no hay validador, aceptar todas las compras
                if validator is None:
                    accepted_transactions.append(tx)
                    accepted_buy_transactions += 1
                    open_positions_count[token_address] = open_positions_count.get(token_address, 0) + 1
                    logger.debug(
                        f"BUY aceptado (sin filtros): token={token_address[:8]} "
                        f"posiciones_abiertas={open_positions_count[token_address]}"
                    )
                else:
                    # Validar usando el validador
                    is_valid, validation_results = validator.validate(tx, validation_context)

                    if is_valid:
                        accepted_transactions.append(tx)
                        accepted_buy_transactions += 1
                        open_positions_count[token_address] = open_positions_count.get(token_address, 0) + 1
                        logger.debug(
                            f"BUY aceptado: token={token_address[:8]} "
                            f"posiciones_abiertas={open_positions_count[token_address]}"
                        )

        # Procesar transacciones aceptadas con FIFO matcher
        for tx in accepted_transactions:
            if tx.side == 'buy':
                self.fifo_matcher.process_buy(tx)
            elif tx.side == 'sell':
                # Usar método optimizado O(1) en lugar de filtrar todas las posiciones
                positions_before = self.fifo_matcher.get_open_positions_count_by_token(tx.base_token_address)
                self.fifo_matcher.process_sell(tx)
                positions_after = self.fifo_matcher.get_open_positions_count_by_token(tx.base_token_address)
                positions_closed = positions_before - positions_after
                if positions_closed > 0:
                    open_positions_count[tx.base_token_address] = max(
                        0, 
                        open_positions_count.get(tx.base_token_address, 0) - positions_closed
                    )
                    logger.debug(
                        f"SELL procesado: token={tx.base_token_address[:8]} "
                        f"posiciones_cerradas={positions_closed} "
                        f"posiciones_restantes={open_positions_count.get(tx.base_token_address, 0)}"
                    )

        # Obtener trades cerrados y posiciones abiertas
        closed_trades = self.fifo_matcher.get_closed_trades()
        open_positions = self.fifo_matcher.get_open_positions()

        if not closed_trades:
            logger.warning("No se encontraron trades cerrados para calcular estadísticas")
            return None

        # Crear métricas de validación si se usó un validador
        validation_metrics = None
        if validator:
            validation_metrics_dict = validator.collect_metrics()

            # Calcular tasa de aceptación
            filter_acceptance_rate = Decimal('0')
            if total_buy_transactions > 0:
                filter_acceptance_rate = (
                    Decimal(accepted_buy_transactions) / Decimal(total_buy_transactions) * 100
                )

            validation_metrics = ValidationMetrics(
                total_buy_transactions=total_buy_transactions,
                accepted_buy_transactions=accepted_buy_transactions,
                filtered_transactions=len(accepted_transactions),
                filter_acceptance_rate=filter_acceptance_rate,
                validation_metrics=validation_metrics_dict
            )

            logger.info(
                f"Filtrado: {len(accepted_transactions)}/{len(sorted_transactions)} transacciones aceptadas "
                f"({float(filter_acceptance_rate):.2f}%)"
            )

        # Calcular estadísticas
        stats = self.metrics_calculator.calculate_stats(
            trades=closed_trades,
            open_positions=open_positions,
            validation_metrics=validation_metrics
        )

        # Agregar métricas de filtrado por fecha
        stats.date_range_start = start_date_str
        stats.date_range_end = end_date_str
        stats.total_transactions_before_date_filter = total_before_filter
        stats.date_filtered_transactions = date_filtered_count

        # Agregar métricas de tiempo mínimo y máximo (del rango completo de datos, sin filtros)
        stats.min_timestamp = min_timestamp_dt_all.isoformat() if min_timestamp_dt_all else None
        stats.max_timestamp = max_timestamp_dt_all.isoformat() if max_timestamp_dt_all else None

        logger.info(f"Backtest completado: {stats.total_trades} trades cerrados")

        if stats.min_timestamp and stats.max_timestamp:
            logger.info(f"Rango de tiempo en datos: {stats.min_timestamp} a {stats.max_timestamp}")

        # Guardar en caché antes de retornar
        self.cache_service.set(cache_key, stats)
        logger.debug(f"Resultado guardado en caché (key: {cache_key[:16]}...)")

        return stats

    def _parse_date_input(self, date_input: Optional[Any]) -> Optional[datetime]:
        """
        Parsea una entrada de fecha que puede ser datetime, string ISO, fecha simple, o None.
        
        Args:
            date_input: Puede ser datetime, string en formato ISO 8601 o fecha simple (YYYY-MM-DD), o None
        
        Returns:
            datetime con timezone UTC o None si no se puede parsear
        """
        if date_input is None:
            return None

        if isinstance(date_input, datetime):
            # Si ya es datetime, asegurar que tenga timezone UTC
            if date_input.tzinfo is None:
                return date_input.replace(tzinfo=timezone.utc)
            else:
                return date_input.astimezone(timezone.utc)

        if isinstance(date_input, str):
            date_str = date_input.strip()

            # Intentar parsear primero como fecha simple (YYYY-MM-DD)
            if len(date_str) == 10 and date_str.count('-') == 2:
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass  # Continuar con otros métodos

            # Intentar parsear como ISO 8601 (con o sin hora)
            try:
                iso_str = date_str.replace('Z', '+00:00')
                dt = datetime.fromisoformat(iso_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                return dt
            except (ValueError, AttributeError):
                logger.warning(f"No se pudo parsear la fecha: {date_input}")
                return None

        return None

    def _parse_timestamp(self, timestamp: Any) -> Optional[datetime]:
        """
        Parsea y normaliza un timestamp a datetime con timezone UTC.
        
        Args:
            timestamp: datetime o string ISO 8601
        
        Returns:
            datetime con timezone UTC o None si no se puede parsear
        """
        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                return timestamp.replace(tzinfo=timezone.utc)
            else:
                return timestamp.astimezone(timezone.utc)
        elif isinstance(timestamp, str):
            try:
                iso_str = timestamp.replace('Z', '+00:00')
                dt = datetime.fromisoformat(iso_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                return dt
            except (ValueError, AttributeError):
                return None
        return None

    def _serialize_validator_config(self, validator: Optional[BacktestValidator]) -> Optional[str]:
        """
        Serializa la configuración del validador para la clave de caché.
        
        Serializa recursivamente toda la estructura del validador incluyendo:
        - Tipo y nombre de cada validación
        - Estado enabled/disabled de cada validación
        - Parámetros de configuración de cada validación (thresholds, pools, etc.)
        - Operadores lógicos en grupos
        - Estructura anidada de grupos
        
        Args:
            validator: Instancia del validador a serializar
        
        Returns:
            String serializado con la configuración o None si no hay validador
        """
        if not validator:
            return None

        import json
        try:
            # Serializar recursivamente la estructura del validador
            config = {
                'validator_type': type(validator).__name__,
                'validations': self._serialize_validation_items(validator.validations)
            }
            return json.dumps(config, sort_keys=True, default=str)
        except Exception as e:
            logger.warning(f"Error al serializar configuración del validador: {e}")
            return None

    def _serialize_validation_items(self, items: List[Any]) -> List[Dict[str, Any]]:
        """
        Serializa recursivamente una lista de items de validación.
        
        Args:
            items: Lista de ValidationItem (puede contener BaseValidation o grupos)
        
        Returns:
            Lista de diccionarios serializados
        """
        serialized = []
        for item in items:
            if isinstance(item, BaseValidation):
                # Serializar validación individual
                serialized.append(self._serialize_validation(item))
            elif isinstance(item, dict) and "validations" in item:
                # Serializar grupo de validaciones
                serialized.append({
                    "type": "group",
                    "logical_operator": item.get("logical_operator", "AND"),
                    "validations": self._serialize_validation_items(item["validations"])
                })
            else:
                logger.warning(f"Tipo de item de validación no reconocido: {type(item)}")

        return serialized

    def _serialize_validation(self, validation: Any) -> Dict[str, Any]:
        """
        Serializa una validación individual (BaseValidation).
        
        Extrae el nombre, estado enabled, y parámetros de configuración relevantes
        usando get_metrics() pero excluyendo métricas de estado (como rejected_count).
        
        Args:
            validation: Instancia de BaseValidation
        
        Returns:
            Diccionario con la configuración serializada
        """
        if not isinstance(validation, BaseValidation):
            logger.warning(f"Intento de serializar objeto que no es BaseValidation: {type(validation)}")
            return {"type": "unknown"}

        # Obtener métricas que incluyen parámetros de configuración
        metrics = validation.get_metrics()

        # Construir configuración: nombre, enabled, y parámetros (excluyendo rejected_count que es estado)
        config = {
            "type": "validation",
            "class_name": type(validation).__name__,
            "name": validation.name,
            "enabled": metrics.get("enabled", validation.enabled)
        }

        # Agregar parámetros de configuración (excluir rejected_count que es métrica de estado)
        for key, value in metrics.items():
            if key not in ["enabled", "rejected_count"]:
                # Convertir valores a tipos serializables
                if isinstance(value, (dict, list, str, int, float, bool, type(None))):
                    config[key] = value
                else:
                    # Para otros tipos, convertir a string
                    config[key] = str(value)

        return config
