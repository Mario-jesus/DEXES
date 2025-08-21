# -*- coding: utf-8 -*-
"""
Configuración del sistema Copy Trading
"""
import json, random
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
    EXACT = "exact"          # Replicar monto exacto
    PERCENTAGE = "percentage" # Porcentaje del monto original
    FIXED = "fixed"          # Monto fijo por operación
    DISTRIBUTED = "distributed"    # Balance entre traders (Para esto ocupamos max_amount_to_invest, max_open_tokens, max_open_positions_per_token, use_balanced_allocation en True)


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

    amount_mode: Optional[AmountMode] = AmountMode.EXACT
    amount_value: Optional[str] = None

    max_amount_to_invest: Optional[str] = None
    max_open_tokens: Optional[int] = None
    max_open_positions_per_token: Optional[int] = None
    use_balanced_allocation: bool = False
    min_position_size: Optional[str] = None
    max_position_size: Optional[str] = None
    adjust_position_size: bool = True
    max_daily_volume_sol_open: Optional[str] = None
    min_trade_interval_seconds: int = 1

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
            'adjust_position_size': self.adjust_position_size,
            'max_daily_volume_sol_open': self.max_daily_volume_sol_open,
            'min_trade_interval_seconds': self.min_trade_interval_seconds
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
            adjust_position_size=data.get('adjust_position_size', True),
            max_daily_volume_sol_open=data.get('max_daily_volume_sol_open'),
            min_trade_interval_seconds=data.get('min_trade_interval_seconds', 1)
        )


