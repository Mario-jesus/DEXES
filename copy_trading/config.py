# -*- coding: utf-8 -*-
"""
Configuración del sistema Copy Trading
"""
import json, random, uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Literal
from enum import Enum
from pathlib import Path
from decimal import Decimal, getcontext
from haikunator import Haikunator

from logging_system import AppLogger, setup_logging

# Configurar precisión de Decimal para operaciones financieras
getcontext().prec = 26

_logger = AppLogger(__name__)


class AmountMode(Enum):
    """Modos de cálculo de montos para copy trading"""
    EXACT = "exact"                                  # Replicar monto exacto
    PERCENTAGE = "percentage"                        # Porcentaje del monto original
    PERCENTAGE_OF_BALANCE = "percentage_of_balance"  # Porcentaje de nuestro balance a invertir respecto al porcentaje que invirtió el trader de su balance
    FIXED = "fixed"                                  # Monto fijo por operación
    DISTRIBUTED = "distributed"                      # Balance entre traders (Para esto ocupamos max_amount_to_invest, max_open_tokens, max_open_positions_per_token, use_balanced_allocation en True)


class TransactionType(Enum):
    """Tipos de transacciones soportadas"""
    LIGHTNING_TRADE = "lightning_trade"  # Transacciones ejecutadas por el servidor
    LOCAL_TRADE = "local_trade"          # Transacciones firmadas localmente


class NicknameGenerator(Enum):
    """Generadores de nombres para traders"""
    CUSTOM = "custom"
    HEROKU = "heroku"
    PETNAME = "petname"
    FAKER = "faker"


