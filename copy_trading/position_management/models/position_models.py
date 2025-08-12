# -*- coding: utf-8 -*-
"""
Modelos específicos de posiciones de trading.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Union, Tuple, Optional
from decimal import Decimal

from .base_models import Position, TraderTradeData
from .enums import PositionStatus, ClosePositionStatus
from .serialization import serialize_for_json
from ...data_management.models.data_models import TokenInfo


@dataclass
class ClosePosition(Position):
    """Datos de un cierre individual de posición"""
    status: ClosePositionStatus = ClosePositionStatus.PENDING

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        # Obtener el diccionario base de la clase padre
        base_dict = super().to_dict()
        # Agregar solo los atributos únicos de ClosePosition
        base_dict['status'] = self.status.value
        return base_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ClosePosition':
        """Crea desde diccionario"""
        trader_data = data.get('trader_trade_data')

        # Procesar trader_data para manejar datetime
        if trader_data and isinstance(trader_data, dict):
            # Convertir string ISO de vuelta a datetime
            if 'timestamp' in trader_data and isinstance(trader_data['timestamp'], str):
                trader_data['timestamp'] = datetime.fromisoformat(trader_data['timestamp'])
            trader_data = TraderTradeData(**trader_data)

        # Procesar metadata para manejar objetos TokenInfo
        metadata = {}
        for key, value in data.get('metadata', {}).items():
            if key == 'token_info' and isinstance(value, dict):
                metadata[key] = TokenInfo.from_dict(value)
            else:
                metadata[key] = value

        return cls(
            id=data.get('id', str(uuid.uuid4())),
            amount_sol=data.get('amount_sol', ''),
            amount_tokens=data.get('amount_tokens', ''),
            entry_price=data.get('entry_price', ''),
            fee_sol=data.get('fee_sol', ''),
            total_cost_sol=data.get('total_cost_sol', ''),
            execution_signature=data.get('execution_signature'),
            execution_price=data.get('execution_price', ''),
            status=ClosePositionStatus(data.get('status', ClosePositionStatus.PENDING.value)),
            is_analyzed=data.get('is_analyzed', False),
            message_error=data.get('message_error', ''),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            executed_at=datetime.fromisoformat(data['executed_at']) if data.get('executed_at') else None,
            trader_trade_data=trader_data,
            metadata=metadata
        )


@dataclass
class SubClosePosition:
    """Datos de un cierre parcial de posición"""
    close_position: ClosePosition
    amount_sol: str = ""
    amount_tokens: str = ""
    status: ClosePositionStatus = ClosePositionStatus.PENDING
    message_error: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not isinstance(self.close_position, ClosePosition):
            raise ValueError("close_position must be an instance of ClosePosition")

    @property
    def trader_wallet(self) -> str:
        return self.close_position.trader_wallet

    @property
    def token_address(self) -> str:
        return self.close_position.token_address

    @property
    def signature(self) -> Optional[str]:
        return self.close_position.execution_signature

    @property
    def metadata(self) -> Dict[str, Any]:
        return self.close_position.metadata

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        return {
            'type': 'partial',
            'close_position': self.close_position.to_dict(),
            'amount_sol': self.amount_sol,
            'amount_tokens': self.amount_tokens,
            'status': self.status.value,
            'message_error': self.message_error,
            'created_at': self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SubClosePosition':
        """Crea desde diccionario"""
        close_position = ClosePosition.from_dict(data['close_position'])
        return cls(
            close_position=close_position,
            amount_sol=data.get('amount_sol', ''),
            amount_tokens=data.get('amount_tokens', ''),
            status=ClosePositionStatus(data.get('status', ClosePositionStatus.PENDING.value)),
            message_error=data.get('message_error', ''),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now()
        )


@dataclass
class OpenPosition(Position):
    """Representa una posición en el sistema"""
    # Estado de la posición
    status: PositionStatus = PositionStatus.PENDING
    # Historial de cierres
    close_history: List[Union[ClosePosition, SubClosePosition]] = field(default_factory=list)

    def get_is_analyzed(self) -> bool:
        for close_item in self.close_history:
            if isinstance(close_item, SubClosePosition):
                close_item = close_item.close_position
            if not close_item.get_is_analyzed():
                return False
        return self.is_analyzed

    @classmethod
    def _get_close_amounts(cls, close_item: Union[ClosePosition, SubClosePosition]) -> Tuple[str, str]:
        """
        Obtiene los montos de SOL y tokens de un item del historial
        
        Args:
            close_item: Item del historial
            
        Returns:
            Tuple de (amount_sol, amount_tokens)
        """
        return close_item.amount_sol, close_item.amount_tokens

    @classmethod
    def calculate_remaining_amounts(cls, position: 'OpenPosition') -> Tuple[str, str]:
        """
        Calcula la cantidad de tokens y SOL restantes
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Tuple de (remaining_sol, remaining_tokens) como strings
        """
        total_closed_sol, total_closed_tokens = cls.calculate_total_closed_amounts(position)
        total_original_tokens = Decimal(position.amount_tokens) if position.amount_tokens else Decimal('0')
        total_original_sol = Decimal(position.amount_sol) if position.amount_sol else Decimal('0')
        remaining_sol = max(Decimal('0'), total_original_sol - Decimal(total_closed_sol))
        remaining_tokens = max(Decimal('0'), total_original_tokens - Decimal(total_closed_tokens))
        return format(remaining_sol, "f"), format(remaining_tokens, "f")

    @classmethod
    def calculate_total_closed_amounts(cls, position: 'OpenPosition') -> Tuple[str, str]:
        """
        Calcula los totales acumulados de cierres
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Tuple de (total_sol, total_tokens) como strings
        """
        total_sol = Decimal('0')
        total_tokens = Decimal('0')

        for close_item in position.close_history:
            amount_sol, amount_tokens = cls._get_close_amounts(close_item)
            if amount_sol:
                total_sol += Decimal(amount_sol)
            if amount_tokens:
                total_tokens += Decimal(amount_tokens)

        return format(total_sol, "f"), format(total_tokens, "f")

    @classmethod
    def calculate_remaining_tokens(cls, position: 'OpenPosition') -> str:
        """
        Calcula la cantidad de tokens restantes
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Cantidad de tokens restantes como string
        """
        _, total_closed_tokens = cls.calculate_total_closed_amounts(position)
        total_original = Decimal(position.amount_tokens) if position.amount_tokens else Decimal('0')
        remaining = max(Decimal('0'), total_original - Decimal(total_closed_tokens))
        return format(remaining, "f")

    @classmethod
    def calculate_remaining_sol(cls, position: 'OpenPosition') -> str:
        """
        Calcula la cantidad de SOL restantes
        """
        total_closed_sol, _ = cls.calculate_total_closed_amounts(position)
        total_original = Decimal(position.amount_sol) if position.amount_sol else Decimal('0')
        remaining = max(Decimal('0'), total_original - Decimal(total_closed_sol))
        return format(remaining, "f")

    def add_close(self, close_data: Union[ClosePosition, SubClosePosition]) -> None:
        """
        Agrega un cierre al historial y actualiza el estado
        """
        self.close_history.append(close_data)

        # Determinar si es cierre completo o parcial
        remaining_tokens = self.calculate_remaining_tokens(self)
        remaining_sol = self.calculate_remaining_sol(self)

        if remaining_tokens == '0' or remaining_sol == '0':
            self.status = PositionStatus.CLOSED
        else:
            self.status = PositionStatus.PARTIALLY_CLOSED

    def is_fully_closed(self) -> bool:
        """
        Verifica si la posición está completamente cerrada
        """
        return self.status == PositionStatus.CLOSED

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        # Obtener el diccionario base de la clase padre
        base_dict = super().to_dict()

        # Procesar close_history usando la función de serialización
        close_history_dict = serialize_for_json(self.close_history)

        # Agregar solo los atributos únicos de OpenPosition
        base_dict['status'] = self.status.value
        base_dict['close_history'] = close_history_dict
        return base_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OpenPosition':
        """Crea desde diccionario"""
        trader_data = data.get('trader_trade_data')

        # Procesar trader_data para manejar datetime
        if trader_data and isinstance(trader_data, dict):
            # Convertir string ISO de vuelta a datetime
            if 'timestamp' in trader_data and isinstance(trader_data['timestamp'], str):
                trader_data['timestamp'] = datetime.fromisoformat(trader_data['timestamp'])
            trader_data = TraderTradeData(**trader_data)

        # Procesar close_history para manejar tanto ClosePosition como ClosePositionPartial
        close_history = []
        for ch_data in data.get('close_history', []):
            close_type = ch_data.get('type', 'full')

            if close_type == 'partial':
                # Es un ClosePositionPartial
                close_partial = SubClosePosition.from_dict(ch_data)
                close_history.append(close_partial)
            else:
                # Es un ClosePosition normal
                close_position = ClosePosition.from_dict(ch_data)
                close_history.append(close_position)

        # Procesar metadata para manejar objetos TokenInfo
        metadata = {}
        for key, value in data.get('metadata', {}).items():
            if key == 'token_info' and isinstance(value, dict):
                metadata[key] = TokenInfo.from_dict(value)
            else:
                metadata[key] = value

        return cls(
            id=data.get('id', str(uuid.uuid4())),
            amount_sol=data.get('amount_sol', ''),
            amount_tokens=data.get('amount_tokens', ''),
            entry_price=data.get('entry_price', ''),
            fee_sol=data.get('fee_sol', ''),
            total_cost_sol=data.get('total_cost_sol', ''),
            execution_signature=data.get('execution_signature'),
            execution_price=data.get('execution_price', ''),
            status=PositionStatus(data.get('status', PositionStatus.PENDING.value)),
            is_analyzed=data.get('is_analyzed', False),
            message_error=data.get('message_error', ''),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            executed_at=datetime.fromisoformat(data['executed_at']) if data.get('executed_at') else None,
            trader_trade_data=trader_data,
            metadata=metadata,
            close_history=close_history
        )
