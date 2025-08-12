# -*- coding: utf-8 -*-
"""
Modelos base para posiciones de trading.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, Literal, NamedTuple
from decimal import Decimal, InvalidOperation, DivisionByZero, getcontext

from ...config import CopyTradingConfig
from ...data_management.models import TokenInfo
from .serialization import serialize_for_json

getcontext().prec = 26

class TraderTradeData(NamedTuple):
    """Tupla con los datos de los trades de compra y venta del trader"""
    # Información básica del trade
    trader_wallet: str
    side: Literal['buy', 'sell']  # 'buy' o 'sell'
    token_address: str
    amount_sol: str
    signature: str

    # Información del token
    token_amount: str
    new_token_balance: str

    # Información del pool/bonding curve
    pool: str
    bonding_curve_key: str
    v_tokens_in_bonding_curve: str
    v_sol_in_bonding_curve: str
    market_cap_sol: str

    # Metadatos
    timestamp: datetime


class PositionTraderTradeData:
    """Clase que envuelve TraderTradeData con funcionalidad de copy trading"""

    def __init__(self, trader_trade_data: TraderTradeData, config: CopyTradingConfig):
        self._trader_trade_data = trader_trade_data
        self._config = config
        self._copy_amount_sol: Optional[str] = None
        self._copy_amount_tokens: Optional[str] = None
        self._created_at = datetime.now() # This line is removed as per the new_code, as the created_at is now part of the dataclass.

    @property
    def copy_amount_sol(self) -> str:
        """Calcula el monto en SOL a copiar basado en la configuración"""
        if self._copy_amount_sol is None:
            self._copy_amount_sol = self._config.calculate_copy_amount(
                self._trader_trade_data.trader_wallet,
                self._trader_trade_data.amount_sol
            )
        return self._copy_amount_sol

    @copy_amount_sol.setter
    def copy_amount_sol(self, value: str) -> None:
        self._copy_amount_sol = value

    @property
    def copy_amount_tokens(self) -> str:
        """Calcula el monto de tokens a copiar basado en la configuración"""
        if self._copy_amount_tokens is None:
            self._copy_amount_tokens = self._config.calculate_copy_amount(
                self._trader_trade_data.trader_wallet,
                self._trader_trade_data.token_amount
            )
        return self._copy_amount_tokens

    @copy_amount_tokens.setter
    def copy_amount_tokens(self, value: str) -> None:
        self._copy_amount_tokens = value

    @property
    def trader_wallet(self) -> str:
        return self._trader_trade_data.trader_wallet

    @property
    def token_address(self) -> str:
        return self._trader_trade_data.token_address

    @property
    def signature(self) -> str:
        return self._trader_trade_data.signature

    @property
    def side(self) -> Literal['buy', 'sell']:
        return self._trader_trade_data.side

    @property
    def pool(self) -> str:
        return self._trader_trade_data.pool

    @property
    def trader_trade_data(self) -> TraderTradeData:
        return self._trader_trade_data

    @property
    def created_at(self) -> datetime:
        return self._created_at

    def get_sol_per_token_price(self) -> str:
        """Calcula el precio SOL por token con validación para evitar división por cero"""
        try:
            amount_sol_dec = Decimal(self._trader_trade_data.amount_sol)
            token_amount_dec = Decimal(self._trader_trade_data.token_amount)

            if token_amount_dec > 0:
                price = amount_sol_dec / token_amount_dec
                return format(price, "f")
            else:
                return "0"
        except (InvalidOperation, ValueError, DivisionByZero):
            return "0"

    def get_sol_per_token_bonding_curve_price(self) -> str:
        """Calcula el precio SOL por token de la bonding curve con validación para evitar división por cero"""
        try:
            v_sol_dec = Decimal(self._trader_trade_data.v_sol_in_bonding_curve)
            v_tokens_dec = Decimal(self._trader_trade_data.v_tokens_in_bonding_curve)

            if v_tokens_dec > 0:
                price = v_sol_dec / v_tokens_dec
                return format(price, "f")
            else:
                return "0"
        except (InvalidOperation, ValueError, DivisionByZero):
            return "0"

    def to_dict(self) -> Dict[str, Any]:
        # Convertir el NamedTuple a dict y manejar la serialización de datetime
        trader_data_dict = self._trader_trade_data._asdict()
        # Convertir datetime a string ISO
        if 'timestamp' in trader_data_dict and isinstance(trader_data_dict['timestamp'], datetime):
            trader_data_dict['timestamp'] = trader_data_dict['timestamp'].isoformat()

        return {
            'trader_trade_data': serialize_for_json(trader_data_dict)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], config: CopyTradingConfig) -> 'PositionTraderTradeData':
        trader_data_dict = data['trader_trade_data'].copy()
        # Convertir string ISO de vuelta a datetime
        if 'timestamp' in trader_data_dict and isinstance(trader_data_dict['timestamp'], str):
            trader_data_dict['timestamp'] = datetime.fromisoformat(trader_data_dict['timestamp'])

        return cls(TraderTradeData(**trader_data_dict), config)


@dataclass
class Position:
    """Clase base para posiciones con atributos comunes"""
    # ID de la posición
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Datos básicos de la posición
    amount_sol: str = ""
    amount_tokens: str = ""
    entry_price: str = ""
    fee_sol: str = ""
    total_cost_sol: str = ""

    # Datos de ejecución
    execution_signature: Optional[str] = None
    execution_price: str = ""

    # Estado
    is_analyzed: bool = False
    message_error: str = ""

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None

    # Datos del trade del trader que originó esta posición
    trader_trade_data: Optional[TraderTradeData] = None

    # Metadata (con límite de tamaño)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def trader_wallet(self) -> str:
        if self.trader_trade_data:
            return self.trader_trade_data.trader_wallet
        return ""

    @property
    def token_address(self) -> str:
        if self.trader_trade_data:
            return self.trader_trade_data.token_address
        return ""

    @property
    def signature(self) -> Optional[str]:
        return self.execution_signature

    def add_metadata(self, key: str, value: Any, max_metadata_size: int = 1000) -> None:
        """
        Agrega metadata con control de tamaño para evitar crecimiento indefinido
        
        Args:
            key: Clave del metadata
            value: Valor del metadata
            max_metadata_size: Tamaño máximo del diccionario metadata
        """
        if len(self.metadata) >= max_metadata_size:
            # Eliminar las claves más antiguas (primeras 10)
            keys_to_remove = list(self.metadata.keys())[:10]
            for key_to_remove in keys_to_remove:
                del self.metadata[key_to_remove]

        self.metadata[key] = value

    def get_is_analyzed(self) -> bool:
        return self.is_analyzed

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        # Procesar metadata usando la función de serialización
        metadata_dict = serialize_for_json(self.metadata)

        # Procesar trader_trade_data para manejar datetime
        trader_data_dict = None
        if self.trader_trade_data:
            trader_data_dict = self.trader_trade_data._asdict()
            # Convertir datetime a string ISO
            if 'timestamp' in trader_data_dict and isinstance(trader_data_dict['timestamp'], datetime):
                trader_data_dict['timestamp'] = trader_data_dict['timestamp'].isoformat()

        return {
            'id': self.id,
            'amount_sol': self.amount_sol,
            'amount_tokens': self.amount_tokens,
            'entry_price': self.entry_price,
            'fee_sol': self.fee_sol,
            'total_cost_sol': self.total_cost_sol,
            'execution_signature': self.execution_signature,
            'execution_price': self.execution_price,
            'is_analyzed': self.is_analyzed,
            'message_error': self.message_error,
            'created_at': self.created_at.isoformat(),
            'executed_at': self.executed_at.isoformat() if self.executed_at else None,
            'trader_trade_data': trader_data_dict,
            'metadata': metadata_dict
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
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
            is_analyzed=data.get('is_analyzed', False),
            message_error=data.get('message_error', ''),
            created_at=datetime.fromisoformat(data['created_at']) if data.get('created_at') else datetime.now(),
            executed_at=datetime.fromisoformat(data['executed_at']) if data.get('executed_at') else None,
            trader_trade_data=trader_data,
            metadata=metadata
        )