@dataclass
class CopyTradingConfig:
    """Configuración principal del sistema de copy trading"""

    # Traders a seguir
    traders: List[TraderInfo] = field(default_factory=list)
    trader_configs: Dict[str, TraderConfig] = field(default_factory=dict)

    # Wallet y Red
    wallet_file: str = "wallets/wallet_pumpportal.json"
    rpc_url: str = "https://api.mainnet-beta.solana.com/"
    websocket_url: str = "wss://api.mainnet-beta.solana.com/"

    general_available_balance_to_invest: str = "0.0"

    # Modo de copia y valor
    amount_mode: AmountMode = AmountMode.EXACT
    amount_value: Optional[str] = None  # Porcentaje (50.0), monto fijo en SOL, o monto exacto a copiar

    # Validaciones
    validations_enabled: bool = True
    strict_mode: bool = False                                      # Cambiado a False para permitir WARNING en copy trading
    max_traders_per_token: Optional[int] = None                    # Maximo de traders que pueden tener una posicion abierta en un token
    max_amount_to_invest_per_trader: Optional[str] = None          # Maximo de SOL que puede invertir un trader en posiciones abiertas
    max_open_tokens_per_trader: Optional[int] = None               # Maximo de tokens que puede tener un trader
    max_open_positions_per_token_per_trader: Optional[int] = None  # Maximo de posiciones que puede tener un trader en un token
    use_balanced_allocation_per_trader: bool = False               # Si se usa la distribucion balanceada de la inversion, el balance para cada trader seria max_amount_to_invest_per_trader / max_open_tokens_per_trader
    min_position_size: Optional[str] = None                        # Minimo de SOL que puede tener una posicion
    max_position_size: Optional[str] = None                        # Maximo de SOL que puede tener una posicion
    adjust_position_size: bool = True                              # Si se ajusta el tamaño de la posicion automaticamente si esta activado en base a max_position_size y min_position_size
    max_daily_volume_sol_open: Optional[str] = None                # Maximo de SOL que puede tener un trader en un dia en posiciones abiertas
    min_trade_interval_seconds_per_trader: int = 1                 # Minimo de segundos que debe esperar un trader para hacer un trade

    # Configuración de Transacciones
    transaction_type: TransactionType = TransactionType.LIGHTNING_TRADE
    pool_type: Literal["pump", "raydium", "pump-amm", "launchlab", "raydium-cpmm", "bonk", "auto"] = "auto"
    skip_preflight: bool = True
    jito_only: bool = False  # Solo para lightning_trade

    # Parámetros de trading
    slippage_tolerance: float = 0.01  # 1%
    priority_fee_sol: float = 0.0005  # 0.0005 SOL
    max_execution_delay_seconds: int = 30

    # Logging
    logging_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = "INFO"
    log_to_file: bool = False
    log_to_console: bool = True
    log_file_path: str = "copy_trading/logs"
    log_filename: str = "copy_trading_%Y-%m-%d_%H-%M-%S.log"
    enable_logfire: bool = False
    min_logfire_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = "WARNING"
    logfire_config: Dict[str, Any] = {
        'service_name': 'copy_trading_development',
        'environment': 'development',
        'tags': {
            'project': 'pumpfun-copy-trading-system',
            'version': '1.0.0'
        },
        'min_level': 'WARNING'
    }

    # Sistema
    dry_run: bool = False
    auto_close_positions: bool = True
    position_tracking_interval: int = 60  # segundos
    max_queue_size: Optional[int] = None

    # Persistencia
    data_path: str = "copy_trading/data"
    save_interval_seconds: int = 300  # 5 minutos

    # WebSocket
    websocket_reconnect_delay: int = 5
    websocket_max_retries: int = 10

    # Notificaciones
    notifications_enabled: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_messages_per_minute: int = 30  # Límite de mensajes por minuto para Telegram

    def __post_init__(self):
        setup_logging(
            min_level_to_process=self.logging_level,
            file_output=self.log_to_file,
            console_output=self.log_to_console,
            log_directory=self.log_file_path,
            log_filename=self.log_filename,
            enable_logfire=self.enable_logfire,
            logfire_config=self.logfire_config
        )
        _logger.info("Inicializando configuración de Copy Trading")

        # Validar que el balance por trader sea valido, si se configura
        if self.max_amount_to_invest_per_trader is not None:
            total_amount_per_trader = Decimal(self.max_amount_to_invest_per_trader) * Decimal(len(self.traders))
            if total_amount_per_trader > Decimal(self.general_available_balance_to_invest):
                error_msg = f"El balance disponible para invertir ({self.general_available_balance_to_invest} SOL) es menor al balance por trader ({total_amount_per_trader} SOL)"
                _logger.error(error_msg)
                raise ValueError(error_msg)

            if self.max_open_tokens_per_trader is not None and self.amount_mode == AmountMode.FIXED:
                amount_per_token = Decimal(self.max_amount_to_invest_per_trader) / Decimal(self.max_open_tokens_per_trader)
                if self.amount_value is not None and Decimal(self.amount_value) > amount_per_token:
                    error_msg = f"El valor de la cantidad a invertir ({self.amount_value} SOL) es mayor al balance por token ({amount_per_token} SOL)"
                    _logger.error(error_msg)
                    raise ValueError(error_msg)

        _logger.debug(f"Configuración inicializada con {len(self.traders)} traders")

    def is_lightning_trade(self) -> bool:
        """Verifica si está configurado para usar Lightning Trade"""
        return self.transaction_type == TransactionType.LIGHTNING_TRADE

    def is_local_trade(self) -> bool:
        """Verifica si está configurado para usar Local Trade"""
        return self.transaction_type == TransactionType.LOCAL_TRADE

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
            'wallet_file': self.wallet_file,
            'rpc_url': self.rpc_url,
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
            'adjust_position_size': self.adjust_position_size,
            'max_daily_volume_sol_open': self.max_daily_volume_sol_open,
            'min_trade_interval_seconds_per_trader': self.min_trade_interval_seconds_per_trader,
            'transaction_type': self.transaction_type.value,
            'pool_type': self.pool_type,
            'skip_preflight': self.skip_preflight,
            'jito_only': self.jito_only,
            'slippage_tolerance': self.slippage_tolerance,
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
            'data_path': self.data_path,
            'save_interval_seconds': self.save_interval_seconds,
            'websocket_reconnect_delay': self.websocket_reconnect_delay,
            'websocket_max_retries': self.websocket_max_retries,
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

            # Wallet y Red
            wallet_file=data.get('wallet_file', 'wallets/wallet_pumpportal.json'),
            rpc_url=data.get('rpc_url', 'https://api.mainnet-beta.solana.com/'),
            websocket_url=data.get('websocket_url', 'wss://api.mainnet-beta.solana.com/'),
            general_available_balance_to_invest=data.get('general_available_balance_to_invest', "0.0"),

            # Modo de copia y valor
            amount_mode=AmountMode(data.get('amount_mode', AmountMode.PERCENTAGE.value)),
            amount_value=data.get('amount_value', "50.0"),

            # Validaciones
            validations_enabled=data.get('validations_enabled', True),
            strict_mode=data.get('strict_mode', False),
            max_traders_per_token=data.get('max_traders_per_token'),
            max_amount_to_invest_per_trader=data.get('max_amount_to_invest_per_trader'),
            max_open_tokens_per_trader=data.get('max_open_tokens_per_trader'),
            max_open_positions_per_token_per_trader=data.get('max_open_positions_per_token_per_trader'),
            use_balanced_allocation_per_trader=data.get('use_balanced_allocation_per_trader', False),
            min_position_size=data.get('min_position_size'),
            max_position_size=data.get('max_position_size'),
            adjust_position_size=data.get('adjust_position_size', True),
            max_daily_volume_sol_open=data.get('max_daily_volume_sol_open'),
            min_trade_interval_seconds_per_trader=data.get('min_trade_interval_seconds_per_trader', 1),

            # Configuración de Transacciones
            transaction_type=TransactionType(data.get('transaction_type', TransactionType.LIGHTNING_TRADE.value)),
            pool_type=data.get('pool_type', 'auto'),
            skip_preflight=data.get('skip_preflight', True),
            jito_only=data.get('jito_only', False),

            # Parámetros de trading
            slippage_tolerance=data.get('slippage_tolerance', 0.01),
            priority_fee_sol=data.get('priority_fee_sol', 0.0005),
            max_execution_delay_seconds=data.get('max_execution_delay_seconds', 30),

            # Logging
            logging_level=data.get('logging_level', 'INFO'),
            log_to_file=data.get('log_to_file', False),
            log_to_console=data.get('log_to_console', True),
            log_file_path=data.get('log_file_path', 'copy_trading/logs'),
            log_filename=data.get('log_filename', 'copy_trading_%Y-%m-%d_%H-%M-%S.log'),
            enable_logfire=data.get('enable_logfire', False),
            min_logfire_level=data.get('min_logfire_level', 'WARNING'),
            logfire_config=data.get('logfire_config', cls.logfire_config),

            # Sistema
            dry_run=data.get('dry_run', False),
            auto_close_positions=data.get('auto_close_positions', True),
            position_tracking_interval=data.get('position_tracking_interval', 60),
            max_queue_size=data.get('max_queue_size'),
            data_path=data.get('data_path', 'copy_trading/data'),
            save_interval_seconds=data.get('save_interval_seconds', 300),

            # WebSocket
            websocket_reconnect_delay=data.get('websocket_reconnect_delay', 5),
            websocket_max_retries=data.get('websocket_max_retries', 10),

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
