# -*- coding: utf-8 -*-
"""
Adaptador: Repositorio de transacciones de PumpPortal.

Implementa ITransactionRepository para cargar transacciones desde PostgreSQL
usando datos de PumpPortal WebSocket almacenados en la base de datos.
"""
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Dict, Any, Literal, cast

from sqlalchemy import create_engine, select, and_, text
from sqlalchemy.orm import sessionmaker

from ....domain.ports.transaction_repository import ITransactionRepository
from ....domain.entities.transactions import SwapTransaction
from ....domain.services.exchange_registry import normalize_exchange

# Importar modelos ORM
from copy_trading.persistence.orm.models import Position, TraderTradeData, Mint, Run
from copy_trading.persistence.orm.enums import Side

logger = logging.getLogger(__name__)


class PumpPortalTransactionRepository(ITransactionRepository):
    """
    Repositorio de transacciones para la fuente PumpPortal.
    
    Implementa ITransactionRepository cargando transacciones desde PostgreSQL
    usando SQLAlchemy ORM, accediendo a las tablas positions, trader_trade_data y mints
    que almacenan información de transacciones de PumpPortal WebSocket.
    """

    _POOL_TO_ADDRESS = {
        "pump": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "pump-amm": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
        "bonk": "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
    }

    def __init__(
        self,
        connection_string: Optional[str] = None,
        engine=None
    ):
        """
        Inicializa el repositorio de PumpPortal.
        
        Args:
            connection_string: String de conexión PostgreSQL (opcional).
                                Si no se proporciona, usa variables de entorno.
            engine: Engine de SQLAlchemy ya creado (opcional).
                    Si se proporciona, se usa este en lugar de crear uno nuevo.
        """
        if engine is not None:
            self.engine = engine
        elif connection_string:
            # Crear engine síncrono
            self.engine = create_engine(connection_string)
        else:
            # Usar variables de entorno
            user = os.getenv("BACKTEST_PGUSER", "postgres")
            password = os.getenv("BACKTEST_PGPASSWORD", "")
            host = os.getenv("BACKTEST_PGHOST", "localhost")
            port = os.getenv("BACKTEST_PGPORT", "5432")
            database = os.getenv("BACKTEST_PGDATABASE", "postgres")
            connection_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"
            self.engine = create_engine(connection_string)

        # Crear sessionmaker
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._transactions: List[SwapTransaction] = []
        logger.debug("PumpPortalTransactionRepository inicializado")

    def load_from_file(self, file_path: str) -> None:
        """
        No soportado para PumpPortal.
        
        Raises:
            NotImplementedError: PumpPortal solo soporta carga desde base de datos
        """
        raise NotImplementedError(
            "PumpPortalTransactionRepository no soporta carga desde archivos. "
            "Usa load_from_database() según corresponda."
        )

    def load_from_data(self, data: List[Dict[str, Any]]) -> None:
        """
        No soportado para PumpPortal.
        
        Raises:
            NotImplementedError: PumpPortal solo soporta carga desde base de datos
        """
        raise NotImplementedError(
            "PumpPortalTransactionRepository no soporta carga desde memoria. "
            "Usa load_from_database() según corresponda."
        )

    def load_from_database(
        self,
        system_wallet_address: str,
        trader_wallet: str,
        run_id: Optional[Any] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None,
        query: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Carga transacciones desde PostgreSQL usando SQLAlchemy ORM.
        
        Filtra las transacciones por el run especificado o el más reciente del system_wallet_address
        y por la wallet del trader. Usa signature y created_at de TraderTradeData.
        
        Args:
            system_wallet_address: Dirección de wallet del sistema (copy_trading_bots_id) - OBLIGATORIO
            trader_wallet: Wallet address del trader - OBLIGATORIO
            run_id: ID del run a usar (opcional). Si no se proporciona, se usa el más reciente
            start_date: Fecha de inicio para filtrar (opcional). Usa TraderTradeData.created_at
            end_date: Fecha de fin para filtrar (opcional). Usa TraderTradeData.created_at
            limit: Límite de registros a cargar (opcional)
            query: Query SQL personalizada (opcional). Si se proporciona, se usa esta en lugar de ORM
            **kwargs: Parámetros adicionales
        
        Raises:
            ValueError: Si no se encuentra un run para el system_wallet_address especificado
        """
        logger.info(
            f"Cargando datos PumpPortal desde PostgreSQL para system_wallet: {system_wallet_address[:8]}... "
            f"y trader: {trader_wallet[:8]}..."
        )

        # Si se proporciona query SQL directa, usarla
        if query:
            self._transactions = self._load_from_raw_query(query)
            logger.info(f"Cargadas {len(self._transactions)} transacciones desde query SQL directa")
            return

        # Construir query usando SQLAlchemy ORM
        session = self.SessionLocal()
        try:
            # Obtener el run_id: usar el proporcionado o buscar el más reciente
            if run_id is not None:
                # Validar que el run existe y pertenece al system_wallet_address
                run_stmt = (
                    select(Run)
                    .where(
                        Run.id == run_id,
                        Run.copy_trading_bots_id == system_wallet_address
                    )
                )
                run_result = session.execute(run_stmt)
                run = run_result.scalars().first()

                if not run:
                    raise ValueError(
                        f"No se encontró un run con id {run_id} para el system_wallet_address: {system_wallet_address}. "
                        f"Asegúrate de que el run existe y pertenece a este sistema."
                    )

                logger.info(f"Usando run especificado: {run_id} (started_at: {run.started_at})")
            else:
                # Obtener el run más reciente para el system_wallet_address
                latest_run_stmt = (
                    select(Run)
                    .where(Run.copy_trading_bots_id == system_wallet_address)
                    .order_by(Run.started_at.desc().nulls_last())
                    .limit(1)
                )

                latest_run_result = session.execute(latest_run_stmt)
                latest_run = latest_run_result.scalars().first()

                if not latest_run:
                    raise ValueError(
                        f"No se encontró un run para el system_wallet_address: {system_wallet_address}. "
                        f"Asegúrate de que existe al menos un run para este sistema."
                    )

                run_id = latest_run.id
                logger.info(f"Usando run más reciente: {run_id} (started_at: {latest_run.started_at})")

            # Query base con JOINs
            # Usar TraderTradeData.signature y TraderTradeData.created_at
            stmt = (
                select(
                    Position.side,
                    Position.traders_id,
                    TraderTradeData.signature,
                    TraderTradeData.created_at,
                    TraderTradeData.token_amount,
                    TraderTradeData.sol_amount,
                    TraderTradeData.pool,
                    Mint.mint_address,
                    Mint.symbol,
                    Mint.name
                )
                .join(TraderTradeData, Position.id == TraderTradeData.positions_id)
                .join(Mint, Position.mints_id == Mint.mint_address)
            )

            # Aplicar filtros
            conditions = []

            # Filtrar por run_id (obligatorio)
            conditions.append(Position.runs_id == run_id)
            logger.debug(f"Filtrando por run_id: {run_id}")

            # Filtrar por trader_wallet (obligatorio)
            conditions.append(Position.traders_id == trader_wallet)
            logger.debug(f"Filtrando por trader_wallet: {trader_wallet[:8]}...")

            # Filtros de fecha usando TraderTradeData.created_at
            if start_date:
                # Asegurar timezone UTC
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=timezone.utc)
                else:
                    start_date = start_date.astimezone(timezone.utc)
                conditions.append(TraderTradeData.created_at >= start_date)

            if end_date:
                # Asegurar timezone UTC
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                else:
                    end_date = end_date.astimezone(timezone.utc)
                conditions.append(TraderTradeData.created_at <= end_date)

            # Aplicar todas las condiciones
            if conditions:
                stmt = stmt.where(and_(*conditions))

            # Ordenar por fecha usando TraderTradeData.created_at
            stmt = stmt.order_by(TraderTradeData.created_at.asc())

            # Aplicar límite
            if limit:
                stmt = stmt.limit(limit)

            # Ejecutar query
            result = session.execute(stmt)
            rows = result.fetchall()

            # Convertir a diccionarios para normalizar
            transactions_raw = []
            for row in rows:
                transactions_raw.append({
                    'signature': row.signature,  # De TraderTradeData
                    'side': row.side.value if hasattr(row.side, 'value') else str(row.side),
                    'created_at': row.created_at,  # De TraderTradeData
                    'token_amount': row.token_amount,
                    'sol_amount': row.sol_amount,
                    'pool': row.pool,
                    'mint_address': row.mint_address,
                    'symbol': row.symbol,
                    'name': row.name,
                    'traders_id': row.traders_id
                })

            # Normalizar todas las transacciones
            normalized = []
            for tx in transactions_raw:
                try:
                    normalized.append(self._normalize_transaction(tx))
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning(f"Error normalizando transacción: {e}. Omitiendo...")
                    continue

            self._transactions = normalized
            logger.info(
                f"Cargadas {len(self._transactions)} transacciones desde PumpPortal "
                f"(de {len(transactions_raw)} totales) para run {run_id} "
                f"y trader {trader_wallet[:8]}..."
            )

        finally:
            session.close()

    def _load_from_raw_query(self, query: str) -> List[SwapTransaction]:
        """
        Carga usando query SQL directa (para casos especiales).
        
        Args:
            query: Query SQL como string
        
        Returns:
            Lista de SwapTransaction normalizadas
        """
        session = self.SessionLocal()
        try:
            result = session.execute(text(query))
            rows = result.fetchall()

            # Convertir rows a dicts
            columns = result.keys()
            transactions_raw = [dict(zip(columns, row)) for row in rows]

            # Normalizar
            normalized = []
            for tx in transactions_raw:
                try:
                    normalized.append(self._normalize_transaction(tx))
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning(f"Error normalizando transacción: {e}. Omitiendo...")
                    continue

            logger.info(f"Cargadas {len(normalized)} transacciones desde query SQL directa")
            return normalized
        finally:
            session.close()

    def get_all(self) -> List[SwapTransaction]:
        """
        Obtiene todas las transacciones cargadas.
        
        Returns:
            Lista de SwapTransaction
        """
        return self._transactions.copy()

    def filter_by_date_range(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime]
    ) -> List[SwapTransaction]:
        """
        Filtra transacciones por rango de fechas.
        
        Args:
            start_date: Fecha de inicio (inclusive). Si es None, no filtra por inicio
            end_date: Fecha de fin (inclusive). Si es None, no filtra por fin
        
        Returns:
            Lista de SwapTransaction filtradas
        """
        filtered = []
        for tx in self._transactions:
            tx_dt = tx.block_timestamp

            # Asegurar que tx_dt sea datetime con timezone
            if isinstance(tx_dt, str):
                try:
                    iso_str = str(tx_dt).replace('Z', '+00:00')
                    tx_dt = datetime.fromisoformat(iso_str)
                    if tx_dt.tzinfo is None:
                        tx_dt = tx_dt.replace(tzinfo=timezone.utc)
                    else:
                        tx_dt = tx_dt.astimezone(timezone.utc)
                except (ValueError, AttributeError):
                    continue
            elif tx_dt.tzinfo is None:
                tx_dt = tx_dt.replace(tzinfo=timezone.utc)
            else:
                tx_dt = tx_dt.astimezone(timezone.utc)

            # Aplicar filtros
            if start_date is not None and tx_dt < start_date:
                continue
            if end_date is not None and tx_dt > end_date:
                continue

            filtered.append(tx)

        return filtered

    def _normalize_transaction(self, raw_transaction: Dict[str, Any]) -> SwapTransaction:
        """
        Convierte una transacción de PostgreSQL (Position + TraderTradeData) a SwapTransaction.
        
        Args:
            raw_transaction: Diccionario con datos de la query SQLAlchemy
        
        Returns:
            SwapTransaction normalizada
        
        Raises:
            ValueError: Si la transacción no tiene los campos requeridos
        """
        # Extraer side (puede venir como Enum Side o string)
        side_value = raw_transaction.get('side')
        if hasattr(side_value, 'value') and isinstance(side_value, Side):
            # Side enum: valores son "BUY" o "SELL", convertir a minúsculas
            side = side_value.value.lower()  # "BUY" -> "buy", "SELL" -> "sell"
        elif isinstance(side_value, str):
            side = side_value.lower()  # String, convertir a minúsculas
        else:
            side = str(side_value).lower()  # Otro tipo, convertir a string y luego minúsculas

        if side not in ['buy', 'sell']:
            raise ValueError(f"Side inválido: {side}. Debe ser 'buy' o 'sell'")

        # Extraer timestamp
        timestamp = raw_transaction.get('created_at')
        if isinstance(timestamp, str):
            block_timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        elif isinstance(timestamp, datetime):
            block_timestamp = timestamp
        else:
            raise ValueError(f"Timestamp inválido: {timestamp}")

        # Asegurar timezone UTC
        if block_timestamp.tzinfo is None:
            block_timestamp = block_timestamp.replace(tzinfo=timezone.utc)
        else:
            block_timestamp = block_timestamp.astimezone(timezone.utc)

        # Extraer información del token
        base_token_address = raw_transaction.get('mint_address')
        if not base_token_address:
            raise ValueError("mint_address es requerido")

        base_token_symbol = raw_transaction.get('symbol') or 'UNKNOWN'

        # Extraer cantidades
        sol_amount = Decimal(str(raw_transaction.get('sol_amount', 0)))
        token_amount = Decimal(str(raw_transaction.get('token_amount', 0)))

        # Validar que las cantidades sean positivas
        if sol_amount <= 0:
            raise ValueError(f"sol_amount debe ser positivo, obtenido: {sol_amount}")
        if token_amount <= 0:
            raise ValueError(f"token_amount debe ser positivo, obtenido: {token_amount}")

        # Extraer otros campos
        # Usar signature de TraderTradeData
        signature = raw_transaction.get('signature')
        if not signature:
            raise ValueError("signature es requerido (debe venir de TraderTradeData)")

        pool = raw_transaction.get('pool', 'PumpPortal')  # Nombre original del pool en PumpPortal

        # Obtener la dirección del exchange basándose en el pool
        exchange_address_from_pool = self._POOL_TO_ADDRESS.get(pool)

        # Normalizar usando el registro de exchanges
        # Si tenemos la dirección del pool, la usamos; si no, intentamos mapear por nombre
        exchange_address, exchange_internal_name = normalize_exchange(
            exchange_address=exchange_address_from_pool,
            exchange_name=pool if not exchange_address_from_pool else None
        )

        # block_number no está disponible en la DB, usar 0
        block_number = 0

        return SwapTransaction(
            signature=signature,
            block_number=block_number,
            block_timestamp=block_timestamp,
            side=cast(Literal['buy', 'sell'], side),
            base_token_address=base_token_address,
            base_token_symbol=base_token_symbol,
            sol_amount=sol_amount,
            token_amount=token_amount,
            exchange_address=exchange_address,
            exchange_name=exchange_internal_name,  # Nombre interno normalizado
            native_exchange_name=pool,  # Nombre original del pool en PumpPortal (para visualizaciones)
            source='pumpportal',
            raw_data=raw_transaction
        )
