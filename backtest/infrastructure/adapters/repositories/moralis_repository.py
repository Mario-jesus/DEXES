# -*- coding: utf-8 -*-
"""
Adaptador: Repositorio de transacciones de Moralis.

Implementa ITransactionRepository para cargar transacciones desde archivos
o datos en memoria usando el formato de Moralis.
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Dict, Any

from ....domain.ports.transaction_repository import ITransactionRepository
from ....domain.entities.transactions import SwapTransaction
from ....domain.services.exchange_registry import normalize_exchange

logger = logging.getLogger(__name__)

# Dirección del token SOL en Solana
SOL_TOKEN_ADDRESS = "So11111111111111111111111111111111111111112"


class MoralisTransactionRepository(ITransactionRepository):
    """
    Repositorio de transacciones para la fuente Moralis.
    
    Implementa ITransactionRepository cargando transacciones desde archivos JSON
    o datos en memoria en formato Moralis, convirtiéndolas al modelo SwapTransaction.
    """

    def __init__(self):
        """
        Inicializa el repositorio de Moralis.
        """
        self._transactions: List[SwapTransaction] = []
        logger.debug("MoralisTransactionRepository inicializado")

    def load_from_file(self, file_path: str) -> None:
        """
        Carga transacciones desde un archivo JSON de Moralis.
        
        Args:
            file_path: Ruta del archivo JSON a cargar
        
        Raises:
            FileNotFoundError: Si el archivo no existe
            ValueError: Si el formato del archivo es inválido
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"El archivo {file_path} no existe")

        logger.info(f"Cargando datos Moralis desde {file_path}...")

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("El archivo JSON debe contener una lista de páginas")

        # Extraer todas las transacciones de todas las páginas
        all_transactions = []
        for page in data:
            if isinstance(page, dict) and 'result' in page:
                all_transactions.extend(page.get('result', []))

        # Normalizar todas las transacciones
        normalized = []
        for tx in all_transactions:
            try:
                normalized.append(self._normalize_transaction(tx))
            except (ValueError, KeyError, TypeError) as e:
                logger.warning(f"Error normalizando transacción: {e}. Omitiendo...")
                continue

        self._transactions = normalized
        logger.info(
            f"Cargadas {len(self._transactions)} transacciones desde archivo Moralis "
            f"(de {len(all_transactions)} totales)"
        )

    def load_from_data(self, data: List[Dict[str, Any]]) -> None:
        """
        Carga transacciones desde datos en memoria (formato Moralis).
        
        Args:
            data: Lista de diccionarios con datos de transacciones de Moralis.
                    Puede ser lista de páginas (con 'result') o lista directa de transacciones.
        
        Raises:
            ValueError: Si el formato de los datos es inválido
        """
        logger.info("Cargando datos Moralis desde memoria...")

        if not data:
            logger.warning("No se proporcionaron datos")
            self._transactions = []
            return

        all_transactions: List[Dict[str, Any]] = []

        # Detectar formato: páginas o transacciones directas
        first_item = data[0] if data else None
        if isinstance(first_item, dict) and 'result' in first_item:
            # Lista de páginas
            for page in data:
                if isinstance(page, dict) and 'result' in page:
                    page_result = page.get('result', [])
                    if isinstance(page_result, list):
                        all_transactions.extend(page_result)
        else:
            # Lista directa de transacciones
            for item in data:
                if isinstance(item, dict):
                    all_transactions.append(item)

        # Normalizar todas las transacciones
        normalized = []
        for tx in all_transactions:
            try:
                normalized.append(self._normalize_transaction(tx))
            except (ValueError, KeyError, TypeError) as e:
                logger.warning(f"Error normalizando transacción: {e}. Omitiendo...")
                continue

        self._transactions = normalized
        logger.info(
            f"Cargadas {len(self._transactions)} transacciones desde datos Moralis "
            f"(de {len(all_transactions)} totales)"
        )

    def load_from_database(
        self,
        system_wallet_address: str,
        trader_wallet: str,
        run_id: Optional[Any] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None,
        **kwargs
    ) -> None:
        """
        No soportado para Moralis.
        
        Raises:
            NotImplementedError: Moralis no soporta carga desde base de datos
        """
        raise NotImplementedError(
            "MoralisTransactionRepository no soporta carga desde base de datos. "
            "Usa load_from_file() o load_from_data() según corresponda."
        )

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
        Convierte una transacción Moralis a SwapTransaction.
        
        Mapea campos de Moralis al modelo SwapTransaction:
        - transactionType -> side ('buy' o 'sell')
        - baseToken -> base_token_address
        - blockTimestamp -> block_timestamp (datetime)
        - transactionHash -> signature
        - blockNumber -> block_number
        - bought/sold -> sol_amount y token_amount
        
        Args:
            raw_transaction: Diccionario con datos raw de Moralis
        
        Returns:
            SwapTransaction normalizada
        
        Raises:
            ValueError: Si la transacción no tiene los campos requeridos
        """
        # Extraer tipo (transactionType -> side)
        tx_type = raw_transaction.get('transactionType', '').lower()
        if tx_type not in ['buy', 'sell']:
            raise ValueError(f"transactionType inválido: {tx_type}. Debe ser 'buy' o 'sell'")

        # Extraer timestamp
        timestamp_str = raw_transaction.get('blockTimestamp', '')
        if not timestamp_str:
            raise ValueError("blockTimestamp es requerido")

        try:
            # Normalizar formato ISO (reemplazar Z por +00:00)
            iso_str = timestamp_str.replace('Z', '+00:00')
            block_timestamp = datetime.fromisoformat(iso_str)
            # Asegurar timezone UTC si es naive
            if block_timestamp.tzinfo is None:
                block_timestamp = block_timestamp.replace(tzinfo=timezone.utc)
            else:
                block_timestamp = block_timestamp.astimezone(timezone.utc)
        except (ValueError, AttributeError) as e:
            raise ValueError(f"blockTimestamp inválido: {timestamp_str}. Error: {e}")

        # Extraer información del token base
        base_token_address = raw_transaction.get('baseToken')
        if not base_token_address:
            raise ValueError("baseToken es requerido")

        # Extraer cantidades según el tipo de transacción
        if tx_type == 'buy':
            # En compra: se vende SOL, se compran tokens
            sol_data = raw_transaction.get('sold', {})
            token_data = raw_transaction.get('bought', {})
        else:  # sell
            # En venta: se venden tokens, se recibe SOL
            sol_data = raw_transaction.get('bought', {})
            token_data = raw_transaction.get('sold', {})

        # Validar y extraer SOL
        if not sol_data:
            raise ValueError("No se encontraron datos de SOL en la transacción")

        sol_address = sol_data.get('address')
        if sol_address != SOL_TOKEN_ADDRESS:
            raise ValueError(
                f"Dirección SOL no coincide. Esperado: {SOL_TOKEN_ADDRESS}, "
                f"obtenido: {sol_address}"
            )

        sol_amount_str = sol_data.get('amount')
        if sol_amount_str is None:
            raise ValueError("No se encontró amount de SOL")

        try:
            sol_amount = Decimal(str(sol_amount_str))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Amount de SOL inválido: {sol_amount_str}. Error: {e}")

        # Extraer tokens
        if not token_data:
            raise ValueError("No se encontraron datos de tokens en la transacción")

        token_amount_str = token_data.get('amount')
        if token_amount_str is None:
            raise ValueError("No se encontró amount de tokens")

        try:
            token_amount = Decimal(str(token_amount_str))
        except (ValueError, TypeError) as e:
            raise ValueError(f"Amount de tokens inválido: {token_amount_str}. Error: {e}")

        token_symbol = token_data.get('symbol', 'UNKNOWN')

        # Extraer otros campos
        signature = raw_transaction.get('transactionHash', '')
        block_number = raw_transaction.get('blockNumber', 0)
        source_exchange_name = raw_transaction.get('exchangeName')  # Nombre original de Moralis

        # Intentar obtener la dirección del exchange desde los datos de Moralis
        source_exchange_address = (
            raw_transaction.get('exchangeAddress') or 
            raw_transaction.get('programId') or
            None
        )

        # Normalizar usando el registro de exchanges
        exchange_address, exchange_internal_name = normalize_exchange(
            exchange_address=source_exchange_address,
            exchange_name=source_exchange_name
        )

        return SwapTransaction(
            signature=signature,
            block_number=block_number,
            block_timestamp=block_timestamp,
            side=tx_type,  # 'buy' o 'sell'
            base_token_address=base_token_address,
            base_token_symbol=token_symbol,
            sol_amount=sol_amount,
            token_amount=token_amount,
            exchange_address=exchange_address,
            exchange_name=exchange_internal_name,  # Nombre interno normalizado
            native_exchange_name=source_exchange_name,  # Nombre original de la fuente
            source='moralis',
            raw_data=raw_transaction  # Para debugging y validación
        )
