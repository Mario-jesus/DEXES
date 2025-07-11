# -*- coding: utf-8 -*-
"""
Configuración del sistema Copy Trading Mini
"""
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path


class AmountMode(Enum):
    """Modos de cálculo de montos para copy trading"""
    EXACT = "exact"          # Replicar monto exacto
    PERCENTAGE = "percentage" # Porcentaje del monto original
    FIXED = "fixed"          # Monto fijo por operación


class TransactionType(Enum):
    """Tipos de transacciones soportadas"""
    LIGHTNING = "lightning_trade"  # Transacciones ejecutadas por el servidor
    LOCAL = "local_trade"          # Transacciones firmadas localmente


@dataclass
class TraderConfig:
    """Configuración específica por trader"""
    wallet_address: str
    amount_mode: Optional[AmountMode] = None
    amount_value: Optional[float] = None
    enabled: bool = True
    max_position_size: Optional[float] = None  # Máximo SOL por posición
    daily_limit: Optional[float] = None        # Límite diario en SOL

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        return {
            'wallet_address': self.wallet_address,
            'amount_mode': self.amount_mode.value if self.amount_mode else None,
            'amount_value': self.amount_value,
            'enabled': self.enabled,
            'max_position_size': self.max_position_size,
            'daily_limit': self.daily_limit
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TraderConfig':
        """Crea desde diccionario"""
        return cls(
            wallet_address=data['wallet_address'],
            amount_mode=AmountMode(data['amount_mode']) if data.get('amount_mode') else None,
            amount_value=data.get('amount_value'),
            enabled=data.get('enabled', True),
            max_position_size=data.get('max_position_size'),
            daily_limit=data.get('daily_limit')
        )


@dataclass
class CopyTradingConfig:
    """Configuración principal del sistema de copy trading"""

    # Traders a seguir
    traders: List[str] = field(default_factory=list)
    trader_configs: Dict[str, TraderConfig] = field(default_factory=dict)

    # Modo de copia y valor
    amount_mode: str = "percentage"  # 'exact', 'percentage', 'fixed'
    amount_value: float = 50.0  # Porcentaje (50.0), monto fijo en SOL, o monto exacto a copiar

    # Wallet y Red
    wallet_file: str = "wallets/wallet_pumpportal.json"
    rpc_url: str = "https://api.mainnet-beta.solana.com/"

    # Validaciones
    validations_enabled: bool = True
    strict_mode: bool = True  # Cambiado a False para permitir WARNING en copy trading
    min_sol_balance: float = 0.01
    max_position_size: float = 1.0
    max_daily_volume: float = 10.0
    min_trade_interval_seconds: int = 1  # Reducido de 30 a 1 segundos para copy trading

    # Configuración de Transacciones
    transaction_type: str = "local_trade"  # 'lightning_trade' o 'local_trade'
    pool_type: str = "auto"  # 'pump', 'raydium', 'pump-amm', 'launchlab', 'raydium-cpmm', 'bonk', 'auto'
    skip_preflight: bool = True
    jito_only: bool = False  # Solo para lightning_trade

    # Parámetros de trading
    slippage_tolerance: float = 0.01  # 1%
    priority_fee_sol: float = 0.0005  # 0.0005 SOL
    max_execution_delay_seconds: int = 30

    # Logging
    logging_level: str = "INFO"
    log_to_file: bool = True
    log_file_path: str = "copy_trading_mini/logs"
    max_log_size_mb: int = 10

    # Sistema
    dry_run: bool = False
    auto_close_positions: bool = True
    position_tracking_interval: int = 60  # segundos

    # Persistencia
    data_path: str = "copy_trading_mini/data"
    save_interval_seconds: int = 300  # 5 minutos

    # WebSocket
    websocket_reconnect_delay: int = 5
    websocket_max_retries: int = 10

    # Notificaciones
    notifications_enabled: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_messages_per_minute: int = 30  # Límite de mensajes por minuto para Telegram

    def is_lightning_trade(self) -> bool:
        """Verifica si está configurado para usar Lightning Trade"""
        return self.transaction_type == "lightning_trade"

    def is_local_trade(self) -> bool:
        """Verifica si está configurado para usar Local Trade"""
        return self.transaction_type == "local_trade"

    def get_transaction_params(self) -> Dict[str, Any]:
        """Obtiene parámetros comunes para transacciones"""
        params = {
            'slippage': self.slippage_tolerance,
            'priority_fee': self.priority_fee_sol,
            'pool': self.pool_type,
        }

        if self.is_lightning_trade():
            params.update({
                'skip_preflight': self.skip_preflight,
                'jito_only': self.jito_only
            })
        elif self.is_local_trade():
            params.update({
                'rpc_endpoint': self.rpc_url
            })

        return params

    def add_trader(self, wallet_address: str, config: Optional[TraderConfig] = None):
        """Añade un trader con configuración opcional"""
        if wallet_address not in self.traders:
            self.traders.append(wallet_address)

        if config:
            self.trader_configs[wallet_address] = config
        elif wallet_address not in self.trader_configs:
            # Crear configuración por defecto
            self.trader_configs[wallet_address] = TraderConfig(wallet_address=wallet_address)

    def remove_trader(self, wallet_address: str):
        """Elimina un trader"""
        if wallet_address in self.traders:
            self.traders.remove(wallet_address)
        if wallet_address in self.trader_configs:
            del self.trader_configs[wallet_address]

    def get_trader_config(self, wallet_address: str) -> TraderConfig:
        """Obtiene la configuración de un trader específico"""
        if wallet_address in self.trader_configs:
            return self.trader_configs[wallet_address]

        # Retornar configuración por defecto
        return TraderConfig(
            wallet_address=wallet_address,
            amount_mode=self.amount_mode,
            amount_value=self.amount_value
        )

    def calculate_copy_amount(self, trader_wallet: str, original_amount: float) -> float:
        """
        Calcula el monto a copiar basado en la configuración
        
        Args:
            trader_wallet: Dirección del trader
            original_amount: Monto original del trade
            
        Returns:
            Monto calculado para copiar
        """
        # Obtener configuración del trader o usar valores globales
        trader_config = self.get_trader_config(trader_wallet)

        # Usar configuración específica del trader o global
        mode = AmountMode(trader_config.amount_mode or self.amount_mode)
        value = trader_config.amount_value if trader_config.amount_value is not None else self.amount_value

        if mode == AmountMode.EXACT:
            copy_amount = original_amount
        elif mode == AmountMode.PERCENTAGE:
            copy_amount = original_amount * (value / 100.0)
        elif mode == AmountMode.FIXED:
            copy_amount = value
        else:
            copy_amount = original_amount

        # Aplicar límites
        if trader_config.max_position_size:
            copy_amount = min(copy_amount, trader_config.max_position_size)

        copy_amount = min(copy_amount, self.max_position_size)

        return copy_amount

    def to_dict(self) -> Dict[str, Any]:
        """Convierte la configuración a diccionario"""
        return {
            'traders': self.traders,
            'trader_configs': {k: v.to_dict() for k, v in self.trader_configs.items()},
            'amount_mode': self.amount_mode,
            'amount_value': self.amount_value,
            'wallet_file': self.wallet_file,
            'rpc_url': self.rpc_url,
            'validations_enabled': self.validations_enabled,
            'strict_mode': self.strict_mode,
            'min_sol_balance': self.min_sol_balance,
            'max_position_size': self.max_position_size,
            'max_daily_volume': self.max_daily_volume,
            'min_trade_interval_seconds': self.min_trade_interval_seconds,
            'transaction_type': self.transaction_type,
            'pool_type': self.pool_type,
            'skip_preflight': self.skip_preflight,
            'jito_only': self.jito_only,
            'slippage_tolerance': self.slippage_tolerance,
            'priority_fee_sol': self.priority_fee_sol,
            'max_execution_delay_seconds': self.max_execution_delay_seconds,
            'logging_level': self.logging_level,
            'log_to_file': self.log_to_file,
            'log_file_path': self.log_file_path,
            'max_log_size_mb': self.max_log_size_mb,
            'dry_run': self.dry_run,
            'auto_close_positions': self.auto_close_positions,
            'position_tracking_interval': self.position_tracking_interval,
            'data_path': self.data_path,
            'save_interval_seconds': self.save_interval_seconds,
            'websocket_reconnect_delay': self.websocket_reconnect_delay,
            'websocket_max_retries': self.websocket_max_retries,
            'notifications_enabled': self.notifications_enabled,
            'telegram_bot_token': self.telegram_bot_token,
            'telegram_chat_id': self.telegram_chat_id,
            'telegram_messages_per_minute': self.telegram_messages_per_minute
        }

    def save_to_file(self, filepath: str = "copy_trading_mini/config.json"):
        """Guarda la configuración en archivo"""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CopyTradingConfig':
        """Crea configuración desde diccionario"""
        config = cls()

        # Configuración básica
        config.traders = data.get('traders', [])
        config.amount_mode = data.get('amount_mode', 'percentage')
        config.amount_value = data.get('amount_value', 50.0)
        config.wallet_file = data.get('wallet_file', 'wallet.json')
        config.rpc_url = data.get('rpc_url', 'https://api.mainnet-beta.solana.com/')

        # Validaciones
        config.validations_enabled = data.get('validations_enabled', True)
        config.strict_mode = data.get('strict_mode', False) # Changed from True to False
        config.min_sol_balance = data.get('min_sol_balance', 0.01)
        config.max_position_size = data.get('max_position_size', 1.0)
        config.max_daily_volume = data.get('max_daily_volume', 10.0)
        config.min_trade_interval_seconds = data.get('min_trade_interval_seconds', 5) # Changed from 30 to 5

        # Transacciones
        config.transaction_type = data.get('transaction_type', 'local_trade')
        config.pool_type = data.get('pool_type', 'auto')
        config.skip_preflight = data.get('skip_preflight', True)
        config.jito_only = data.get('jito_only', False)

        # Trading
        config.slippage_tolerance = data.get('slippage_tolerance', 0.01)
        config.priority_fee_sol = data.get('priority_fee_sol', 0.0005)
        config.max_execution_delay_seconds = data.get('max_execution_delay_seconds', 30)

        # Configuraciones de traders
        trader_configs = data.get('trader_configs', {})
        for wallet, tconfig in trader_configs.items():
            config.trader_configs[wallet] = TraderConfig.from_dict(tconfig)

        # Logging
        config.logging_level = data.get('logging_level', 'INFO')
        config.log_to_file = data.get('log_to_file', True)
        config.log_file_path = data.get('log_file_path', 'copy_trading_mini/logs')
        config.max_log_size_mb = data.get('max_log_size_mb', 10)

        # Sistema
        config.dry_run = data.get('dry_run', False)
        config.auto_close_positions = data.get('auto_close_positions', True)
        config.position_tracking_interval = data.get('position_tracking_interval', 60)
        config.data_path = data.get('data_path', 'copy_trading_mini/data')
        config.save_interval_seconds = data.get('save_interval_seconds', 300)

        # WebSocket
        config.websocket_reconnect_delay = data.get('websocket_reconnect_delay', 5)
        config.websocket_max_retries = data.get('websocket_max_retries', 10)

        # Notificaciones
        config.notifications_enabled = data.get('notifications_enabled', False)
        config.telegram_bot_token = data.get('telegram_bot_token')
        config.telegram_chat_id = data.get('telegram_chat_id')
        config.telegram_messages_per_minute = data.get('telegram_messages_per_minute', 30)

        return config

    @classmethod
    def load_from_file(cls, filepath: str = "copy_trading_mini/config.json") -> 'CopyTradingConfig':
        """Carga configuración desde archivo"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            return cls.from_dict(data)
        except FileNotFoundError:
            print(f"⚠️ Archivo de configuración no encontrado: {filepath}")
            print("📝 Creando configuración por defecto...")
            return cls()
