# -*- coding: utf-8 -*-
"""
Modelos específicos de posiciones de trading.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Union, Tuple, Optional
from decimal import Decimal, ROUND_DOWN, getcontext

from ...data_management.models.data_models import TokenInfo
from .base_models import Position, TraderTradeData
from .enums import PositionStatus, ClosePositionStatus
from .serialization import serialize_for_json

getcontext().prec = 26


@dataclass(slots=True)
class ClosePosition(Position):
    """Datos de un cierre individual de posición"""
    status: ClosePositionStatus = ClosePositionStatus.PENDING

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        # Obtener el diccionario base de la clase padre
        base_dict = super(ClosePosition, self).to_dict()
        # Agregar solo los atributos únicos de ClosePosition
        base_dict['status'] = self.status.value
        return base_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ClosePosition':
        """Crea desde diccionario"""
        # Procesar metadata para manejar objetos TokenInfo
        metadata = {}
        for key, value in data.get('metadata', {}).items():
            if key == 'token_info' and isinstance(value, dict):
                metadata[key] = TokenInfo.from_dict(value)
            else:
                metadata[key] = value

        return cls(
            id=data['id'],
            amount_sol=data.get('amount_sol', ''),
            amount_sol_executed=data.get('amount_sol_executed', ''),
            amount_tokens=data.get('amount_tokens', ''),
            amount_tokens_executed=data.get('amount_tokens_executed', ''),
            fee_sol=data.get('fee_sol', ''),
            total_cost_sol=data.get('total_cost_sol', ''),
            execution_signature=data.get('execution_signature'),
            execution_price=data.get('execution_price', ''),
            status=ClosePositionStatus(data.get('status', ClosePositionStatus.PENDING.value)),
            is_analyzed=data.get('is_analyzed', False),
            message_error=data.get('message_error', ''),
            is_liquidation=data.get('is_liquidation', False),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            executed_at=datetime.fromisoformat(data['executed_at']) if data.get('executed_at') else None,
            trader_trade_data=TraderTradeData.from_dict(data.get('trader_trade_data', {})),
            metadata=metadata
        )


@dataclass(slots=True)
class SubClosePosition:
    """Datos de un cierre parcial de posición"""
    close_position: ClosePosition
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    amount_sol_executed: str = ""
    amount_tokens_executed: str = ""
    total_cost_sol: str = ""
    status: ClosePositionStatus = ClosePositionStatus.PENDING
    message_error: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

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
    def is_liquidation(self) -> bool:
        return self.close_position.is_liquidation

    def get_metadata(self, key: str, default: Optional[Any] = None) -> Optional[Any]:
        return self.metadata.get(key, default)

    def add_metadata(self, key: str, value: Any, max_metadata_size: int = 1000) -> None:
        if len(self.metadata) >= max_metadata_size:
            # Eliminar las claves más antiguas (primeras 10)
            keys_to_remove = list(self.metadata.keys())[:10]
            for key_to_remove in keys_to_remove:
                del self.metadata[key_to_remove]

        self.metadata[key] = value

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        return {
            'type': 'partial',
            'close_position': self.close_position.to_dict(),
            'id': self.id,
            'amount_sol_executed': self.amount_sol_executed,
            'amount_tokens_executed': self.amount_tokens_executed,
            'total_cost_sol': self.total_cost_sol,
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
            id=data.get('id', str(uuid.uuid4())),
            amount_sol_executed=data.get('amount_sol_executed', ''),
            amount_tokens_executed=data.get('amount_tokens_executed', ''),
            total_cost_sol=data.get('total_cost_sol', ''),
            status=ClosePositionStatus(data.get('status', ClosePositionStatus.PENDING.value)),
            message_error=data.get('message_error', ''),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now()
        )


@dataclass(slots=True)
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

    def add_close(self, close_data: Union[ClosePosition, SubClosePosition]) -> None:
        """
        Agrega un cierre al historial y actualiza el estado
        """
        self.close_history.append(close_data)

    def is_fully_closed(self) -> bool:
        """
        Verifica si la posición está completamente cerrada
        """
        return self.status == PositionStatus.CLOSED

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        # Obtener el diccionario base de la clase padre
        base_dict = super(OpenPosition, self).to_dict()

        # Procesar close_history usando la función de serialización
        close_history_dict = serialize_for_json(self.close_history)

        # Agregar solo los atributos únicos de OpenPosition
        base_dict['status'] = self.status.value
        base_dict['close_history'] = close_history_dict
        return base_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OpenPosition':
        """Crea desde diccionario"""
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
            id=data['id'],
            amount_sol=data.get('amount_sol', ''),
            amount_sol_executed=data.get('amount_sol_executed', ''),
            amount_tokens=data.get('amount_tokens', ''),
            amount_tokens_executed=data.get('amount_tokens_executed', ''),
            fee_sol=data.get('fee_sol', ''),
            total_cost_sol=data.get('total_cost_sol', ''),
            execution_signature=data.get('execution_signature'),
            execution_price=data.get('execution_price', ''),
            status=PositionStatus(data.get('status', PositionStatus.PENDING.value)),
            is_analyzed=data.get('is_analyzed', False),
            message_error=data.get('message_error', ''),
            is_liquidation=data.get('is_liquidation', False),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            executed_at=datetime.fromisoformat(data['executed_at']) if data.get('executed_at') else None,
            trader_trade_data=TraderTradeData.from_dict(data.get('trader_trade_data', {})),
            metadata=metadata,
            close_history=close_history
        )
