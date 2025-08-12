# -*- coding: utf-8 -*-
"""
Sistema de gestión de posiciones cerradas para Copy Trading.
Utiliza una cola de posiciones por trader y por token para historial y análisis.
"""
import aiofiles
import json
import asyncio
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal, getcontext
from datetime import datetime, timedelta

from logging_system import AppLogger
from ..models import OpenPosition, PositionStatus

getcontext().prec = 26


class ClosedPositionQueue:
    """Gestión de posiciones cerradas con persistencia, agrupadas por trader y luego por token para historial y análisis."""

    def __init__(self, data_path: str = "copy_trading/data", max_size: Optional[int] = None):
        self.data_path = Path(data_path)
        self.max_size = max_size
        self._logger = AppLogger(self.__class__.__name__)

        # Cola principal: Diccionario anidado [trader_wallet -> token_address -> deque]
        self.closed_positions_queue: Dict[str, Dict[str, deque[OpenPosition]]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=self.max_size)))

        self._lock = asyncio.Lock()

        self.data_path.mkdir(parents=True, exist_ok=True)
        self.closed_file = self.data_path / "closed_positions.json"
        self._initialize_files()

        self._logger.debug(f"ClosedPositionQueue inicializado - Data path: {self.data_path}, Max size: {self.max_size}")

    async def __aenter__(self):
        self._logger.debug("Iniciando carga de posiciones cerradas desde disco")
        await self.load_from_disk()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            await self.stop()
            self._logger.debug("ClosedPositionQueue cerrado con async context manager")
        except Exception as e:
            self._logger.error(f"Error cerrando ClosedPositionQueue: {e}")

    async def add_closed_position(self, position: OpenPosition) -> bool:
        """
        Agrega una posición cerrada al historial.
        
        Args:
            position: Posición que se ha cerrado completamente
            
        Returns:
            True si se agregó exitosamente, False en caso contrario
        """
        try:
            async with self._lock:
                # Verificar que la posición esté realmente cerrada
                if position.status != PositionStatus.CLOSED:
                    self._logger.warning(f"Posición {position.id} no está cerrada (status: {position.status})")
                    return False

                trader_token_queue = self.closed_positions_queue[position.trader_wallet][position.token_address]

                if any(p.id == position.id for p in trader_token_queue):
                    self._logger.warning(f"Posición cerrada {position.id} ya existe en el historial para el trader {position.trader_wallet} y token {position.token_address}.")
                    return False

                trader_token_queue.append(position)

                self._logger.info(f"Posición cerrada {position.id} agregada al historial")

                await self._save_closed()
                return True
        except Exception as e:
            self._logger.error(f"Error agregando posición cerrada {position.id}: {e}")
            return False

    async def get_closed_positions(self, trader_address: Optional[str] = None, token_address: Optional[str] = None, _lock_acquired: bool = False) -> List[OpenPosition]:
        """
        Obtiene posiciones cerradas con filtros opcionales.
        
        Args:
            trader_address: Wallet del trader (opcional)
            token_address: Dirección del token (opcional)
            _lock_acquired: Indica si el lock ya está adquirido (para uso interno)
            
        Returns:
            Lista de posiciones cerradas
        """
        try:
            if not _lock_acquired:
                async with self._lock:
                    positions = await self._get_closed_positions_internal(trader_address, token_address)
                    self._logger.debug(f"Obtenidas {len(positions)} posiciones cerradas")
                    return positions
            else:
                positions = await self._get_closed_positions_internal(trader_address, token_address)
                self._logger.debug(f"Obtenidas {len(positions)} posiciones cerradas (lock ya adquirido)")
                return positions

        except Exception as e:
            self._logger.error(f"Error en get_closed_positions: {e}")
            raise

    async def _get_closed_positions_internal(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> List[OpenPosition]:
        """Método interno que asume que el lock ya está adquirido."""
        try:
            if trader_address and token_address:
                return list(self.closed_positions_queue.get(trader_address, {}).get(token_address, deque()))

            if trader_address:
                trader_positions = []
                trader_tokens = self.closed_positions_queue.get(trader_address, {})
                for token_addr, queue in trader_tokens.items():
                    trader_positions.extend(queue)
                return trader_positions

            # Caso 3: todas las posiciones cerradas
            all_positions = []
            for trader_wallet, tokens in self.closed_positions_queue.items():
                for token_addr, queue in tokens.items():
                    all_positions.extend(queue)

            return all_positions
        except Exception as e:
            self._logger.error(f"Error en _get_closed_positions_internal: {e}")
            return []

    async def get_closed_positions_by_date_range(self, start_date: datetime, end_date: datetime, trader_address: Optional[str] = None) -> List[OpenPosition]:
        """
        Obtiene posiciones cerradas dentro de un rango de fechas.
        
        Args:
            start_date: Fecha de inicio del rango
            end_date: Fecha de fin del rango
            trader_address: Wallet del trader (opcional)
            
        Returns:
            Lista de posiciones cerradas en el rango de fechas
        """
        try:
            async with self._lock:
                all_positions = await self.get_closed_positions(trader_address, _lock_acquired=True)

                filtered_positions = []
                for position in all_positions:
                    # Buscar la fecha de cierre en el historial
                    closed_date = None
                    for close_item in position.close_history:
                        if hasattr(close_item, 'created_at'):
                            closed_date = close_item.created_at
                            break

                    # Si no hay fecha de cierre, usar la fecha de creación
                    if not closed_date:
                        closed_date = position.created_at

                    if start_date <= closed_date <= end_date:
                        filtered_positions.append(position)

                self._logger.debug(f"Filtradas {len(filtered_positions)} posiciones cerradas en rango de fechas")
                return filtered_positions
        except Exception as e:
            self._logger.error(f"Error obteniendo posiciones por rango de fechas: {e}")
            return []

    async def get_position_by_id(self, position_id: str) -> Optional[OpenPosition]:
        """
        Busca una posición cerrada por ID.
        
        Args:
            position_id: ID de la posición a buscar
            
        Returns:
            La posición encontrada o None
        """
        try:
            async with self._lock:
                position, _, _ = await self._find_position_in_queue(position_id)
                if position:
                    self._logger.debug(f"Posición cerrada encontrada por ID: {position_id}")
                else:
                    self._logger.debug(f"Posición cerrada no encontrada por ID: {position_id}")
                return position
        except Exception as e:
            self._logger.error(f"Error buscando posición cerrada por ID {position_id}: {e}")
            return None

    async def _find_position_in_queue(self, position_id: str) -> Tuple[Optional[OpenPosition], Optional[str], Optional[str]]:
        """Helper para encontrar una posición y sus claves asociadas (trader, token)."""
        try:
            for trader_wallet, tokens in self.closed_positions_queue.items():
                for token_address, queue in tokens.items():
                    for position in queue:
                        if position.id == position_id:
                            return position, trader_wallet, token_address
            return None, None, None
        except Exception as e:
            self._logger.error(f"Error buscando posición {position_id} en cola cerrada: {e}")
            return None, None, None

    async def get_queue_size(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> int:
        """
        Obtiene el tamaño de la cola de posiciones cerradas.
        
        Args:
            trader_address: Wallet del trader (opcional)
            token_address: Dirección del token (opcional)
            
        Returns:
            Número de posiciones cerradas en la cola
        """
        try:
            async with self._lock:
                if trader_address and token_address:
                    size = len(self.closed_positions_queue.get(trader_address, {}).get(token_address, deque()))
                    self._logger.debug(f"Tamaño de cola cerrada para trader {trader_address} y token {token_address}: {size}")
                    return size

                elif trader_address:
                    total_size = 0
                    for queue in self.closed_positions_queue.get(trader_address, {}).values():
                        total_size += len(queue)
                    self._logger.debug(f"Tamaño total de cola cerrada para trader {trader_address}: {total_size}")
                    return total_size

                else:
                    total_size = 0
                    for tokens in self.closed_positions_queue.values():
                        for queue in tokens.values():
                            total_size += len(queue)
                    self._logger.debug(f"Tamaño total de cola cerrada general: {total_size}")
                    return total_size
        except Exception as e:
            self._logger.error(f"Error obteniendo tamaño de cola cerrada: {e}")
            return 0

    async def get_pnl_statistics(self, trader_address: Optional[str] = None, token_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Obtiene estadísticas de PnL de posiciones cerradas.
        
        Args:
            trader_address: Wallet del trader (opcional)
            token_address: Dirección del token (opcional)
            
        Returns:
            Diccionario con estadísticas de PnL
        """
        try:
            async with self._lock:
                positions = await self.get_closed_positions(trader_address, token_address, _lock_acquired=True)

                total_positions = len(positions)
                profitable_positions = 0
                total_pnl_sol = Decimal('0')
                total_pnl_usd = Decimal('0')
                total_volume_sol = Decimal('0')
                total_volume_usd = Decimal('0')

                for position in positions:
                    # Calcular volumen
                    volume_sol = Decimal(position.amount_sol) if position.amount_sol else Decimal('0')
                    total_volume_sol += volume_sol

                    # Calcular PnL (asumiendo que está en metadata o se puede calcular)
                    pnl_sol = Decimal('0')
                    pnl_usd = Decimal('0')

                    # Intentar obtener PnL de metadata
                    if 'pnl_sol' in position.metadata:
                        pnl_sol = Decimal(str(position.metadata['pnl_sol']))
                    if 'pnl_usd' in position.metadata:
                        pnl_usd = Decimal(str(position.metadata['pnl_usd']))

                    total_pnl_sol += pnl_sol
                    total_pnl_usd += pnl_usd

                    if pnl_sol > 0:
                        profitable_positions += 1

                win_rate = (profitable_positions / total_positions * 100) if total_positions > 0 else 0

                stats = {
                    'total_positions': total_positions,
                    'profitable_positions': profitable_positions,
                    'win_rate_percent': float(win_rate),
                    'total_pnl_sol': str(total_pnl_sol),
                    'total_pnl_usd': str(total_pnl_usd),
                    'total_volume_sol': str(total_volume_sol),
                    'total_volume_usd': str(total_volume_usd),
                    'average_pnl_sol': str(total_pnl_sol / total_positions) if total_positions > 0 else '0',
                    'average_pnl_usd': str(total_pnl_usd / total_positions) if total_positions > 0 else '0'
                }

                self._logger.info(f"Estadísticas PnL calculadas: {total_positions} posiciones, {profitable_positions} rentables")
                return stats
        except Exception as e:
            self._logger.error(f"Error calculando estadísticas PnL: {e}")
            return {}

    async def get_trading_performance_by_period(self, period_days: int = 30, trader_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Obtiene rendimiento de trading por período.
        
        Args:
            period_days: Número de días para el período
            trader_address: Wallet del trader (opcional)
            
        Returns:
            Diccionario con estadísticas del período
        """
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=period_days)

            positions = await self.get_closed_positions_by_date_range(start_date, end_date, trader_address)

            if not positions:
                self._logger.debug(f"No hay posiciones cerradas en el período de {period_days} días")
                return {
                    'period_days': period_days,
                    'total_positions': 0,
                    'total_pnl_sol': '0',
                    'total_pnl_usd': '0',
                    'win_rate_percent': 0.0
                }

            # Calcular estadísticas del período
            total_positions = len(positions)
            profitable_positions = 0
            total_pnl_sol = Decimal('0')
            total_pnl_usd = Decimal('0')

            for position in positions:
                pnl_sol = Decimal('0')
                pnl_usd = Decimal('0')

                if 'pnl_sol' in position.metadata:
                    pnl_sol = Decimal(str(position.metadata['pnl_sol']))
                if 'pnl_usd' in position.metadata:
                    pnl_usd = Decimal(str(position.metadata['pnl_usd']))

                total_pnl_sol += pnl_sol
                total_pnl_usd += pnl_usd

                if pnl_sol > 0:
                    profitable_positions += 1

            win_rate = (profitable_positions / total_positions * 100) if total_positions > 0 else 0

            stats = {
                'period_days': period_days,
                'total_positions': total_positions,
                'profitable_positions': profitable_positions,
                'win_rate_percent': float(win_rate),
                'total_pnl_sol': str(total_pnl_sol),
                'total_pnl_usd': str(total_pnl_usd),
                'average_pnl_sol': str(total_pnl_sol / total_positions) if total_positions > 0 else '0',
                'average_pnl_usd': str(total_pnl_usd / total_positions) if total_positions > 0 else '0'
            }

            self._logger.info(f"Rendimiento por período calculado: {period_days} días, {total_positions} posiciones")
            return stats
        except Exception as e:
            self._logger.error(f"Error calculando rendimiento por período: {e}")
            return {}

    async def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas generales de posiciones cerradas.
        
        Returns:
            Diccionario con estadísticas generales
        """
        try:
            async with self._lock:
                all_positions = await self.get_closed_positions(_lock_acquired=True)
                
                total_closed_value = sum(float(p.amount_sol) for p in all_positions if p.amount_sol)
                unique_traders = len(self.closed_positions_queue)
                unique_tokens = len(set(pos.token_address for pos in all_positions))

                stats = {
                    'closed_count': len(all_positions),
                    'total_closed_value_sol': total_closed_value,
                    'unique_traders': unique_traders,
                    'unique_tokens': unique_tokens,
                }

                self._logger.info(f"Estadísticas generales: {len(all_positions)} posiciones cerradas")
                return stats

        except Exception as e:
            self._logger.error(f"Error en get_stats: {e}")
            raise

    async def load_from_disk(self):
        """Carga posiciones cerradas desde el disco."""
        try:
            async with self._lock:
                if not self.closed_file.exists():
                    self._logger.debug("Archivo de posiciones cerradas no existe, iniciando con cola vacía")
                    return

                self._logger.debug(f"Cargando posiciones cerradas desde {self.closed_file}")
                async with aiofiles.open(self.closed_file, 'r') as f:
                    content = await f.read()
                    if content.strip():
                        data: Dict[str, Dict[str, List[Dict]]] = json.loads(content)
                        self.closed_positions_queue.clear()
                        total_positions = 0
                        for trader_wallet, tokens_data in data.items():
                            for token_address, positions_data in tokens_data.items():
                                trader_token_deque = deque(maxlen=self.max_size)
                                for pos_data in positions_data:
                                    trader_token_deque.append(OpenPosition.from_dict(pos_data))
                                    total_positions += 1
                                self.closed_positions_queue[trader_wallet][token_address] = trader_token_deque

                        self._logger.debug(f"Cargadas {total_positions} posiciones cerradas desde disco")
                    else:
                        self._logger.debug("Archivo de posiciones cerradas está vacío")
        except (json.JSONDecodeError, Exception) as e:
            self._logger.warning(f"Error cargando closed_positions.json: {e}")

    async def save_state(self):
        """Guarda el estado de posiciones cerradas."""
        try:
            self._logger.debug("Guardando estado de posiciones cerradas")
            await self._save_closed()
        except Exception as e:
            self._logger.error(f"Error guardando estado de posiciones cerradas: {e}")

    async def _save_closed(self):
        """Guarda posiciones cerradas al disco de forma asíncrona."""
        try:
            data_to_save = defaultdict(dict)
            total_positions = 0
            for trader_wallet, tokens in self.closed_positions_queue.items():
                for token_address, queue in tokens.items():
                    if queue:  # Solo guardar si la cola no está vacía
                        posiciones_dict = [p.to_dict() for p in queue]
                        data_to_save[trader_wallet][token_address] = posiciones_dict
                        total_positions += len(queue)

            async with aiofiles.open(self.closed_file, 'w') as f:
                await f.write(json.dumps(data_to_save, indent=2))

            self._logger.debug(f"Posiciones cerradas guardadas: {total_positions} posiciones")
        except Exception as e:
            self._logger.error(f"Error guardando posiciones cerradas en {self.closed_file}: {e}")
            raise

    def _initialize_files(self):
        """Inicializa el archivo de posiciones cerradas si no existe."""
        try:
            if not self.closed_file.exists() or self.closed_file.stat().st_size == 0:
                with open(self.closed_file, 'w') as f:
                    f.write('{}')  # Inicializar como un objeto JSON vacío
                self._logger.debug(f"Archivo {self.closed_file.name} inicializado")
        except Exception as e:
            self._logger.error(f"Error inicializando {self.closed_file.name}: {e}")

    async def stop(self) -> None:
        """Detiene el worker y guarda el estado final."""
        try:
            self._logger.info("Deteniendo ClosedPositionQueue")
            # Guardar estado final
            await self.save_state()
            self._logger.debug("ClosedPositionQueue detenido exitosamente")
        except Exception as e:
            self._logger.error(f"Error durante la detención: {e}")
            raise
