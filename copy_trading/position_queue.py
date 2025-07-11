# -*- coding: utf-8 -*-
"""
Sistema de cola de posiciones FIFO para Copy Trading Mini
"""
import aiofiles
import json
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Callable
from enum import Enum
from pathlib import Path
from collections import deque


class PositionSide(Enum):
    """Lado de la posición"""
    BUY = "buy"
    SELL = "sell"


class PositionStatus(Enum):
    """Estado de la posición"""
    PENDING = "pending"          # En cola esperando ejecución
    EXECUTING = "executing"      # Ejecutándose
    OPEN = "open"               # Abierta y activa
    CLOSING = "closing"         # En proceso de cierre
    CLOSED = "closed"           # Cerrada
    FAILED = "failed"           # Falló la ejecución
    CANCELLED = "cancelled"     # Cancelada


@dataclass
class Position:
    """Representa una posición en el sistema"""

    # Identificación
    id: str
    trader_wallet: str
    token_address: str
    token_symbol: str = ""

    # Detalles de la posición
    side: PositionSide = PositionSide.BUY
    amount_sol: float = 0.0
    amount_tokens: float = 0.0
    entry_price: float = 0.0

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    # Estado
    status: PositionStatus = PositionStatus.PENDING

    # Ejecución
    execution_signature: Optional[str] = None
    execution_price: Optional[float] = None
    slippage: Optional[float] = None

    # Cierre
    close_signature: Optional[str] = None
    close_price: Optional[float] = None
    close_amount_sol: Optional[float] = None

    # P&L
    realized_pnl_sol: Optional[float] = None
    realized_pnl_usd: Optional[float] = None
    unrealized_pnl_sol: Optional[float] = None
    unrealized_pnl_usd: Optional[float] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def calculate_pnl(self, current_price: float, sol_price_usd: float = 150.0) -> Tuple[float, float]:
        """
        Calcula P&L actual
        
        Returns:
            Tuple de (pnl_sol, pnl_usd)
        """
        if self.status not in [PositionStatus.OPEN, PositionStatus.CLOSED]:
            return 0.0, 0.0

        if self.side == PositionSide.BUY:
            # Para compras
            if self.status == PositionStatus.OPEN:
                # P&L no realizado
                current_value = self.amount_tokens * current_price
                pnl_sol = current_value - self.amount_sol
                pnl_usd = pnl_sol * sol_price_usd
                self.unrealized_pnl_sol = pnl_sol
                self.unrealized_pnl_usd = pnl_usd
            else:
                # P&L realizado
                if self.close_amount_sol:
                    pnl_sol = self.close_amount_sol - self.amount_sol
                    pnl_usd = pnl_sol * sol_price_usd
                    self.realized_pnl_sol = pnl_sol
                    self.realized_pnl_usd = pnl_usd
                else:
                    pnl_sol = pnl_usd = 0.0
        else:
            # Para ventas (ya realizadas)
            pnl_sol = self.amount_sol
            pnl_usd = pnl_sol * sol_price_usd
            self.realized_pnl_sol = pnl_sol
            self.realized_pnl_usd = pnl_usd

        return pnl_sol, pnl_usd

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        return {
            'id': self.id,
            'trader_wallet': self.trader_wallet,
            'token_address': self.token_address,
            'token_symbol': self.token_symbol,
            'side': self.side.value,
            'amount_sol': self.amount_sol,
            'amount_tokens': self.amount_tokens,
            'entry_price': self.entry_price,
            'created_at': self.created_at.isoformat(),
            'executed_at': self.executed_at.isoformat() if self.executed_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'status': self.status.value,
            'execution_signature': self.execution_signature,
            'execution_price': self.execution_price,
            'slippage': self.slippage,
            'close_signature': self.close_signature,
            'close_price': self.close_price,
            'close_amount_sol': self.close_amount_sol,
            'realized_pnl_sol': self.realized_pnl_sol,
            'realized_pnl_usd': self.realized_pnl_usd,
            'unrealized_pnl_sol': self.unrealized_pnl_sol,
            'unrealized_pnl_usd': self.unrealized_pnl_usd,
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
        """Crea desde diccionario"""
        return cls(
            id=data['id'],
            trader_wallet=data['trader_wallet'],
            token_address=data['token_address'],
            token_symbol=data.get('token_symbol', ''),
            side=PositionSide(data['side']),
            amount_sol=data['amount_sol'],
            amount_tokens=data.get('amount_tokens', 0.0),
            entry_price=data.get('entry_price', 0.0),
            created_at=datetime.fromisoformat(data['created_at']),
            executed_at=datetime.fromisoformat(data['executed_at']) if data.get('executed_at') else None,
            closed_at=datetime.fromisoformat(data['closed_at']) if data.get('closed_at') else None,
            status=PositionStatus(data['status']),
            execution_signature=data.get('execution_signature'),
            execution_price=data.get('execution_price'),
            slippage=data.get('slippage'),
            close_signature=data.get('close_signature'),
            close_price=data.get('close_price'),
            close_amount_sol=data.get('close_amount_sol'),
            realized_pnl_sol=data.get('realized_pnl_sol'),
            realized_pnl_usd=data.get('realized_pnl_usd'),
            unrealized_pnl_sol=data.get('unrealized_pnl_sol'),
            unrealized_pnl_usd=data.get('unrealized_pnl_usd'),
            metadata=data.get('metadata', {})
        )


class PositionQueue:
    """Cola FIFO de posiciones con persistencia"""

    def __init__(self, data_path: str = "copy_trading_mini/data", max_size: int = 1000, logger: Any = None, notification_callback: Optional[Callable] = None):
        """
        Inicializa la cola de posiciones
        
        Args:
            data_path: Directorio para persistencia
            max_size: Tamaño máximo de la cola
            logger: Logger para registrar eventos
            notification_callback: Callback para notificar cambios de estado
        """
        self.data_path = Path(data_path)
        self.max_size = max_size
        self.logger = logger
        self.notification_callback = notification_callback

        # Colas FIFO
        self.pending_queue: deque = deque(maxlen=max_size)
        self.open_positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []

        # Índices para búsqueda rápida
        self.positions_by_trader: Dict[str, List[str]] = {}
        self.positions_by_token: Dict[str, List[str]] = {}

        # Lock para operaciones thread-safe
        self._lock = asyncio.Lock()

        # Crear directorio si no existe
        self.data_path.mkdir(parents=True, exist_ok=True)

        # Archivos de persistencia
        self.pending_file = self.data_path / "pending_positions.json"
        self.open_file = self.data_path / "open_positions.json"
        self.closed_file = self.data_path / "closed_positions.json"

    async def add_position(self, position: Position) -> bool:
        """
        Añade una posición a la cola
        
        Args:
            position: Posición a añadir
            
        Returns:
            True si se añadió correctamente
        """
        async with self._lock:
            # Verificar límite
            if len(self.pending_queue) >= self.max_size:
                return False

            # Añadir a cola
            self.pending_queue.append(position)

            # Actualizar índices
            if position.trader_wallet not in self.positions_by_trader:
                self.positions_by_trader[position.trader_wallet] = []
            self.positions_by_trader[position.trader_wallet].append(position.id)

            if position.token_address not in self.positions_by_token:
                self.positions_by_token[position.token_address] = []
            self.positions_by_token[position.token_address].append(position.id)

            # Persistir
            await self._save_pending()

            return True

    async def get_next_pending(self) -> Optional[Position]:
        """Obtiene la siguiente posición pendiente (FIFO)"""
        async with self._lock:
            if self.pending_queue:
                return self.pending_queue[0]
            return None

    async def execute_position(self, position_id: str, signature: str, 
                                execution_price: float, amount_tokens: float) -> bool:
        """
        Marca una posición como ejecutada
        
        Args:
            position_id: ID de la posición
            signature: Signature de la transacción
            execution_price: Precio de ejecución
            amount_tokens: Cantidad de tokens obtenidos
            
        Returns:
            True si se actualizó correctamente
        """
        async with self._lock:
            # Buscar en pending
            position = None
            for i, pos in enumerate(self.pending_queue):
                if pos.id == position_id:
                    position = pos
                    self.pending_queue.remove(pos)
                    break

            if not position:
                return False

            # Guardar estado anterior para notificación
            old_status = position.status

            # Actualizar posición
            position.status = PositionStatus.OPEN
            position.executed_at = datetime.now()
            position.execution_signature = signature
            position.execution_price = execution_price
            position.amount_tokens = amount_tokens

            # Calcular slippage
            if position.entry_price > 0:
                position.slippage = abs(execution_price - position.entry_price) / position.entry_price * 100

            # Mover a posiciones abiertas
            self.open_positions[position_id] = position

            # Persistir
            await self._save_pending()
            await self._save_open()

            # Notificar cambio de estado
            await self._notify_status_change(position, old_status, PositionStatus.OPEN)

            return True

    async def close_position(self, position_id: str, signature: str, 
                            close_price: float, close_amount_sol: float) -> bool:
        """
        Cierra una posición
        
        Args:
            position_id: ID de la posición
            signature: Signature de la transacción de cierre
            close_price: Precio de cierre
            close_amount_sol: SOL obtenidos al cerrar
            
        Returns:
            True si se cerró correctamente
        """
        async with self._lock:
            position = self.open_positions.get(position_id)
            if not position:
                return False

            # Guardar estado anterior para notificación
            old_status = position.status

            # Actualizar posición
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.now()
            position.close_signature = signature
            position.close_price = close_price
            position.close_amount_sol = close_amount_sol

            # Calcular P&L final
            position.calculate_pnl(close_price)

            # Mover a cerradas
            del self.open_positions[position_id]
            self.closed_positions.append(position)

            # Limitar historial de cerradas
            if len(self.closed_positions) > self.max_size:
                self.closed_positions = self.closed_positions[-self.max_size:]

            # Persistir
            await self._save_open()
            await self._save_closed()

            # Notificar cambio de estado
            await self._notify_status_change(position, old_status, PositionStatus.CLOSED)

            return True

    async def get_open_positions(self, trader: Optional[str] = None, 
                                token: Optional[str] = None) -> List[Position]:
        """Obtiene posiciones abiertas filtradas"""
        async with self._lock:
            positions = list(self.open_positions.values())

            if trader:
                positions = [p for p in positions if p.trader_wallet == trader]

            if token:
                positions = [p for p in positions if p.token_address == token]

            return positions

    async def get_position_by_id(self, position_id: str) -> Optional[Position]:
        """Obtiene una posición por ID"""
        async with self._lock:
            # Buscar en pending
            for pos in self.pending_queue:
                if pos.id == position_id:
                    return pos

            # Buscar en abiertas
            if position_id in self.open_positions:
                return self.open_positions[position_id]

            # Buscar en cerradas
            for pos in self.closed_positions:
                if pos.id == position_id:
                    return pos

            return None

    async def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas de la cola"""
        async with self._lock:
            total_open_value = sum(p.amount_sol for p in self.open_positions.values())
            total_pnl = sum(p.realized_pnl_sol or 0 for p in self.closed_positions)

            return {
                'pending_count': len(self.pending_queue),
                'open_count': len(self.open_positions),
                'closed_count': len(self.closed_positions),
                'total_open_value_sol': total_open_value,
                'total_realized_pnl_sol': total_pnl,
                'unique_traders': len(self.positions_by_trader),
                'unique_tokens': len(self.positions_by_token)
            }

    async def load_from_disk(self):
        """Carga posiciones desde disco"""
        async with self._lock:
            # Cargar pending
            if self.pending_file.exists():
                async with aiofiles.open(self.pending_file, 'r') as f:
                    data = json.loads(await f.read())
                    self.pending_queue = deque(
                        [Position.from_dict(p) for p in data],
                        maxlen=self.max_size
                    )

            # Cargar abiertas
            if self.open_file.exists():
                async with aiofiles.open(self.open_file, 'r') as f:
                    data = json.loads(await f.read())
                    self.open_positions = {
                        p['id']: Position.from_dict(p) for p in data
                    }

            # Cargar cerradas
            if self.closed_file.exists():
                async with aiofiles.open(self.closed_file, 'r') as f:
                    data = json.loads(await f.read())
                    self.closed_positions = [
                        Position.from_dict(p) for p in data[-self.max_size:]
                    ]

            # Reconstruir índices
            self._rebuild_indices()

    def _rebuild_indices(self):
        """Reconstruye los índices de búsqueda"""
        self.positions_by_trader.clear()
        self.positions_by_token.clear()

        # Procesar todas las posiciones
        all_positions = (
            list(self.pending_queue) + 
            list(self.open_positions.values()) + 
            self.closed_positions
        )

        for pos in all_positions:
            if pos.trader_wallet not in self.positions_by_trader:
                self.positions_by_trader[pos.trader_wallet] = []
            self.positions_by_trader[pos.trader_wallet].append(pos.id)

            if pos.token_address not in self.positions_by_token:
                self.positions_by_token[pos.token_address] = []
            self.positions_by_token[pos.token_address].append(pos.id)

    async def _save_pending(self):
        """Guarda posiciones pendientes"""
        data = [p.to_dict() for p in self.pending_queue]
        async with aiofiles.open(self.pending_file, 'w') as f:
            await f.write(json.dumps(data, indent=2))

    async def _save_open(self):
        """Guarda posiciones abiertas"""
        data = [p.to_dict() for p in self.open_positions.values()]
        async with aiofiles.open(self.open_file, 'w') as f:
            await f.write(json.dumps(data, indent=2))

    async def _save_closed(self):
        """Guarda posiciones cerradas"""
        data = [p.to_dict() for p in self.closed_positions]
        async with aiofiles.open(self.closed_file, 'w') as f:
            await f.write(json.dumps(data, indent=2))

    async def _notify_status_change(self, position: Position, old_status: PositionStatus, new_status: PositionStatus):
        """
        Notifica cambios de estado de posición
        
        Args:
            position: La posición que cambió
            old_status: Estado anterior
            new_status: Nuevo estado
        """
        # No notificar en estados PENDING o EXECUTING
        if new_status in [PositionStatus.PENDING, PositionStatus.EXECUTING]:
            return

        if self.notification_callback:
            try:
                # Preparar datos para la notificación
                notification_data = {
                    'side': position.side.value,
                    'token_address': position.token_address,
                    'token_name': f"Token {position.token_address[:8]}...",
                    'token_symbol': position.token_symbol or position.token_address[:4].upper(),
                    'amount': position.amount_sol,
                    'status': new_status.value,
                    'position_id': position.id,
                    'trader_wallet': position.trader_wallet
                }

                # Agregar información específica según el estado
                if new_status == PositionStatus.OPEN:
                    notification_data.update({
                        'execution_signature': position.execution_signature,
                        'execution_price': position.execution_price,
                        'amount_tokens': position.amount_tokens,
                        'slippage': position.slippage
                    })
                elif new_status == PositionStatus.CLOSED:
                    notification_data.update({
                        'close_signature': position.close_signature,
                        'close_price': position.close_price,
                        'close_amount_sol': position.close_amount_sol,
                        'realized_pnl_sol': position.realized_pnl_sol
                    })
                elif new_status == PositionStatus.FAILED:
                    notification_data.update({
                        'error': position.metadata.get('error', 'Error desconocido')
                    })

                # Llamar al callback de notificación
                await self.notification_callback(notification_data)

            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error notificando cambio de estado: {e}")

    async def get_pending_count(self) -> int:
        """Obtiene el número de posiciones pendientes"""
        async with self._lock:
            return len(self.pending_queue)

    async def save_state(self):
        """Guarda el estado completo de la cola"""
        await self._save_pending()
        await self._save_open()
        await self._save_closed()
        if self.logger:
            self.logger.info("Estado de la cola de posiciones guardado")

    async def get_all_positions(self) -> List[Dict[str, Any]]:
        """Obtiene todas las posiciones (pending, open, closed)"""
        async with self._lock:
            all_positions = []

            # Añadir posiciones pendientes
            for pos in self.pending_queue:
                all_positions.append(pos.to_dict())

            # Añadir posiciones abiertas
            for pos in self.open_positions.values():
                all_positions.append(pos.to_dict())

            # Añadir posiciones cerradas
            for pos in self.closed_positions:
                all_positions.append(pos.to_dict())

            return all_positions

    async def get_pending_positions(self) -> List[Dict[str, Any]]:
        """Obtiene todas las posiciones pendientes"""
        async with self._lock:
            return [pos.to_dict() for pos in self.pending_queue]

    async def update_position(self, position_id: str, status: Optional[str] = None, 
                            execution_signature: Optional[str] = None, 
                            error: Optional[str] = None, **kwargs) -> bool:
        """
        Actualiza una posición existente
        
        Args:
            position_id: ID de la posición
            status: Nuevo estado de la posición
            execution_signature: Signature de ejecución
            error: Mensaje de error si aplica
            **kwargs: Otros campos a actualizar
            
        Returns:
            True si se actualizó correctamente
        """
        async with self._lock:
            position = None

            # Buscar en posiciones pendientes
            for pos in self.pending_queue:
                if pos.id == position_id:
                    position = pos
                    break

            # Buscar en posiciones abiertas
            if not position and position_id in self.open_positions:
                position = self.open_positions[position_id]

            # Buscar en posiciones cerradas
            if not position:
                for pos in self.closed_positions:
                    if pos.id == position_id:
                        position = pos
                        break

            if not position:
                return False

            # Guardar estado anterior para notificación
            old_status = position.status
            new_status = None

            # Actualizar campos
            if status:
                if status == 'executed':
                    new_status = PositionStatus.OPEN
                    position.status = new_status
                    position.executed_at = datetime.now()
                elif status == 'failed':
                    new_status = PositionStatus.FAILED
                    position.status = new_status
                elif status == 'cancelled':
                    new_status = PositionStatus.CANCELLED
                    position.status = new_status
                elif status == 'closed':
                    new_status = PositionStatus.CLOSED
                    position.status = new_status
                    position.closed_at = datetime.now()

            if execution_signature:
                position.execution_signature = execution_signature

            if error:
                position.metadata['error'] = error

            # Actualizar otros campos
            for key, value in kwargs.items():
                if hasattr(position, key):
                    setattr(position, key, value)

            # Mover posición si cambió de estado
            if status == 'executed' and position in self.pending_queue:
                self.pending_queue.remove(position)
                self.open_positions[position_id] = position
            elif status in ['failed', 'cancelled'] and position in self.pending_queue:
                self.pending_queue.remove(position)
                self.closed_positions.append(position)
            elif status == 'closed' and position_id in self.open_positions:
                del self.open_positions[position_id]
                self.closed_positions.append(position)

            # Guardar cambios
            await self.save_state()

            # Notificar cambio de estado si hubo uno
            if new_status:
                await self._notify_status_change(position, old_status, new_status)

            return True