@dataclass
class TraderInfo:
    wallet_address: str
    nickname_generator: NicknameGenerator = NicknameGenerator.HEROKU
    nickname: str = ""

    def __post_init__(self):
        self.nickname = self.generate_nickname(self)
        _logger.debug(f"TraderInfo inicializado para wallet: {self.wallet_address}, nickname: {self.nickname}")

    @classmethod
    def generate_nickname(cls, trader_info: 'TraderInfo', token_length=4) -> str:
        """
        Genera un nickname para el trader usando el generador especificado en trader_info.
        El parámetro token_length se usa para Haikunator y puede ser usado en otros generadores si aplica.
        """
        generate_token = lambda: str(random.randint(0, 10**token_length - 1)).zfill(token_length)

        if trader_info.nickname_generator == NicknameGenerator.CUSTOM:
            if trader_info.nickname:
                nickname = trader_info.nickname.title().replace(" ", "-")
                return nickname
        elif trader_info.nickname_generator == NicknameGenerator.PETNAME and not trader_info.nickname:
            import petname
            name1 = petname.generate()
            name2 = petname.generate()
            if name1 and isinstance(name1, str) and name2 and isinstance(name2, str):
                token = generate_token()
                nickname = f"{name1}-{name2}-{token}".title()
                return nickname
        elif trader_info.nickname_generator == NicknameGenerator.FAKER and not trader_info.nickname:
            from faker import Faker
            fake = Faker()
            base_name = fake.name().title().replace(" ", "-")
            token = generate_token()
            return f"{base_name}-{token}"

        if trader_info.nickname:
            return trader_info.nickname.title().replace(" ", "-")

        nickname = Haikunator().haikunate(token_length=token_length)
        nickname = "-".join(map(lambda nickname: nickname.title(), nickname.split("-")))
        return nickname

    def to_dict(self) -> Dict[str, Any]:
        return {
            'wallet_address': self.wallet_address,
            'nickname_generator': self.nickname_generator.value,
            'nickname': self.nickname
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TraderInfo':
        return cls(
            wallet_address=data['wallet_address'],
            nickname_generator=NicknameGenerator(data['nickname_generator']),
            nickname=data.get('nickname', '')
        )


@dataclass
class TraderConfig:
    """Configuración específica por trader"""
    trader_info: TraderInfo
    enabled: bool = True

    amount_mode: Optional[AmountMode] = None
    amount_value: Optional[str] = None

    max_amount_to_invest: Optional[str] = None
    max_open_tokens: Optional[int] = None
    max_open_positions_per_token: Optional[int] = None
    use_balanced_allocation: bool = False
    min_position_size: Optional[str] = None
    max_position_size: Optional[str] = None
    adjust_position_size: bool = True
    min_position_size_percentage: Optional[str] = None
    max_position_size_percentage: Optional[str] = None
    max_daily_volume_sol_open: Optional[str] = None
    min_open_trade_interval_seconds: Optional[int] = None

    def __post_init__(self):
        _logger.debug(f"TraderConfig inicializado para trader: {self.trader_info.wallet_address}, enabled: {self.enabled}")

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        return {
            'trader_info': self.trader_info.to_dict(),
            'enabled': self.enabled,
            'amount_mode': self.amount_mode.value if self.amount_mode else None,
            'amount_value': self.amount_value,
            'max_amount_to_invest': self.max_amount_to_invest,
            'max_open_tokens': self.max_open_tokens,
            'max_open_positions_per_token': self.max_open_positions_per_token,
            'use_balanced_allocation': self.use_balanced_allocation,
            'min_position_size': self.min_position_size,
            'max_position_size': self.max_position_size,
            'min_position_size_percentage': self.min_position_size_percentage,
            'max_position_size_percentage': self.max_position_size_percentage,
            'adjust_position_size': self.adjust_position_size,
            'max_daily_volume_sol_open': self.max_daily_volume_sol_open,
            'min_open_trade_interval_seconds': self.min_open_trade_interval_seconds
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TraderConfig':
        """Crea desde diccionario"""
        return cls(
            trader_info=TraderInfo.from_dict(data['trader_info']),
            enabled=data.get('enabled', True),
            amount_mode=AmountMode(data['amount_mode']) if data.get('amount_mode') else None,
            amount_value=data.get('amount_value'),
            max_amount_to_invest=data.get('max_amount_to_invest'),
            max_open_tokens=data.get('max_open_tokens'),
            max_open_positions_per_token=data.get('max_open_positions_per_token'),
            use_balanced_allocation=data.get('use_balanced_allocation', False),
            min_position_size=data.get('min_position_size'),
            max_position_size=data.get('max_position_size'),
            min_position_size_percentage=data.get('min_position_size_percentage'),
            max_position_size_percentage=data.get('max_position_size_percentage'),
            adjust_position_size=data.get('adjust_position_size', True),
            max_daily_volume_sol_open=data.get('max_daily_volume_sol_open'),
            min_open_trade_interval_seconds=data.get('min_open_trade_interval_seconds')
        )


@dataclass
class CopyTradingConfig:
    """Configuración principal del sistema de copy trading"""
    # id de correr la instancia del sistema (el usuario no lo puede establecer, modificar ni acceder)
    system_run_id: uuid.UUID = field(default_factory=lambda: uuid.uuid4(), init=False, repr=False)

    # nombre del sistema (el usuario puede establecerlo)
    system_name: str = field(default_factory=lambda: "Copy Trading System")

    # Traders a seguir
    traders: List[TraderInfo] = field(default_factory=list)
    trader_configs: Dict[str, TraderConfig] = field(default_factory=dict)

    # Wallet y Red
    wallet_file: str = "wallets/wallet_pumpportal.json"
    rpc_url: str = "https://api.mainnet-beta.solana.com/"
    rpc_api_key: Optional[str] = None
    websocket_url: str = "wss://api.mainnet-beta.solana.com/"
	
    general_available_balance_to_invest: Optional[str] = None

    # Modo de copia y valor
    amount_mode: AmountMode = AmountMode.EXACT
    amount_value: Optional[str] = None  # Porcentaje (50.0), monto fijo en SOL, o monto exacto a copiar

    # Validaciones
    validations_enabled: bool = True
    strict_mode: bool = False                                      # Cambiado a False para permitir WARNING en copy trading
    max_traders_per_token: int = 1                                 # Maximo de traders que pueden tener una posicion abierta en un token
    max_amount_to_invest_per_trader: Optional[str] = None          # Maximo de SOL que puede invertir un trader en posiciones abiertas
    max_open_tokens_per_trader: Optional[int] = None               # Maximo de tokens que puede tener un trader
    max_open_positions_per_token_per_trader: Optional[int] = None  # Maximo de posiciones que puede tener un trader en un token
    use_balanced_allocation_per_trader: bool = False               # Si se usa la distribucion balanceada de la inversion, el balance para cada trader seria max_amount_to_invest_per_trader / max_open_tokens_per_trader
    min_position_size: Optional[str] = None                        # Minimo de SOL que puede tener una posicion
    max_position_size: Optional[str] = None                        # Maximo de SOL que puede tener una posicion
    min_position_size_percentage: Optional[str] = None             # Minimo de SOL que puede tener una posicion en porcentaje (0-100) de nuestro balance
    max_position_size_percentage: Optional[str] = None             # Maximo de SOL que puede tener una posicion en porcentaje (0-100) de nuestro balance
    adjust_position_size: bool = True                              # Si se ajusta el tamaño de la posicion automaticamente si esta activado en base a max_position_size y min_position_size
    max_daily_volume_sol_open: Optional[str] = None                # Maximo de SOL que puede tener un trader en un dia en posiciones abiertas
    min_open_trade_interval_seconds_per_trader: Optional[int] = None    # Minimo de segundos que debe esperar un trader para hacer un trade de apertura de posicion
    min_global_available_balance_threshold_percent: Optional[str] = None    # Porcentaje (0-100) del presupuesto global por debajo del cual se bloquean BUY
    graceful_shutdown_enabled: bool = False                        # Si se habilita el shutdown graceful, se espera a que todas las posiciones se cierren antes de cerrar el sistema
    pump_amm_min_sol_amount_threshold: Optional[str] = None        # Solo copiar trades si el monto es mayor a este valor en SOL para pool pump-amm
    other_pools_min_sol_amount_threshold: Optional[str] = None     # Mínimo de SOL para pools distintos de pump-amm
    pump_amm_max_sol_amount_threshold: Optional[str] = None        # Solo copiar trades si el monto es menor o igual a este valor en SOL para pool pump-amm
    other_pools_max_sol_amount_threshold: Optional[str] = None     # Máximo de SOL para pools distintos de pump-amm
    is_trade_activity_filter_enabled: bool = True                  # Si se habilita el filtro de actividad de trades, solo copiar trades si se han observado N trades previos en el token
    trade_activity_window_seconds: int = 60                        # Ventana de tiempo para contar trades
    min_trade_count_threshold: int = 3                             # Número mínimo de trades antes de copiar

    # Configuración de Transacciones
    transaction_type: TransactionType = TransactionType.LIGHTNING_TRADE
    pool_type: Literal["pump", "raydium", "pump-amm", "launchlab", "raydium-cpmm", "bonk", "auto"] = "auto"
    skip_preflight: bool = True
    jito_only: bool = False  # Solo para lightning_trade

    # Parámetros de trading
    slippage_tolerance_for_buy: str = "15.0"  # 15%
    slippage_tolerance_for_sell: str = "100.0"  # 100%
    priority_fee_sol: str = "0.0005"  # 0.0005 SOL
    max_execution_delay_seconds: int = 30

    # Logging
    logging_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = "INFO"
    log_to_file: bool = False
    log_to_console: bool = True
    log_file_path: str = "copy_trading/logs"
    log_filename: str = "copy_trading_%Y-%m-%d_%H-%M-%S.log"
    enable_logfire: bool = False
    min_logfire_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = "WARNING"
    logfire_config: Dict[str, Any] = field(default_factory=lambda: {
        'service_name': 'copy_trading_development',
        'environment': 'development',
        'tags': {
            'project': 'pumpfun-copy-trading-system',
            'version': '1.0.0'
        }
    })

    # Sistema
    dry_run: bool = False
    auto_close_positions: bool = True
    position_tracking_interval: int = 60  # segundos
    max_queue_size: Optional[int] = None

    # Timeout de posiciones
    position_timeout_enabled: bool = False  # Habilitar cierre automático por timeout
    max_position_age_seconds: Optional[int] = None  # Tiempo máximo en segundos antes de cerrar automáticamente
    position_timeout_check_interval: int = 300  # Intervalo de verificación en segundos (default: 5 minutos)
    position_timeout_max_retry_attempts: int = 3  # Máximo número de reintentos antes de remover de cola de abiertas

    # Drawdown (gestión de riesgo)
    drawdown_enabled: bool = True  # Habilitar monitoreo de drawdown
    max_drawdown_percent: Optional[str] = None  # Máximo drawdown porcentual permitido (ej: "20.0" = 20%)
    max_drawdown_sol: Optional[str] = None  # Máximo drawdown en SOL permitido (ej: "5.0" = 5 SOL)
    drawdown_check_interval: int = 60  # Intervalo de verificación en segundos (default: 60 segundos)
    drawdown_action: Literal["block_buys", "stop_trading", "notify_only"] = "block_buys"  # Acción cuando se excede el umbral
    drawdown_recovery_threshold_percent: Optional[str] = None  # Umbral de recuperación porcentual para reactivar trading (ej: "10.0" = 10%)

    # Stop Loss y Take Profit (gestión de riesgo por posición)
    stop_loss_enabled: bool = False  # Habilitar trailing stop loss
    stop_loss_percentage: Optional[str] = None  # Porcentaje de pérdida para liquidar (ej: "10.0" = 10%)
    take_profit_enabled: bool = False  # Habilitar take profit
    take_profit_percentage: Optional[str] = None  # Porcentaje de ganancia para liquidar (ej: "20.0" = 20%)
    risk_management_max_liquidation_retries: int = 3  # Máximo número de reintentos de liquidación antes de descartar posición
    risk_management_max_concurrent_check_positions: int = 10  # Máximo número de verificaciones de posiciones concurrentes (default: 10)
    risk_management_sol_price_cache_ttl: int = 3600  # TTL del cache de precio SOL/USD en segundos (default: 1h, solo para notificaciones)

    # Persistencia
    data_path: str = "copy_trading/data"
    save_interval_seconds: int = 300  # 5 minutos

    # WebSocket
    websocket_reconnect_delay: int = 5
    websocket_max_retries: int = 10

    # Redis bridge para PumpFun WebSocket compartido
    use_pumpfun_redis_bridge: bool = True
    pumpfun_redis_url: Optional[str] = None
    pumpfun_redis_namespace: str = "pumpfun"
    pumpfun_redis_client_id: Optional[str] = None
    pumpfun_redis_ack_timeout_seconds: int = 10

    # Notificaciones
    notifications_enabled: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_messages_per_minute: int = 30  # Límite de mensajes por minuto para Telegram

    def __post_init__(self):
        setup_logging(
            console_output=self.log_to_console,
            file_output=self.log_to_file,
            log_directory=self.log_file_path,
            log_filename=self.log_filename,
            min_level_to_process=self.logging_level,
            enable_logfire=self.enable_logfire,
            logfire_config=self.logfire_config,
            logfire_min_level=self.min_logfire_level
        )
        _logger.info("Inicializando configuración de Copy Trading")

        # Validar que el balance por trader sea valido, si se configura
        if self.max_amount_to_invest_per_trader is not None:
            total_amount_per_trader = Decimal(self.max_amount_to_invest_per_trader) * Decimal(len(self.traders))
            if total_amount_per_trader > Decimal(self.general_available_balance_to_invest or "0.0"):
                error_msg = f"El balance disponible para invertir ({self.general_available_balance_to_invest or "0.0"} SOL) es menor al balance por trader ({total_amount_per_trader} SOL)"
                _logger.error(error_msg)
                raise ValueError(error_msg)

            if self.max_open_tokens_per_trader is not None and self.amount_mode == AmountMode.FIXED:
                amount_per_token = Decimal(self.max_amount_to_invest_per_trader) / Decimal(self.max_open_tokens_per_trader)
                if self.amount_value is not None and Decimal(self.amount_value) > amount_per_token:
                    error_msg = f"El valor de la cantidad a invertir ({self.amount_value} SOL) es mayor al balance por token ({amount_per_token} SOL)"
                    _logger.error(error_msg)
                    raise ValueError(error_msg)

        _logger.debug(f"Configuración inicializada con {len(self.traders)} traders")

        # Validar rango del porcentaje de umbral mínimo global (0 a 100)
        if self.min_global_available_balance_threshold_percent is None:
            return
        try:
            pct = Decimal(self.min_global_available_balance_threshold_percent)
            if pct < 0 or pct > 100:
                error_msg = (
                    f"min_global_available_balance_threshold_percent ({self.min_global_available_balance_threshold_percent}) "
                    f"debe estar entre 0 y 100"
                )
                _logger.error(error_msg)
                raise ValueError(error_msg)
        except Exception as e:
            _logger.error(f"Valor inválido para min_global_available_balance_threshold_percent: {e}")
            raise

    def is_lightning_trade(self) -> bool:
        """Verifica si está configurado para usar Lightning Trade"""
        return self.transaction_type == TransactionType.LIGHTNING_TRADE

    def is_local_trade(self) -> bool:
        """Verifica si está configurado para usar Local Trade"""
        return self.transaction_type == TransactionType.LOCAL_TRADE

    def get_transaction_params(self) -> Dict[str, Any]:
        """Obtiene parámetros comunes para transacciones"""
        params: Dict[str, Any] = {
            'slippage_for_buy': self.slippage_tolerance_for_buy,
            'slippage_for_sell': self.slippage_tolerance_for_sell,
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

    def get_trader_info(self, wallet_address: str) -> Optional[TraderInfo]:
        """Obtiene la información de un trader específico"""
        return next((trader for trader in self.traders if trader.wallet_address == wallet_address), None)

    def add_trader_info(self, trader_info: TraderInfo, config: Optional[TraderConfig] = None):
        """Añade un trader con configuración opcional"""
        if trader_info not in self.traders:
            self.traders.append(trader_info)
            _logger.info(f"Trader añadido: {trader_info.wallet_address} ({trader_info.nickname})")

        if config:
            self.trader_configs[trader_info.wallet_address] = config
            _logger.debug(f"Configuración personalizada añadida para trader: {trader_info.wallet_address}")

    def add_trader_config_by_wallet_address(self, wallet_address: str, config: TraderConfig):
        """Añade una configuración de trader específica"""
        if wallet_address not in [trader.wallet_address for trader in self.traders]:
            self.add_trader_info(TraderInfo(wallet_address=wallet_address))

        self.trader_configs[wallet_address] = config
        _logger.debug(f"Configuración personalizada añadida para trader: {wallet_address}")

    def remove_trader_info(self, trader_info: TraderInfo):
        """Elimina un trader"""
        if trader_info in self.traders:
            self.traders.remove(trader_info)
            _logger.info(f"Trader eliminado: {trader_info.wallet_address} ({trader_info.nickname})")
        if trader_info.wallet_address in self.trader_configs:
            del self.trader_configs[trader_info.wallet_address]
            _logger.debug(f"Configuración eliminada para trader: {trader_info.wallet_address}")

    def add_trader_by_wallet_address(self, wallet_address: str, config: Optional[TraderConfig] = None):
        """Añade un trader por su dirección de wallet"""
        trader_info = self.get_trader_info(wallet_address)
        if not trader_info:
            trader_info = TraderInfo(wallet_address=wallet_address)
            self.add_trader_info(trader_info, config)
        else:
            _logger.debug(f"Trader ya existe: {wallet_address}")

    def get_trader_config(self, trader_info: TraderInfo) -> Optional[TraderConfig]:
        """Obtiene la configuración de un trader específico"""
        if trader_info.wallet_address in self.trader_configs:
            return self.trader_configs[trader_info.wallet_address]

    def to_dict(self) -> Dict[str, Any]:
        """Convierte la configuración a diccionario"""
        return {
            'traders': [trader.to_dict() for trader in self.traders],
            'trader_configs': {k: v.to_dict() for k, v in self.trader_configs.items()},
            'system_name': self.system_name,
            'wallet_file': self.wallet_file,
            'rpc_url': self.rpc_url,
            'rpc_api_key': self.rpc_api_key,
            'websocket_url': self.websocket_url,
            'general_available_balance_to_invest': self.general_available_balance_to_invest,
            'amount_mode': self.amount_mode.value,
            'amount_value': self.amount_value,
            'validations_enabled': self.validations_enabled,
            'strict_mode': self.strict_mode,
            'max_traders_per_token': self.max_traders_per_token,
            'max_amount_to_invest_per_trader': self.max_amount_to_invest_per_trader,
            'max_open_tokens_per_trader': self.max_open_tokens_per_trader,
            'max_open_positions_per_token_per_trader': self.max_open_positions_per_token_per_trader,
            'use_balanced_allocation_per_trader': self.use_balanced_allocation_per_trader,
            'min_position_size': self.min_position_size,
            'max_position_size': self.max_position_size,
            'min_position_size_percentage': self.min_position_size_percentage,
            'max_position_size_percentage': self.max_position_size_percentage,
            'adjust_position_size': self.adjust_position_size,
            'max_daily_volume_sol_open': self.max_daily_volume_sol_open,
            'min_open_trade_interval_seconds_per_trader': self.min_open_trade_interval_seconds_per_trader,
            'min_global_available_balance_threshold_percent': self.min_global_available_balance_threshold_percent,
            'graceful_shutdown_enabled': self.graceful_shutdown_enabled,
            'pump_amm_min_sol_amount_threshold': self.pump_amm_min_sol_amount_threshold,
            'other_pools_min_sol_amount_threshold': self.other_pools_min_sol_amount_threshold,
            'pump_amm_max_sol_amount_threshold': self.pump_amm_max_sol_amount_threshold,
            'other_pools_max_sol_amount_threshold': self.other_pools_max_sol_amount_threshold,
            'is_trade_activity_filter_enabled': self.is_trade_activity_filter_enabled,
            'trade_activity_window_seconds': self.trade_activity_window_seconds,
            'min_trade_count_threshold': self.min_trade_count_threshold,
            'transaction_type': self.transaction_type.value,
            'pool_type': self.pool_type,
            'skip_preflight': self.skip_preflight,
            'jito_only': self.jito_only,
            'slippage_tolerance_for_buy': self.slippage_tolerance_for_buy,
            'slippage_tolerance_for_sell': self.slippage_tolerance_for_sell,
            'priority_fee_sol': self.priority_fee_sol,
            'max_execution_delay_seconds': self.max_execution_delay_seconds,
            'logging_level': self.logging_level,
            'log_to_file': self.log_to_file,
            'log_to_console': self.log_to_console,
            'log_file_path': self.log_file_path,
            'log_filename': self.log_filename,
            'enable_logfire': self.enable_logfire,
            'min_logfire_level': self.min_logfire_level,
            'logfire_config': self.logfire_config,
            'dry_run': self.dry_run,
            'auto_close_positions': self.auto_close_positions,
            'position_tracking_interval': self.position_tracking_interval,
            'max_queue_size': self.max_queue_size,
            'position_timeout_enabled': self.position_timeout_enabled,
            'max_position_age_seconds': self.max_position_age_seconds,
            'position_timeout_check_interval': self.position_timeout_check_interval,
            'position_timeout_max_retry_attempts': self.position_timeout_max_retry_attempts,
            'drawdown_enabled': self.drawdown_enabled,
            'max_drawdown_percent': self.max_drawdown_percent,
            'max_drawdown_sol': self.max_drawdown_sol,
            'drawdown_check_interval': self.drawdown_check_interval,
            'drawdown_action': self.drawdown_action,
            'drawdown_recovery_threshold_percent': self.drawdown_recovery_threshold_percent,
            'stop_loss_enabled': self.stop_loss_enabled,
            'stop_loss_percentage': self.stop_loss_percentage,
            'take_profit_enabled': self.take_profit_enabled,
            'take_profit_percentage': self.take_profit_percentage,
            'risk_management_max_liquidation_retries': self.risk_management_max_liquidation_retries,
            'risk_management_max_concurrent_check_positions': self.risk_management_max_concurrent_check_positions,
            'risk_management_sol_price_cache_ttl': self.risk_management_sol_price_cache_ttl,
            'data_path': self.data_path,
            'save_interval_seconds': self.save_interval_seconds,
            'websocket_reconnect_delay': self.websocket_reconnect_delay,
            'websocket_max_retries': self.websocket_max_retries,
            'use_pumpfun_redis_bridge': self.use_pumpfun_redis_bridge,
            'pumpfun_redis_url': self.pumpfun_redis_url,
            'pumpfun_redis_namespace': self.pumpfun_redis_namespace,
            'pumpfun_redis_client_id': self.pumpfun_redis_client_id,
            'pumpfun_redis_ack_timeout_seconds': self.pumpfun_redis_ack_timeout_seconds,
            'notifications_enabled': self.notifications_enabled,
            'telegram_bot_token': self.telegram_bot_token,
            'telegram_chat_id': self.telegram_chat_id,
            'telegram_messages_per_minute': self.telegram_messages_per_minute
        }

    def save_to_file(self, filepath: str = "copy_trading/config.json"):
        """Guarda la configuración en archivo"""
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(self.to_dict(), f, indent=2)
            _logger.info(f"Configuración guardada exitosamente en: {filepath}")
        except Exception as e:
            _logger.error(f"Error al guardar configuración en {filepath}: {e}")
            raise

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CopyTradingConfig':
        """Crea configuración desde diccionario"""
        _logger.debug("Creando configuración desde diccionario")

        # Preparar traders
        traders = [TraderInfo.from_dict(trader) for trader in data.get('traders', [])]

        # Preparar trader_configs
        trader_configs = {}
        trader_configs_data = data.get('trader_configs', {})
        for wallet, tconfig in trader_configs_data.items():
            trader_configs[wallet] = TraderConfig.from_dict(tconfig)

        # Crear configuración pasando todos los parámetros al constructor
        config = cls(
            # Traders a seguir
            traders=traders,
            trader_configs=trader_configs,

            # Nombre del sistema
            system_name=data.get('system_name', "Copy Trading System"),

            # Wallet y Red
            wallet_file=data.get('wallet_file', 'wallets/wallet_pumpportal.json'),
            rpc_url=data.get('rpc_url', 'https://api.mainnet-beta.solana.com/'),
            rpc_api_key=data.get('rpc_api_key'),
            websocket_url=data.get('websocket_url', 'wss://api.mainnet-beta.solana.com/'),
            general_available_balance_to_invest=data.get('general_available_balance_to_invest'),

            # Modo de copia y valor
            amount_mode=AmountMode(data.get('amount_mode', AmountMode.PERCENTAGE.value)),
            amount_value=data.get('amount_value', "50.0"),

            # Validaciones
            validations_enabled=data.get('validations_enabled', True),
            strict_mode=data.get('strict_mode', False),
            max_traders_per_token=int(data.get('max_traders_per_token', 1)),
            max_amount_to_invest_per_trader=data.get('max_amount_to_invest_per_trader'),
            max_open_tokens_per_trader=data.get('max_open_tokens_per_trader'),
            max_open_positions_per_token_per_trader=data.get('max_open_positions_per_token_per_trader'),
            use_balanced_allocation_per_trader=data.get('use_balanced_allocation_per_trader', False),
            min_position_size=data.get('min_position_size'),
            max_position_size=data.get('max_position_size'),
            min_position_size_percentage=data.get('min_position_size_percentage'),
            max_position_size_percentage=data.get('max_position_size_percentage'),
            adjust_position_size=data.get('adjust_position_size', True),
            max_daily_volume_sol_open=data.get('max_daily_volume_sol_open'),
            min_open_trade_interval_seconds_per_trader=data.get('min_open_trade_interval_seconds_per_trader'),
            min_global_available_balance_threshold_percent=data.get('min_global_available_balance_threshold_percent'),
            graceful_shutdown_enabled=data.get('graceful_shutdown_enabled', False),
            pump_amm_min_sol_amount_threshold=data.get('pump_amm_min_sol_amount_threshold'),
            other_pools_min_sol_amount_threshold=data.get('other_pools_min_sol_amount_threshold'),
            pump_amm_max_sol_amount_threshold=data.get('pump_amm_max_sol_amount_threshold'),
            other_pools_max_sol_amount_threshold=data.get('other_pools_max_sol_amount_threshold'),
            is_trade_activity_filter_enabled=data.get('is_trade_activity_filter_enabled', True),
            trade_activity_window_seconds=data.get('trade_activity_window_seconds', 60),
            min_trade_count_threshold=data.get('min_trade_count_threshold', 3),

            # Configuración de Transacciones
            transaction_type=TransactionType(data.get('transaction_type', TransactionType.LIGHTNING_TRADE.value)),
            pool_type=data.get('pool_type', 'auto'),
            skip_preflight=data.get('skip_preflight', True),
            jito_only=data.get('jito_only', False),

            # Parámetros de trading
            slippage_tolerance_for_buy=data.get('slippage_tolerance_for_buy', "15.0"),
            slippage_tolerance_for_sell=data.get('slippage_tolerance_for_sell', "100.0"),
            priority_fee_sol=data.get('priority_fee_sol', "0.000005"),
            max_execution_delay_seconds=data.get('max_execution_delay_seconds', 30),

            # Logging
            logging_level=data.get('logging_level', 'INFO'),
            log_to_file=data.get('log_to_file', False),
            log_to_console=data.get('log_to_console', True),
            log_file_path=data.get('log_file_path', 'copy_trading/logs'),
            log_filename=data.get('log_filename', 'copy_trading_%Y-%m-%d_%H-%M-%S.log'),
            enable_logfire=data.get('enable_logfire', False),
            min_logfire_level=data.get('min_logfire_level', 'WARNING'),
            logfire_config=data.get('logfire_config', {
                'service_name': 'copy_trading_development',
                'environment': 'development',
                'tags': {
                    'project': 'pumpfun-copy-trading-system',
                    'version': '1.0.0'
                }
            }),

            # Sistema
            dry_run=data.get('dry_run', False),
            auto_close_positions=data.get('auto_close_positions', True),
            position_tracking_interval=data.get('position_tracking_interval', 60),
            max_queue_size=data.get('max_queue_size'),
            position_timeout_enabled=data.get('position_timeout_enabled', False),
            max_position_age_seconds=data.get('max_position_age_seconds'),
            position_timeout_check_interval=data.get('position_timeout_check_interval', 300),
            position_timeout_max_retry_attempts=data.get('position_timeout_max_retry_attempts', 3),
            drawdown_enabled=data.get('drawdown_enabled', True),
            max_drawdown_percent=data.get('max_drawdown_percent'),
            max_drawdown_sol=data.get('max_drawdown_sol'),
            drawdown_check_interval=data.get('drawdown_check_interval', 60),
            drawdown_action=data.get('drawdown_action', 'block_buys'),
            drawdown_recovery_threshold_percent=data.get('drawdown_recovery_threshold_percent'),
            stop_loss_enabled=data.get('stop_loss_enabled', False),
            stop_loss_percentage=data.get('stop_loss_percentage'),
            take_profit_enabled=data.get('take_profit_enabled', False),
            take_profit_percentage=data.get('take_profit_percentage'),
            risk_management_max_liquidation_retries=data.get('risk_management_max_liquidation_retries', 3),
            risk_management_max_concurrent_check_positions=data.get('risk_management_max_concurrent_check_positions', 10),
            risk_management_sol_price_cache_ttl=data.get('risk_management_sol_price_cache_ttl', 3600),
            data_path=data.get('data_path', 'copy_trading/data'),
            save_interval_seconds=data.get('save_interval_seconds', 300),

            # WebSocket
            websocket_reconnect_delay=data.get('websocket_reconnect_delay', 5),
            websocket_max_retries=data.get('websocket_max_retries', 10),
            use_pumpfun_redis_bridge=data.get('use_pumpfun_redis_bridge', True),
            pumpfun_redis_url=data.get('pumpfun_redis_url'),
            pumpfun_redis_namespace=data.get('pumpfun_redis_namespace', 'pumpfun'),
            pumpfun_redis_client_id=data.get('pumpfun_redis_client_id'),
            pumpfun_redis_ack_timeout_seconds=data.get('pumpfun_redis_ack_timeout_seconds', 10),

            # Notificaciones
            notifications_enabled=data.get('notifications_enabled', False),
            telegram_bot_token=data.get('telegram_bot_token'),
            telegram_chat_id=data.get('telegram_chat_id'),
            telegram_messages_per_minute=data.get('telegram_messages_per_minute', 30)
        )

        _logger.debug(f"Configuración creada con {len(config.traders)} traders y {len(config.trader_configs)} configuraciones")
        return config

    @classmethod
    def load_from_file(cls, filepath: str = "copy_trading/config.json") -> 'CopyTradingConfig':
        """Carga configuración desde archivo"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            _logger.info(f"Configuración cargada exitosamente desde: {filepath}")
            return cls.from_dict(data)
        except FileNotFoundError:
            _logger.warning(f"Archivo de configuración no encontrado: {filepath}")
            _logger.info("Creando configuración por defecto...")
            return cls()
        except Exception as e:
            _logger.error(f"Error al cargar configuración desde {filepath}: {e}")
            raise
