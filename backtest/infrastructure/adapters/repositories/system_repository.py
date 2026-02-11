# -*- coding: utf-8 -*-
"""
Adaptador: Repositorio de transacciones del Sistema.

Implementa ITransactionRepository para cargar transacciones desde PostgreSQL
usando datos del sistema de trading almacenados en la base de datos.
"""
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Dict, Any, Literal, cast

from sqlalchemy import create_engine, select, and_, or_, text
from sqlalchemy.orm import sessionmaker

from ....domain.ports.transaction_repository import ITransactionRepository
from ....domain.entities.transactions import SwapTransaction
from ....domain.services.exchange_registry import normalize_exchange

# Importar modelos ORM
from copy_trading.persistence.orm.models import (
    Position, 
    OpenPosition, 
    CloseOrder, 
    TraderTradeData,
    Mint, 
    Run
)
from copy_trading.persistence.orm.enums import Side

logger = logging.getLogger(__name__)


class SystemTransactionRepository(ITransactionRepository):
    """
    Repositorio de transacciones para la fuente System.
    
    Implementa ITransactionRepository cargando transacciones desde PostgreSQL
    usando SQLAlchemy ORM, accediendo a las tablas positions, open_positions, 
    close_orders, trader_trade_data y mints que almacenan información de trades
    ejecutados por el sistema de copy trading.
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
        Inicializa el repositorio del Sistema.
        
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
        logger.debug("SystemTransactionRepository inicializado")

    def load_from_file(self, file_path: str) -> None:
        """
        No soportado para System.
        
        Raises:
            NotImplementedError: System solo soporta carga desde base de datos
        """
        raise NotImplementedError(
            "SystemTransactionRepository no soporta carga desde archivos. "
            "Usa load_from_database() según corresponda."
        )

    def load_from_data(self, data: List[Dict[str, Any]]) -> None:
        """
        No soportado para System.
        
        Raises:
            NotImplementedError: System solo soporta carga desde base de datos
        """
        raise NotImplementedError(
            "SystemTransactionRepository no soporta carga desde memoria. "
            "Usa load_from_database() según corresponda."
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
        query: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Carga transacciones desde PostgreSQL usando SQLAlchemy ORM.
        
        Filtra las transacciones por el run especificado o el más reciente del system_wallet_address
        y por la wallet del trader.
        
        Args:
            system_wallet_address: Dirección de wallet del sistema (copy_trading_bots_id) - OBLIGATORIO
            trader_wallet: Wallet address del trader - OBLIGATORIO
            run_id: ID del run a usar (opcional). Si no se proporciona, se usa el más reciente
            start_date: Fecha de inicio para filtrar (opcional). Usa Position.created_at
            end_date: Fecha de fin para filtrar (opcional). Usa Position.created_at
            include_liquidations: Si True, incluye posiciones de liquidación (por defecto False)
            limit: Límite de registros a cargar (opcional)
            query: Query SQL personalizada (opcional). Si se proporciona, se usa esta en lugar de ORM
            **kwargs: Parámetros adicionales
        
        Raises:
            ValueError: Si no se encuentra un run para el system_wallet_address especificado
        """
        logger.info(
            f"Cargando datos del sistema desde PostgreSQL para system_wallet: {system_wallet_address[:8]}... "
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
            # Para BUY: usar OpenPosition
            # Para SELL: usar CloseOrder
            # Para pool: usar TraderTradeData
            stmt = (
                select(
                    Position.id,
                    Position.side,
                    Position.traders_id,
                    Position.signature,
                    Position.created_at,
                    Position.runs_id,
                    Mint.mint_address,
                    Mint.symbol,
                    Mint.name,
                    OpenPosition.sol_amount_sent,
                    OpenPosition.sol_amount_executed,
                    OpenPosition.token_amount_received,
                    CloseOrder.token_amount_sent,
                    CloseOrder.sol_amount_received,
                    TraderTradeData.pool,
                )
                .join(Mint, Position.mints_id == Mint.mint_address)
                .outerjoin(OpenPosition, Position.id == OpenPosition.positions_id)
                .outerjoin(CloseOrder, Position.id == CloseOrder.positions_id)
                .outerjoin(TraderTradeData, Position.id == TraderTradeData.positions_id)
            )

            # Aplicar filtros
            conditions = []

            # Filtrar por run_id (obligatorio)
            conditions.append(Position.runs_id == run_id)
            logger.debug(f"Filtrando por run_id: {run_id}")

            # Filtrar por trader_wallet y liquidaciones según el parámetro
            if include_liquidations:
                # Incluir posiciones del trader O liquidaciones (donde traders_id es NULL)
                conditions.append(
                    or_(
                        Position.traders_id == trader_wallet,
                        Position.is_liquidation == True
                    )
                )
                logger.debug(f"Incluyendo posiciones del trader {trader_wallet[:8]}... y liquidaciones")
            else:
                # Solo posiciones del trader (excluir liquidaciones)
                conditions.append(Position.traders_id == trader_wallet)
                conditions.append(Position.is_liquidation == False)
                logger.debug(f"Filtrando por trader_wallet: {trader_wallet[:8]}... (excluyendo liquidaciones)")

            # Filtros de fecha usando Position.created_at
            if start_date:
                # Asegurar timezone UTC
                if start_date.tzinfo is None:
                    start_date = start_date.replace(tzinfo=timezone.utc)
                else:
                    start_date = start_date.astimezone(timezone.utc)
                conditions.append(Position.created_at >= start_date)

            if end_date:
                # Asegurar timezone UTC
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                else:
                    end_date = end_date.astimezone(timezone.utc)
                conditions.append(Position.created_at <= end_date)

            # Aplicar todas las condiciones
            if conditions:
                stmt = stmt.where(and_(*conditions))

            # Ordenar por fecha usando Position.created_at
            stmt = stmt.order_by(Position.created_at.asc())

            # Aplicar límite
            if limit:
                stmt = stmt.limit(limit)

            # Ejecutar query
            result = session.execute(stmt)
            rows = result.fetchall()

            # Convertir a diccionarios para normalizar
            transactions_raw = []
            for row in rows:
                # Determinar si es BUY o SELL y obtener los datos correspondientes
                side_value = row.side.value if hasattr(row.side, 'value') else str(row.side)
                side = side_value.lower()

                if side == 'buy':
                    # Para BUY: usar datos de OpenPosition
                    sol_amount = row.sol_amount_executed or row.sol_amount_sent or Decimal('0')
                    token_amount = row.token_amount_received or Decimal('0')
                elif side == 'sell':
                    # Para SELL: usar datos de CloseOrder
                    sol_amount = row.sol_amount_received or Decimal('0')
                    token_amount = row.token_amount_sent or Decimal('0')
                else:
                    logger.warning(f"Side desconocido: {side}, omitiendo posición {row.id}")
                    continue

                # Validar que tengamos datos válidos
                if sol_amount <= 0 or token_amount <= 0:
                    logger.warning(
                        f"Posición {row.id} tiene cantidades inválidas: "
                        f"sol={sol_amount}, tokens={token_amount}, omitiendo..."
                    )
                    continue

                # Usar signature de Position (obligatorio)
                signature = row.signature or f"system-{row.id}"

                # Usar created_at de Position
                created_at = row.created_at

                transactions_raw.append({
                    'signature': signature,
                    'side': side,
                    'created_at': created_at,
                    'token_amount': token_amount,
                    'sol_amount': sol_amount,
                    'mint_address': row.mint_address,
                    'symbol': row.symbol,
                    'name': row.name,
                    'traders_id': row.traders_id,
                    'position_id': str(row.id),
                    'pool': row.pool  # De TraderTradeData (solo para obtener el pool)
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
                f"Cargadas {len(self._transactions)} transacciones del sistema "
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
        Convierte una transacción del sistema a SwapTransaction.
        
        Args:
            raw_transaction: Diccionario con datos de la query SQLAlchemy
        
        Returns:
            SwapTransaction normalizada
        
        Raises:
            ValueError: Si la transacción no tiene los campos requeridos
        """
        # Extraer side
        side_value = raw_transaction.get('side')
        if isinstance(side_value, Side):
            side = side_value.value.lower()  # "BUY" -> "buy", "SELL" -> "sell"
        elif isinstance(side_value, str):
            side = side_value.lower()
        else:
            side = str(side_value).lower()

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

        # Extraer signature
        signature = raw_transaction.get('signature')
        if not signature:
            # Generar signature basado en position_id si no hay signature
            position_id = raw_transaction.get('position_id')
            if position_id:
                signature = f"system-{position_id}"
            else:
                raise ValueError("signature o position_id es requerido")

        # Obtener pool de TraderTradeData
        pool = raw_transaction.get('pool')  # Nombre original del pool en TraderTradeData
        if pool is None:
            if base_token_address[-4:] == "pump":
                pool = "pump"
            elif base_token_address[-4:] == "bonk":
                pool = "bonk"
            else:
                pool = "pump-amm"

        # Obtener la dirección del exchange basándose en el pool
        exchange_address_from_pool = self._POOL_TO_ADDRESS.get(pool) if pool else None

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
            native_exchange_name=pool,  # Nombre original del pool en TraderTradeData (para visualizaciones)
            source='system',
            raw_data=raw_transaction
        )
