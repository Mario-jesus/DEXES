# -*- coding: utf-8 -*-
"""
Motor de validaciones para trades
"""
from enum import Enum
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from solders.keypair import Keypair

from solana_manager.account_info import SolanaAccountInfo

from .config import CopyTradingConfig
from .logger import CopyTradingLogger


class ValidationResult(Enum):
    """Resultado de una validación"""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


@dataclass
class ValidationCheck:
    """Resultado de una validación individual"""
    name: str
    result: ValidationResult = ValidationResult.PASSED
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def fail(self, message: str, details: Optional[Dict[str, Any]] = None):
        """Marca el check como fallido."""
        self.result = ValidationResult.FAILED
        self.message = message
        self.details = details or {}

    def passthrough(self, message: str, details: Optional[Dict[str, Any]] = None):
        """Marca el check como aprobado."""
        self.result = ValidationResult.PASSED
        self.message = message
        self.details = details or {}

    def warning(self, message: str, details: Optional[Dict[str, Any]] = None):
        """Marca el check como una advertencia."""
        self.result = ValidationResult.WARNING
        self.message = message
        self.details = details or {}

    def is_ok(self, strict_mode: bool = True) -> bool:
        """Determina si el resultado es aceptable."""
        if strict_mode:
            return self.result == ValidationResult.PASSED
        return self.result != ValidationResult.FAILED


