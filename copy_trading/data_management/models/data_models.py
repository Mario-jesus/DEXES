# -*- coding: utf-8 -*-
"""
Modelos de datos para información de tokens y traders.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Set, Optional
from decimal import Decimal, getcontext

getcontext().prec = 26


@dataclass
class TokenInfo:
    """Información de un token"""
    num_traders: int = 0
    traders: Set[str] = field(default_factory=set)
    name: str = ""
    symbol: str = ""

    def add_trader(self, trader_wallet: str) -> None:
        """Añade un trader a la lista de traders"""
        self.traders.add(trader_wallet)
        self.num_traders += 1

    def remove_trader(self, trader_wallet: str) -> None:
        """Elimina un trader de la lista de traders"""
        if trader_wallet in self.traders:
            self.traders.remove(trader_wallet)
            self.num_traders -= 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            'num_traders': self.num_traders,
            'traders': list(self.traders),
            'name': self.name,
            'symbol': self.symbol
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TokenInfo':
        return cls(
            num_traders=data.get('num_traders', 0),
            traders=set(data.get('traders', [])),
            name=data.get('name', ''),
            symbol=data.get('symbol', '')
        )


@dataclass
class TraderTokenStats:
    """Estadísticas de un trader específico para un token específico"""
    trader_wallet: str = ""
    token_address: str = ""
    token_symbol: str = ""
    open_positions: int = 0
    closed_positions: int = 0
    total_volume_sol_open: str = "0.0"
    total_volume_sol_closed: str = "0.0"
    total_pnl_sol: str = "0.0"
    total_pnl_sol_with_costs: str = "0.0"
    last_trade_timestamp: Optional[str] = None

    @property
    def open_positions_active(self) -> int:
        """Obtiene el total de posiciones abiertas activas"""
        return max(0, self.open_positions - self.closed_positions)

    @property
    def total_trades(self) -> int:
        """Obtiene el total de trades"""
        return max(0, self.open_positions + self.closed_positions)

    @property
    def total_volume_sol(self) -> str:
        """Obtiene el total de volumen de sol"""
        value = Decimal(self.total_volume_sol_open) + Decimal(self.total_volume_sol_closed)
        return format(value, "f") if value > 0 else "0.0"

    @property
    def total_volume_sol_open_active(self) -> str:
        """Obtiene el total de volumen de sol para posiciones abiertas activas"""
        value = Decimal(self.total_volume_sol_open) - Decimal(self.total_volume_sol_closed)
        return format(value, "f") if value > 0 else "0.0"

    def register_open_position(self, volume_sol: str, timestamp: Optional[str] = None) -> None:
        """Registra una posición abierta para este trader en este token"""
        self.open_positions += 1
        self.total_volume_sol_open = format(Decimal(self.total_volume_sol_open) + Decimal(volume_sol), "f")
        if timestamp:
            self.last_trade_timestamp = timestamp

    def register_closed_position(self, volume_sol: str, timestamp: Optional[str] = None) -> None:
        """Registra una posición cerrada para este trader en este token"""
        self.closed_positions += 1
        self.total_volume_sol_closed = format(Decimal(self.total_volume_sol_closed) + Decimal(volume_sol), "f")
        if timestamp:
            self.last_trade_timestamp = timestamp

    def register_pnl(self, pnl_sol: str, pnl_sol_with_costs: str) -> None:
        """Registra P&L para este trader en este token"""
        self.total_pnl_sol = format(Decimal(self.total_pnl_sol) + Decimal(pnl_sol), "f")
        self.total_pnl_sol_with_costs = format(Decimal(self.total_pnl_sol_with_costs) + Decimal(pnl_sol_with_costs), "f")

    def get_win_rate(self) -> str:
        """Calcula el porcentaje de trades ganadores basado en P&L"""
        if self.total_trades == 0:
            return "0"

        # Si P&L es positivo, consideramos que fue un trade ganador
        pnl_decimal = Decimal(self.total_pnl_sol)
        if pnl_decimal > 0:
            win_rate = (Decimal("1") / Decimal(str(self.total_trades))) * Decimal("100")
            return format(win_rate, "f")
        return "0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            'trader_wallet': self.trader_wallet,
            'token_address': self.token_address,
            'token_symbol': self.token_symbol,
            'open_positions': self.open_positions,
            'closed_positions': self.closed_positions,
            'total_volume_sol_open': self.total_volume_sol_open,
            'total_volume_sol_closed': self.total_volume_sol_closed,
            'total_pnl_sol': self.total_pnl_sol,
            'total_pnl_sol_with_costs': self.total_pnl_sol_with_costs,
            'last_trade_timestamp': self.last_trade_timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TraderTokenStats':
        return cls(
            trader_wallet=data.get('trader_wallet', ''),
            token_address=data.get('token_address', ''),
            token_symbol=data.get('token_symbol', ''),
            open_positions=data.get('open_positions', 0),
            closed_positions=data.get('closed_positions', 0),
            total_volume_sol_open=data.get('total_volume_sol_open', '0'),
            total_volume_sol_closed=data.get('total_volume_sol_closed', '0'),
            total_pnl_sol=data.get('total_pnl_sol', '0'),
            total_pnl_sol_with_costs=data.get('total_pnl_sol_with_costs', '0'),
            last_trade_timestamp=data.get('last_trade_timestamp')
        )


@dataclass
class TraderStats:
    """Estadísticas generales de un trader (agregadas de todos los tokens)"""
    nickname: str = ""
    open_positions: int = 0
    closed_positions: int = 0
    total_volume_sol_open: str = "0.0"
    total_volume_sol_closed: str = "0.0"
    total_pnl_sol: str = "0.0"
    total_pnl_sol_with_costs: str = "0.0"

    @property
    def open_positions_active(self) -> int:
        """Obtiene el total de posiciones abiertas activas"""
        return max(0, self.open_positions - self.closed_positions)

    @property
    def total_trades(self) -> int:
        """Obtiene el total de trades"""
        return max(0, self.open_positions + self.closed_positions)

    @property
    def total_volume_sol(self) -> str:
        """Obtiene el total de volumen de sol"""
        value = Decimal(self.total_volume_sol_open) + Decimal(self.total_volume_sol_closed)
        return format(value, "f") if value > 0 else "0.0"

    @property
    def total_volume_sol_open_active(self) -> str:
        """Obtiene el total de volumen de sol para posiciones abiertas activas"""
        value = Decimal(self.total_volume_sol_open) - Decimal(self.total_volume_sol_closed)
        return format(value, "f") if value > 0 else "0.0"

    # Registrar posicion abierta, volumen y total de trades
    def register_open_position(self, volume_sol: str) -> None:
        self.open_positions += 1
        self.total_volume_sol_open = format(Decimal(self.total_volume_sol_open) + Decimal(volume_sol), "f")

    # Registrar posicion cerrada, volumen y total de trades
    def register_closed_position(self, volume_sol: str) -> None:
        self.closed_positions += 1
        self.total_volume_sol_closed = format(Decimal(self.total_volume_sol_closed) + Decimal(volume_sol), "f")

    # Registrar P&Ls
    def register_pnl(self, pnl_sol: str, pnl_sol_with_costs: str) -> None:
        self.total_pnl_sol = format(Decimal(self.total_pnl_sol) + Decimal(pnl_sol), "f")
        self.total_pnl_sol_with_costs = format(Decimal(self.total_pnl_sol_with_costs) + Decimal(pnl_sol_with_costs), "f")

    def to_dict(self) -> Dict[str, Any]:
        return {
            'nickname': self.nickname,
            'open_positions': self.open_positions,
            'closed_positions': self.closed_positions,
            'total_volume_sol_open': self.total_volume_sol_open,
            'total_volume_sol_closed': self.total_volume_sol_closed,
            'total_pnl_sol': self.total_pnl_sol,
            'total_pnl_sol_with_costs': self.total_pnl_sol_with_costs
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TraderStats':
        return cls(
            nickname=data.get('nickname', ''),
            open_positions=data.get('open_positions', 0),
            closed_positions=data.get('closed_positions', 0),
            total_volume_sol_open=data.get('total_volume_sol_open', '0'),
            total_volume_sol_closed=data.get('total_volume_sol_closed', '0'),
            total_pnl_sol=data.get('total_pnl_sol', '0'),
            total_pnl_sol_with_costs=data.get('total_pnl_sol_with_costs', '0')
        )
