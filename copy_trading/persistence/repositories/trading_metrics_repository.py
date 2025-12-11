# -*- coding: utf-8 -*-
"""
Repositorio asíncrono para la tabla TradingMetrics.
"""
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
from sqlalchemy import select, and_, or_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .base import AsyncRepository
from ..orm.models import TradingMetrics


class TradingMetricsRepository(AsyncRepository):
    """Repositorio asíncrono para la tabla TradingMetrics."""

    async def create(
        self,
        *,
        timestamp: datetime,
        metric_name: str,
        metric_value: Decimal,
        system_name: str,
        execution_mode: str,
        trader: str,
    ) -> TradingMetrics:
        """
        Crea una nueva métrica de trading.

        Args:
            timestamp: Timestamp de la métrica
            metric_name: Nombre de la métrica
            metric_value: Valor numérico de la métrica
            system_name: Nombre del sistema o "ALL_SYSTEMS"
            execution_mode: Modo de ejecución (live/dry_run)
            trader: Dirección de wallet del trader o "ALL_TRADERS"

        Returns:
            TradingMetrics creada
        """
        async with (await self._get_session()) as session:
            metric = TradingMetrics(
                id=uuid.uuid4(),
                timestamp=timestamp,
                metric_name=metric_name,
                metric_value=metric_value,
                system_name=system_name,
                execution_mode=execution_mode,
                trader=trader,
            )
            session.add(metric)
            await session.flush()
            await self._commit(session)
            return metric

    async def bulk_create(
        self,
        metrics: List[Dict[str, Any]],
    ) -> int:
        """
        Crea múltiples métricas en una sola transacción.

        Args:
            metrics: Lista de diccionarios con los datos de las métricas.
                    Cada diccionario debe contener: timestamp, metric_name,
                    metric_value, system_name, execution_mode, trader

        Returns:
            Cantidad de métricas creadas
        """
        if not metrics:
            return 0

        async with (await self._get_session()) as session:
            metric_objects = []
            for metric_data in metrics:
                metric = TradingMetrics(
                    id=uuid.uuid4(),
                    timestamp=metric_data["timestamp"],
                    metric_name=metric_data["metric_name"],
                    metric_value=Decimal(str(metric_data["metric_value"])),
                    system_name=metric_data["system_name"],
                    execution_mode=metric_data["execution_mode"],
                    trader=metric_data["trader"],
                )
                metric_objects.append(metric)

            session.add_all(metric_objects)
            await session.flush()
            await self._commit(session)
            return len(metric_objects)

    async def get(self, metric_id: uuid.UUID) -> Optional[TradingMetrics]:
        """
        Obtiene una métrica por su ID.

        Args:
            metric_id: ID de la métrica

        Returns:
            TradingMetrics si existe, None en caso contrario
        """
        async with (await self._get_session()) as session:
            return await session.get(TradingMetrics, metric_id)

    async def get_by_system(
        self,
        system_name: str,
        *,
        metric_name: Optional[str] = None,
        trader: Optional[str] = None,
        execution_mode: Optional[str] = None,
        limit: Optional[int] = None,
        order_by_desc: bool = True,
    ) -> List[TradingMetrics]:
        """
        Obtiene métricas filtradas por sistema.

        Args:
            system_name: Nombre del sistema o "ALL_SYSTEMS"
            metric_name: Filtrar por nombre de métrica (opcional)
            trader: Filtrar por trader (opcional)
            execution_mode: Filtrar por modo de ejecución (opcional)
            limit: Límite de resultados (opcional)
            order_by_desc: Ordenar por timestamp descendente (True) o ascendente (False)

        Returns:
            Lista de TradingMetrics
        """
        async with (await self._get_session()) as session:
            query = select(TradingMetrics).where(TradingMetrics.system_name == system_name)

            if metric_name:
                query = query.where(TradingMetrics.metric_name == metric_name)

            if trader:
                query = query.where(TradingMetrics.trader == trader)

            if execution_mode:
                query = query.where(TradingMetrics.execution_mode == execution_mode)

            if order_by_desc:
                query = query.order_by(TradingMetrics.timestamp.desc())
            else:
                query = query.order_by(TradingMetrics.timestamp.asc())

            if limit:
                query = query.limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_by_time_range(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        system_name: Optional[str] = None,
        metric_name: Optional[str] = None,
        trader: Optional[str] = None,
        execution_mode: Optional[str] = None,
    ) -> List[TradingMetrics]:
        """
        Obtiene métricas en un rango de tiempo.

        Args:
            start_time: Tiempo de inicio
            end_time: Tiempo de fin
            system_name: Filtrar por sistema (opcional)
            metric_name: Filtrar por nombre de métrica (opcional)
            trader: Filtrar por trader (opcional)
            execution_mode: Filtrar por modo de ejecución (opcional)

        Returns:
            Lista de TradingMetrics en el rango de tiempo
        """
        async with (await self._get_session()) as session:
            query = select(TradingMetrics).where(
                and_(
                    TradingMetrics.timestamp >= start_time,
                    TradingMetrics.timestamp <= end_time,
                )
            )

            if system_name:
                query = query.where(TradingMetrics.system_name == system_name)

            if metric_name:
                query = query.where(TradingMetrics.metric_name == metric_name)

            if trader:
                query = query.where(TradingMetrics.trader == trader)

            if execution_mode:
                query = query.where(TradingMetrics.execution_mode == execution_mode)

            query = query.order_by(TradingMetrics.timestamp.asc())

            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_latest_metric(
        self,
        *,
        system_name: str,
        metric_name: str,
        trader: Optional[str] = None,
        execution_mode: Optional[str] = None,
    ) -> Optional[TradingMetrics]:
        """
        Obtiene la métrica más reciente de un tipo específico.

        Args:
            system_name: Nombre del sistema o "ALL_SYSTEMS"
            metric_name: Nombre de la métrica
            trader: Filtrar por trader (opcional)
            execution_mode: Filtrar por modo de ejecución (opcional)

        Returns:
            TradingMetrics más reciente o None si no existe
        """
        async with (await self._get_session()) as session:
            query = select(TradingMetrics).where(
                and_(
                    TradingMetrics.system_name == system_name,
                    TradingMetrics.metric_name == metric_name,
                )
            )

            if trader:
                query = query.where(TradingMetrics.trader == trader)

            if execution_mode:
                query = query.where(TradingMetrics.execution_mode == execution_mode)

            query = query.order_by(TradingMetrics.timestamp.desc()).limit(1)

            result = await session.execute(query)
            return result.scalars().first()

    async def get_metrics_summary(
        self,
        *,
        system_name: Optional[str] = None,
        metric_names: Optional[List[str]] = None,
        execution_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Obtiene un resumen de métricas.

        Args:
            system_name: Filtrar por sistema (opcional, todas si None)
            metric_names: Lista de nombres de métricas a incluir (opcional, todas si None)
            execution_mode: Filtrar por modo de ejecución (opcional)

        Returns:
            Diccionario con resumen de métricas
        """
        async with (await self._get_session()) as session:
            query = select(
                TradingMetrics.metric_name,
                func.count(TradingMetrics.id).label("count"),
                func.max(TradingMetrics.timestamp).label("latest_timestamp"),
                func.min(TradingMetrics.timestamp).label("earliest_timestamp"),
            )

            conditions = []
            if system_name:
                conditions.append(TradingMetrics.system_name == system_name)
            if execution_mode:
                conditions.append(TradingMetrics.execution_mode == execution_mode)

            if conditions:
                query = query.where(and_(*conditions))

            if metric_names:
                query = query.where(TradingMetrics.metric_name.in_(metric_names))

            query = query.group_by(TradingMetrics.metric_name)

            result = await session.execute(query)
            rows = result.all()

            summary = {
                "system_name": system_name or "ALL_SYSTEMS",
                "metrics": {},
            }

            for row in rows:
                summary["metrics"][row.metric_name] = {
                    "count": row.count,
                    "latest_timestamp": row.latest_timestamp.isoformat() if row.latest_timestamp else None,
                    "earliest_timestamp": row.earliest_timestamp.isoformat() if row.earliest_timestamp else None,
                }

            return summary

    async def delete_by_system(self, system_name: str) -> int:
        """
        Elimina todas las métricas de un sistema.

        Args:
            system_name: Nombre del sistema

        Returns:
            Cantidad de métricas eliminadas
        """
        async with (await self._get_session()) as session:
            query = select(TradingMetrics).where(TradingMetrics.system_name == system_name)
            result = await session.execute(query)
            metrics = result.scalars().all()

            count = len(metrics)
            if count > 0:
                for metric in metrics:
                    await session.delete(metric)
                await self._commit(session)

            return count

    async def delete_old_metrics(
        self,
        *,
        before_timestamp: datetime,
        system_name: Optional[str] = None,
    ) -> int:
        """
        Elimina métricas anteriores a un timestamp.

        Args:
            before_timestamp: Timestamp límite
            system_name: Filtrar por sistema (opcional)

        Returns:
            Cantidad de métricas eliminadas
        """
        async with (await self._get_session()) as session:
            conditions = [TradingMetrics.timestamp < before_timestamp]
            if system_name:
                conditions.append(TradingMetrics.system_name == system_name)

            query = select(TradingMetrics).where(and_(*conditions))
            result = await session.execute(query)
            metrics = result.scalars().all()

            count = len(metrics)
            if count > 0:
                for metric in metrics:
                    await session.delete(metric)
                await self._commit(session)

            return count

    async def delete_all(self) -> int:
        """
        Elimina todas las métricas de la tabla TradingMetrics.

        Este método usa un DELETE SQL directo sin cargar objetos en memoria,
        lo que lo hace mucho más eficiente que iterar sobre cada registro.

        Returns:
            Cantidad de métricas eliminadas
        """
        async with (await self._get_session()) as session:
            # Usar delete() ejecuta un DELETE SQL directo sin cargar objetos
            stmt = delete(TradingMetrics)
            result = await session.execute(stmt)
            await self._commit(session)
            return result.rowcount