class ValidationEngine:
    """Motor de validaciones para trades"""

    def __init__(self, 
                    config: CopyTradingConfig, 
                    logger: CopyTradingLogger):
        """
        Inicializa el motor de validaciones
        
        Args:
            config: Configuración del sistema
            logger: Logger para registrar eventos
        """
        self.config = config
        self.logger = logger
        self.keypair: Optional[Keypair] = None
        self.account_info: Optional[SolanaAccountInfo] = None

        # Estado para validaciones
        self.daily_volume: Dict[str, float] = {}  # {trader: volume}
        self.daily_trades: Dict[str, int] = {}    # {trader: count}
        self.last_trade_time: Dict[str, datetime] = {} # {trader_token: time}

        self.validation_stats = {
            'total_checks': 0,
            'passed': 0,
            'failed': 0,
            'warnings': 0
        }

        # Reset diario
        self.last_reset = datetime.now().date()

    async def initialize(self, keypair: Keypair):
        """
        Inicializa el motor con el keypair y otros recursos asíncronos.
        
        Args:
            keypair: Keypair de la wallet de trading.
        """
        self.keypair = keypair
        self.account_info = SolanaAccountInfo(rpc_url=self.config.rpc_url)
        await self.account_info.__aenter__()
        self.logger.info("Validation engine inicializado")

    async def close(self):
        """Cierra los recursos del motor de validación (ej. clientes de red)."""
        if self.account_info:
            await self.account_info.__aexit__(None, None, None)
            self.logger.info("Recursos de AccountInfo liberados en ValidationEngine")

    async def validate_trade(
        self, 
        trader_wallet: str, 
        token_address: str, 
        amount_sol: float,
        side: str
    ) -> Tuple[bool, List[ValidationCheck]]:
        """
        Valida un trade antes de ejecutar
        
        Args:
            trader_wallet: Wallet del trader
            token_address: Dirección del token
            amount_sol: Monto en SOL
            side: 'buy' o 'sell'
            
        Returns:
            Tuple de (puede_ejecutar, lista_de_checks)
        """
        # Reset diario si es necesario
        self._check_daily_reset()

        # Si las validaciones están deshabilitadas, aprobar todo con un warning
        if not self.config.validations_enabled:
            check = ValidationCheck(name="ValidationsDisabled")
            check.warning("Validaciones deshabilitadas, trade aprobado sin verificación.")
            self._record_check(check)
            return True, [check]

        # Ejecutar todas las validaciones
        checks = [
            await self.check_sol_balance(),
            self.check_position_size(amount_sol, trader_wallet),
            self.check_daily_volume(trader_wallet, amount_sol),
            self.check_trade_timing(token_address)
        ]

        if side == "sell":
            token_balance_check = await self.check_token_balance(token_address)
            checks.append(token_balance_check)

        # Registrar estadísticas de todas las validaciones
        for check in checks:
            self._record_check(check)

        # Determinar resultado final
        can_execute = all(check.is_ok(strict_mode=self.config.strict_mode) for check in checks)

        return can_execute, checks

    async def check_sol_balance(self) -> ValidationCheck:
        """Verifica que el balance de SOL sea suficiente."""
        check = ValidationCheck(name="SolBalanceCheck")
        if not self.account_info or not self.keypair:
            check.fail("Motor de validación no inicializado correctamente para check de SOL.")
            return check

        try:
            balance = await self.account_info.get_sol_balance(str(self.keypair.pubkey()))
            required_sol = self.config.min_sol_balance

            if balance >= required_sol:
                check.passthrough(f"Balance suficiente: {balance:.6f} SOL", {'balance': balance, 'required': required_sol})
            else:
                check.fail(f"Balance insuficiente: {balance:.6f} SOL < {required_sol:.6f} SOL requeridos", {'balance': balance, 'required': required_sol})

        except Exception as e:
            self.logger.error(f"Error verificando balance de SOL: {e}", exc_info=True)
            check.fail("Error al verificar balance de SOL", {'error': str(e)})

        return check

    async def check_token_balance(self, token_address: str) -> ValidationCheck:
        """Verifica que se posee el token que se intenta vender."""
        check = ValidationCheck(name="TokenBalanceCheck")
        if not self.account_info or not self.keypair:
            check.fail("Motor de validación no inicializado correctamente para check de token.")
            return check

        try:
            owner_address = str(self.keypair.pubkey())
            balance = await self.account_info.get_token_balance(
                mint_address=token_address,
                owner_address=owner_address
            )

            if balance > 0:
                check.passthrough(f"Se posee el token a vender ({balance} tokens)", {'balance': balance})
            else:
                check.fail("No se posee el token que se intenta vender", {'balance': 0})

        except Exception as e:
            self.logger.error(f"Error verificando balance de token {token_address}: {e}", exc_info=True)
            check.fail("Error al verificar balance del token", {'error': str(e)})

        return check

    def check_position_size(self, amount_sol: float, trader_wallet: str) -> ValidationCheck:
        """Verifica que el tamaño de la posición no exceda el máximo."""
        check = ValidationCheck(name="PositionSizeCheck")
        trader_config = self.config.get_trader_config(trader_wallet)
        max_position = trader_config.max_position_size if trader_config.max_position_size is not None else self.config.max_position_size

        if amount_sol <= max_position:
            details = {'amount': amount_sol, 'max_allowed': max_position}
            check.passthrough(f"Tamaño de posición válido: {amount_sol:.6f} SOL", details)
        else:
            details = {'amount': amount_sol, 'max_allowed': max_position, 'excess': amount_sol - max_position}
            check.fail(f"Posición demasiado grande: {amount_sol:.6f} SOL > {max_position:.6f} SOL máximo", details)

        return check

    def check_daily_volume(self, trader_wallet: str, amount_sol: float) -> ValidationCheck:
        """Verifica que el volumen diario del trader no exceda el máximo."""
        check = ValidationCheck(name="DailyVolumeCheck")
        current_volume = self.daily_volume.get(trader_wallet, 0.0)
        new_volume = current_volume + amount_sol

        trader_config = self.config.get_trader_config(trader_wallet)
        daily_limit = trader_config.daily_limit if trader_config.daily_limit is not None else self.config.max_daily_volume

        if new_volume <= daily_limit:
            details = {'new_volume': new_volume, 'limit': daily_limit}
            check.passthrough(f"Volumen diario dentro del límite: {new_volume:.6f}/{daily_limit:.6f} SOL", details)
        else:
            details = {'new_volume': new_volume, 'limit': daily_limit, 'excess': new_volume - daily_limit}
            check.fail(f"Excede límite de volumen diario: {new_volume:.6f} SOL > {daily_limit:.6f} SOL", details)

        return check

    def check_trade_timing(self, token_address: str) -> ValidationCheck:
        """Verifica que no se compre y venda el mismo token demasiado rápido."""
        check = ValidationCheck(name="TradeTimingCheck")
        last_trade = self.last_trade_time.get(token_address)

        if not last_trade:
            check.passthrough("Primer trade para este token.", {'token': token_address})
            return check

        time_diff = (datetime.now() - last_trade).total_seconds()
        min_interval = self.config.min_trade_interval_seconds

        if time_diff >= min_interval:
            details = {'token': token_address, 'time_since_last': time_diff, 'min_interval': min_interval}
            check.passthrough(f"Tiempo desde último trade del token: {time_diff:.1f}s", details)
        else:
            details = {'token': token_address, 'time_since_last': time_diff, 'min_interval': min_interval}
            # En copy trading, es normal copiar trades rápidos, así que solo warning
            check.warning(f"Trade rápido para el mismo token: {time_diff:.1f}s < {min_interval}s", details)

        return check

    def record_trade_execution(self, trader_wallet: str, token_address: str, amount_sol: float):
        """Registra la ejecución de un trade para validaciones futuras."""
        self._check_daily_reset()

        # Actualizar volumen diario
        self.daily_volume[trader_wallet] = self.daily_volume.get(trader_wallet, 0.0) + amount_sol

        # Actualizar conteo de trades
        self.daily_trades[trader_wallet] = self.daily_trades.get(trader_wallet, 0) + 1

        # Actualizar último trade para este token específico
        self.last_trade_time[token_address] = datetime.now()

    def _check_daily_reset(self):
        """Verifica si es un nuevo día para resetear contadores diarios."""
        current_date = datetime.now().date()
        if current_date > self.last_reset:
            self.daily_volume.clear()
            self.daily_trades.clear()
            self.last_reset = current_date
            self.logger.info("✅ Contadores de validación diarios reseteados.")

    def _record_check(self, check: ValidationCheck):
        """Registra las estadísticas de una validación."""
        self.validation_stats['total_checks'] += 1
        if check.result == ValidationResult.PASSED:
            self.validation_stats['passed'] += 1
        elif check.result == ValidationResult.FAILED:
            self.validation_stats['failed'] += 1
        elif check.result == ValidationResult.WARNING:
            self.validation_stats['warnings'] += 1

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene las estadísticas del motor de validaciones."""
        return {
            **self.validation_stats,
            'daily_volume_per_trader': dict(self.daily_volume),
            'daily_trades_per_trader': dict(self.daily_trades),
            'last_reset': self.last_reset.isoformat()
        }

    def reset_stats(self):
        """Resetea las estadísticas de validación."""
        self.validation_stats = {'total_checks': 0, 'passed': 0, 'failed': 0, 'warnings': 0}
        self.logger.info("Estadísticas de validación reseteadas manualmente.")
