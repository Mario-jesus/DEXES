# -*- coding: utf-8 -*-
"""
Motor de validaciones para trades
"""
from enum import Enum
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from solders.keypair import Keypair
from decimal import Decimal, getcontext
from asyncio import TaskGroup, CancelledError
import asyncio

from logging_system import AppLogger

from .config import CopyTradingConfig
from .data_management.token_trader_manager import TokenTraderManager
from .balance_management import BalanceManager

getcontext().prec = 26

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
                    token_trader_manager: Optional[TokenTraderManager] = None,
                    balance_manager: Optional[BalanceManager] = None):
        """
        Inicializa el motor de validaciones
        
        Args:
            config: Configuración del sistema
            logger: Logger para registrar eventos
            token_trader_manager: Manager para obtener datos de tokens y traders
        """
        self.config = config
        self._logger = AppLogger(self.__class__.__name__)
        self.token_trader_manager = token_trader_manager
        self.balance_manager = balance_manager

        # Estado para validaciones
        self.daily_volume: Dict[str, float] = {}  # {trader: volume}
        self.daily_trades: Dict[str, int] = {}    # {trader: count}
        self.last_trade_time: Dict[str, datetime] = {} # {trader_token: time}

        self.validation_stats: Dict[str, Any] = {
            'total_checks': 0,
            'passed': 0,
            'failed': 0,
            'warnings': 0,
            'concurrent_validations': 0,
            'total_validation_time': 0.0,
            'avg_validation_time': 0.0,
            'cancelled_validations': 0
        }

        # Reset diario
        self.last_reset = datetime.now().date()

        self._logger.debug("ValidationEngine inicializado")

    async def validate_trade(
        self, 
        trader_wallet: str, 
        token_address: str, 
        amount_sol: str,
        amount_tokens: str,
        side: str
    ) -> Tuple[bool, List[ValidationCheck]]:
        """
        Valida un trade antes de ejecutar usando validaciones concurrentes con cancelación inteligente
        
        Args:
            trader_wallet: Wallet del trader
            token_address: Dirección del token
            amount_sol: Monto en SOL
            amount_tokens: Monto en tokens
            side: 'buy' o 'sell'
            
        Returns:
            Tuple de (puede_ejecutar, lista_de_checks)
        """
        # Reset diario si es necesario
        self._check_daily_reset()

        # Verificar si las validaciones están deshabilitadas
        if not self.config.validations_enabled:
            return self._handle_disabled_validations()

        # Ejecutar validaciones con cancelación inteligente
        self._logger.info(f"Iniciando validaciones concurrentes para trade {side} de {amount_sol} SOL en {token_address}")
        start_time = datetime.now()

        try:
            # Ejecutar validaciones concurrentes
            checks, failed_checks, cancelled_tasks = await self._execute_concurrent_validations(
                trader_wallet, token_address, amount_sol, amount_tokens, side
            )

            # Procesar resultados y estadísticas
            validation_duration = (datetime.now() - start_time).total_seconds()
            self._log_validation_results(validation_duration, failed_checks, cancelled_tasks)
            self._update_performance_stats(validation_duration)

            # Registrar estadísticas de todas las validaciones
            for check in checks:
                self._record_check(check)

            # Determinar resultado final
            can_execute = all(check.is_ok(strict_mode=self.config.strict_mode) for check in checks)

            if can_execute:
                self._logger.info(f"Validaciones completadas exitosamente para trade {side} de {amount_sol} SOL")
            else:
                self._logger.info(f"Validaciones fallaron para trade {side} de {amount_sol} SOL")

            return can_execute, checks
        except Exception as e:
            self._logger.error(f"Error en validaciones para trade {side} de {amount_sol} SOL: {e}")
            return False, []

    def _handle_disabled_validations(self) -> Tuple[bool, List[ValidationCheck]]:
        """Maneja el caso cuando las validaciones están deshabilitadas."""
        check = ValidationCheck(name="ValidationsDisabled")
        check.warning("Validaciones deshabilitadas, trade aprobado sin verificación.")
        self._record_check(check)
        return True, [check]

    async def _execute_concurrent_validations(
        self,
        trader_wallet: str,
        token_address: str,
        amount_sol: str,
        amount_tokens: str,
        side: str
    ) -> Tuple[List[ValidationCheck], List[ValidationCheck], List[str]]:
        """
        Ejecuta las validaciones de forma concurrente con cancelación inteligente.
        
        Returns:
            Tuple de (checks_completados, checks_fallidos, tareas_canceladas)
        """
        checks: List[ValidationCheck] = []
        failed_checks: List[ValidationCheck] = []
        cancelled_tasks: List[str] = []

        try:
            async with TaskGroup() as tg:
                # Crear tareas para todas las validaciones
                tasks = self._create_validation_tasks(tg, trader_wallet, token_address, amount_sol, amount_tokens, side)

                # Monitorear y procesar resultados
                checks, failed_checks, cancelled_tasks = await self._monitor_validation_tasks(tasks)

        except Exception as e:
            self._logger.error(f"Error general en validaciones: {e}")
            # Crear un check de fallo general
            general_failure = ValidationCheck(name="GeneralValidationError")
            general_failure.fail(f"Error general en validaciones: {str(e)}", {'error': str(e)})
            checks.append(general_failure)
            failed_checks.append(general_failure)

        return checks, failed_checks, cancelled_tasks

    def _create_validation_tasks(
        self, 
        tg: TaskGroup,
        trader_wallet: str,
        token_address: str,
        amount_sol: str,
        amount_tokens: str,
        side: str
    ) -> Dict[str, asyncio.Task[ValidationCheck]]:
        """Crea las tareas de validación para ejecutar concurrentemente."""
        tasks = {
            'sol_balance': tg.create_task(self.check_sol_balance(amount_sol)),
            'position_size': tg.create_task(self.check_position_size(amount_sol, trader_wallet)),
            'trade_timing': tg.create_task(self.check_trade_timing(trader_wallet, token_address)),
            'max_traders': tg.create_task(self.check_max_traders_per_token(trader_wallet, token_address)),
            'max_amount': tg.create_task(self.check_max_amount_to_invest_per_trader(trader_wallet, amount_sol, side)),
            'max_tokens': tg.create_task(self.check_max_open_tokens_per_trader(trader_wallet, token_address, side)),
            'max_positions': tg.create_task(self.check_max_open_positions_per_token_per_trader(trader_wallet, token_address, side)),
            'max_daily_volume': tg.create_task(self.check_max_daily_volume_sol_open(trader_wallet, amount_sol, side)),
            'budget_availability': tg.create_task(self.check_budget_availability(amount_sol))
        }

        # Agregar validación de token balance solo para ventas
        if side == "sell":
            tasks['token_balance'] = tg.create_task(self.check_token_balance(token_address, amount_tokens))

        return tasks

    async def _monitor_validation_tasks(
        self, 
        tasks: Dict[str, asyncio.Task[ValidationCheck]]
    ) -> Tuple[List[ValidationCheck], List[ValidationCheck], List[str]]:
        """
        Monitorea las tareas de validación y maneja la cancelación inteligente.
        
        Returns:
            Tuple de (checks_completados, checks_fallidos, tareas_canceladas)
        """
        checks: List[ValidationCheck] = []
        failed_checks: List[ValidationCheck] = []
        cancelled_tasks: List[str] = []
        completed_tasks = set()

        while len(completed_tasks) < len(tasks):
            for task_name, task in tasks.items():
                if task_name in completed_tasks:
                    continue

                if task.done():
                    check, is_failed = await self._process_completed_task(task_name, task)
                    checks.append(check)
                    completed_tasks.add(task_name)

                    if is_failed:
                        failed_checks.append(check)

                        # Verificar si es un fallo crítico y cancelar tareas no críticas
                        if self._is_critical_failure(check.name):
                            cancelled_tasks.extend(
                                await self._cancel_non_critical_tasks(tasks, completed_tasks)
                            )

            # Pequeña pausa para evitar polling agresivo
            await asyncio.sleep(0.01)

        return checks, failed_checks, cancelled_tasks

    async def check_budget_availability(self, amount_sol: str) -> ValidationCheck:
        """Valida que el presupuesto efectivo (global/distribuido) permita el trade."""
        check = ValidationCheck(name="BudgetAvailabilityCheck")

        if not self.balance_manager:
            check.passthrough("BalanceManager no disponible; sin verificación de presupuesto efectivo")
            return check

        try:
            available_str, is_enough = await self.balance_manager.get_effective_available_sol_for_trade(amount_sol)
            details = {
                'requested': amount_sol,
                'effective_available': available_str
            }
            if is_enough:
                check.passthrough("Presupuesto efectivo suficiente para el trade", details)
            else:
                check.fail("Presupuesto efectivo insuficiente para el trade", details)
        except Exception as e:
            self._logger.error(f"Error verificando presupuesto efectivo: {e}")
            check.fail("Error verificando presupuesto efectivo", {'error': str(e)})

        return check

    async def _process_completed_task(
        self, 
        task_name: str, 
        task: asyncio.Task[ValidationCheck]
    ) -> Tuple[ValidationCheck, bool]:
        """
        Procesa una tarea completada y retorna el check resultante.
        
        Returns:
            Tuple de (check, es_fallo)
        """
        try:
            check = task.result()
            return check, check.result == ValidationResult.FAILED

        except CancelledError:
            # Crear un check para tareas canceladas
            cancelled_check = ValidationCheck(name=f"{task_name}_cancelled")
            cancelled_check.warning(f"Validación {task_name} cancelada debido a fallo crítico en otra validación")
            self.validation_stats['cancelled_validations'] += 1
            return cancelled_check, False

        except Exception as e:
            # Crear un check de fallo para tareas que fallaron con excepción
            failed_check = ValidationCheck(name=f"{task_name}_error")
            failed_check.fail(f"Error en validación {task_name}: {str(e)}", {'error': str(e)})
            self._logger.error(f"Error en validación {task_name}: {e}")
            return failed_check, True

    async def _cancel_non_critical_tasks(
        self, 
        tasks: Dict[str, asyncio.Task[ValidationCheck]], 
        completed_tasks: set
    ) -> List[str]:
        """
        Cancela las tareas no críticas cuando se detecta un fallo crítico.
        
        Returns:
            Lista de nombres de tareas canceladas
        """
        cancelled_tasks: List[str] = []

        for task_name, task in tasks.items():
            if task_name not in completed_tasks and not self._is_critical_validation(task_name):
                task.cancel()
                cancelled_tasks.append(task_name)
                self._logger.debug(f"Cancelando validación no crítica: {task_name}")

        return cancelled_tasks

    def _log_validation_results(
        self, 
        validation_duration: float, 
        failed_checks: List[ValidationCheck], 
        cancelled_tasks: List[str]
    ):
        """Registra los resultados de las validaciones."""
        # Determinar si hay fallos críticos
        has_critical_failures = any(self._is_critical_failure(check.name) for check in failed_checks)

        if has_critical_failures:
            self._logger.info(f"Validaciones completadas con fallos críticos en {validation_duration:.3f}s")
            if cancelled_tasks:
                self._logger.debug(f"Validaciones canceladas: {', '.join(cancelled_tasks)}")
        else:
            self._logger.info(f"Validaciones concurrentes completadas en {validation_duration:.3f}s")

    def _update_performance_stats(self, validation_duration: float):
        """Actualiza las estadísticas de rendimiento."""
        self.validation_stats['concurrent_validations'] += 1
        self.validation_stats['total_validation_time'] += validation_duration
        self.validation_stats['avg_validation_time'] = (
            self.validation_stats['total_validation_time'] / 
            self.validation_stats['concurrent_validations']
        )

    async def check_sol_balance(self, amount_sol: str) -> ValidationCheck:
        """Verifica que el balance de SOL sea suficiente."""
        check = ValidationCheck(name="SolBalanceCheck")

        # Verificar integración de balances
        if not self.balance_manager:
            check.fail("BalanceManager no disponible para verificación de SOL")
            return check

        try:
            # Obtener balance actual
            balance = await self.balance_manager.get_sol_balance()
            balance_dec = Decimal(balance)
            amount_sol_dec = Decimal(amount_sol)

            if balance_dec >= amount_sol_dec:
                details = {
                    'balance': format(balance_dec, "f"),
                    'required': amount_sol,
                    'excess': format(balance_dec - amount_sol_dec, "f")
                }
                check.passthrough(f"Balance suficiente: {format(balance_dec, 'f')} SOL", details)
            else:
                details = {
                    'balance': format(balance_dec, "f"),
                    'required': amount_sol,
                    'deficit': format(amount_sol_dec - balance_dec, "f")
                }
                check.fail(f"Balance insuficiente: {format(balance_dec, 'f')} SOL < {amount_sol} SOL requeridos", details)

        except Exception as e:
            self._logger.error(f"Error verificando balance de SOL: {e}")
            check.fail("Error al verificar balance de SOL", {'error': str(e)})

        return check

    async def check_token_balance(self, token_address: str, amount_tokens: str) -> ValidationCheck:
        """Verifica que se posee el token que se intenta vender."""
        check = ValidationCheck(name="TokenBalanceCheck")

        # Verificar integración de balances
        if not self.balance_manager:
            check.fail("BalanceManager no disponible para verificación de token")
            return check

        try:
            # Obtener balance del token
            balance = await self.balance_manager.get_token_balance([token_address])
            balance_dec = Decimal(balance.get(token_address, "0.0"))
            amount_tokens_dec = Decimal(amount_tokens)

            if balance_dec >= amount_tokens_dec:
                details = {
                    'token_address': token_address,
                    'balance': format(balance_dec, "f"),
                    'amount_tokens': amount_tokens,
                    'excess': format(balance_dec - amount_tokens_dec, "f")
                }
                check.passthrough(f"Se posee el token a vender ({balance} tokens)", details)
            else:
                details = {
                    'token_address': token_address,
                    'balance': format(balance_dec, "f"),
                    'amount_tokens': amount_tokens,
                    'deficit': format(amount_tokens_dec - balance_dec, "f")
                }
                check.fail("No se posee el token que se intenta vender", details)

        except Exception as e:
            self._logger.error(f"Error verificando balance de token {token_address}: {e}")
            check.fail("Error al verificar balance del token", {'error': str(e), 'token_address': token_address})

        return check

    async def check_position_size(self, amount_sol: str, trader_wallet: str) -> ValidationCheck:
        """Verifica que el tamaño de la posición esté dentro de los límites configurados."""
        check = ValidationCheck(name="PositionSizeCheck")

        # Verificar si las validaciones de posición están configuradas
        if (self._should_skip_validation(trader_wallet, 'min_position_size') and 
            self._should_skip_validation(trader_wallet, 'max_position_size')):
            check.passthrough("Validación de tamaño de posición no configurada")
            return check

        # Verificar si el trader existe
        trader_info = self.config.get_trader_info(trader_wallet)
        if not trader_info:
            check.fail("Trader no encontrado", {'trader_wallet': trader_wallet})
            return check

        try:
            # Obtener configuraciones con prioridad
            min_position = self._get_trader_config_value(trader_wallet, 'min_position_size')
            max_position = self._get_trader_config_value(trader_wallet, 'max_position_size')
            adjust_position_size = self._get_trader_config_value(trader_wallet, 'adjust_position_size', True)

            amount_sol_dec = Decimal(amount_sol)

            # Verificar mínimo
            if min_position is not None:
                min_position_dec = Decimal(min_position)
                if amount_sol_dec < min_position_dec:
                    if adjust_position_size:
                        details = {
                            'trader_wallet': trader_wallet,
                            'amount': amount_sol,
                            'min_required': min_position,
                            'adjusted': True,
                            'adjustment': format(min_position_dec - amount_sol_dec, "f")
                        }
                        check.warning(f"Posición será ajustada al mínimo: {amount_sol} SOL -> {min_position} SOL", details)
                    else:
                        details = {
                            'trader_wallet': trader_wallet,
                            'amount': amount_sol,
                            'min_required': min_position,
                            'deficit': format(min_position_dec - amount_sol_dec, "f")
                        }
                        check.fail(f"Posición demasiado pequeña: {amount_sol} SOL < {min_position} SOL mínimo", details)
                        return check

            # Verificar máximo
            if max_position is not None:
                max_position_dec = Decimal(max_position)
                if amount_sol_dec > max_position_dec:
                    if adjust_position_size:
                        details = {
                            'trader_wallet': trader_wallet,
                            'amount': amount_sol,
                            'max_allowed': max_position,
                            'adjusted': True,
                            'adjustment': format(amount_sol_dec - max_position_dec, "f")
                        }
                        check.warning(f"Posición será ajustada al máximo: {amount_sol} SOL -> {max_position} SOL", details)
                    else:
                        details = {
                            'trader_wallet': trader_wallet,
                            'amount': amount_sol,
                            'max_allowed': max_position,
                            'excess': format(amount_sol_dec - max_position_dec, "f")
                        }
                        check.fail(f"Posición demasiado grande: {amount_sol} SOL > {max_position} SOL máximo", details)
                        return check

            # Si llegamos aquí, la posición es válida
            details = {
                'trader_wallet': trader_wallet,
                'amount': amount_sol,
                'min_position': min_position,
                'max_position': max_position,
                'adjust_position_size': adjust_position_size
            }
            check.passthrough(f"Tamaño de posición válido: {amount_sol} SOL", details)

        except Exception as e:
            self._logger.error(f"Error verificando tamaño de posición para {trader_wallet}: {e}")
            check.fail("Error al verificar tamaño de posición", {'error': str(e), 'trader_wallet': trader_wallet})

        return check

    async def check_trade_timing(self, trader_wallet: str, token_address: str) -> ValidationCheck:
        """Verifica que no se hagan trades demasiado rápido para el mismo token."""
        check = ValidationCheck(name="TradeTimingCheck")

        # Verificar si la validación está configurada
        if self._should_skip_validation(trader_wallet, 'min_trade_interval_seconds_per_trader'):
            check.passthrough("Validación de intervalo de trades no configurada")
            return check

        try:
            # Obtener configuración con prioridad
            min_interval = self._get_trader_config_value(trader_wallet, 'min_trade_interval_seconds_per_trader', 1)

            # Usar TokenTraderManager para obtener el último trade real del trader para este token
            last_trade = None
            if self.token_trader_manager:
                trader_token_stats = await self.token_trader_manager.get_trader_token_stats(trader_wallet, token_address)
                if trader_token_stats and trader_token_stats.last_trade_timestamp:
                    # Convertir string a datetime si es necesario
                    if isinstance(trader_token_stats.last_trade_timestamp, str):
                        last_trade = datetime.fromisoformat(trader_token_stats.last_trade_timestamp)
                    else:
                        last_trade = trader_token_stats.last_trade_timestamp
                else:
                    # Si no hay datos persistentes, usar el diccionario en memoria como fallback
                    last_trade = self.last_trade_time.get(token_address)
            else:
                # Fallback al diccionario en memoria si no hay TokenTraderManager
                last_trade = self.last_trade_time.get(token_address)

            if not last_trade:
                details = {
                    'trader_wallet': trader_wallet,
                    'token_address': token_address,
                    'min_interval': min_interval,
                    'is_first_trade': True,
                    'data_source': 'persistent' if self.token_trader_manager else 'memory'
                }
                check.passthrough("Primer trade para este token.", details)
                return check

            # Calcular tiempo transcurrido desde el último trade
            time_diff = (datetime.now() - last_trade).total_seconds()

            if time_diff >= min_interval:
                details = {
                    'trader_wallet': trader_wallet,
                    'token_address': token_address,
                    'time_since_last': time_diff,
                    'min_interval': min_interval,
                    'last_trade_time': last_trade.isoformat(),
                    'data_source': 'persistent' if self.token_trader_manager else 'memory'
                }
                check.passthrough(f"Tiempo desde último trade del token: {time_diff:.1f}s", details)
            else:
                details = {
                    'trader_wallet': trader_wallet,
                    'token_address': token_address,
                    'time_since_last': time_diff,
                    'min_interval': min_interval,
                    'last_trade_time': last_trade.isoformat(),
                    'time_remaining': min_interval - time_diff,
                    'data_source': 'persistent' if self.token_trader_manager else 'memory'
                }
                # En copy trading, es normal copiar trades rápidos, así que solo warning
                check.warning(f"Trade rápido para el mismo token: {time_diff:.1f}s < {min_interval}s", details)

        except Exception as e:
            self._logger.error(f"Error verificando timing de trades para {trader_wallet} en {token_address}: {e}")
            check.fail("Error al verificar timing de trades", {'error': str(e), 'trader_wallet': trader_wallet, 'token_address': token_address})

        return check

    async def check_max_traders_per_token(self, trader_wallet: str, token_address: str) -> ValidationCheck:
        """Verifica que no se exceda el máximo de traders por token."""
        check = ValidationCheck(name="MaxTradersPerTokenCheck")

        # Verificar si la validación está configurada
        if self._should_skip_validation(trader_wallet, 'max_traders_per_token'):
            check.passthrough("Validación de máximo traders por token no configurada")
            return check

        # Verificar si tenemos TokenTraderManager disponible
        if not self.token_trader_manager:
            check.warning("TokenTraderManager no disponible, saltando validación de max_traders_per_token")
            return check

        try:
            # Obtener configuración
            max_traders = self._get_trader_config_value(trader_wallet, 'max_traders_per_token')

            if max_traders is None:
                check.passthrough("Máximo de traders por token no configurado")
                return check

            # Obtener información del token
            token_info = await self.token_trader_manager.get_token_info(token_address)
            current_traders = len(token_info.traders) if token_info else 0

            # Verificar si el trader ya está en el token (no contará como nuevo)
            trader_already_in_token = token_info and trader_wallet in token_info.traders
            effective_traders = current_traders if trader_already_in_token else current_traders + 1

            if effective_traders <= max_traders:
                details = {
                    'token': token_address, 
                    'current_traders': current_traders, 
                    'max_allowed': max_traders,
                    'trader_already_in_token': trader_already_in_token
                }
                check.passthrough(f"Traders en token válido: {effective_traders}/{max_traders}", details)
            else:
                details = {
                    'token': token_address, 
                    'current_traders': current_traders, 
                    'max_allowed': max_traders,
                    'excess': effective_traders - max_traders
                }
                check.fail(f"Demasiados traders en token: {effective_traders} > {max_traders} máximo", details)

        except Exception as e:
            self._logger.error(f"Error verificando max_traders_per_token para {token_address}: {e}")
            check.fail("Error al verificar máximo de traders por token", {'error': str(e)})

        return check

    async def check_max_amount_to_invest_per_trader(self, trader_wallet: str, amount_sol: str, side: str = "buy") -> ValidationCheck:
        """Verifica que no se exceda el máximo de SOL que puede invertir un trader."""
        check = ValidationCheck(name="MaxAmountToInvestPerTraderCheck")

        # Las ventas no requieren esta validación ya que liberan balance en lugar de consumirlo
        if side.lower() == "sell":
            check.passthrough("Validación de máximo inversión omitida para ventas", {
                'trader': trader_wallet,
                'amount': amount_sol,
                'side': side,
                'reason': 'Las ventas liberan balance en lugar de consumirlo'
            })
            return check

        # Verificar si la validación está configurada
        if self._should_skip_validation(trader_wallet, 'max_amount_to_invest_per_trader'):
            check.passthrough("Validación de máximo de inversión por trader no configurada")
            return check

        # Verificar si tenemos TokenTraderManager disponible
        if not self.token_trader_manager:
            check.warning("TokenTraderManager no disponible, saltando validación de max_amount_to_invest")
            return check

        try:
            # Obtener configuración
            max_amount = self._get_trader_config_value(trader_wallet, 'max_amount_to_invest_per_trader')

            if max_amount is None:
                check.passthrough("Máximo de inversión por trader no configurado")
                return check

            # Obtener estadísticas del trader
            trader_stats = await self.token_trader_manager.get_trader_stats(trader_wallet)
            current_invested = Decimal(trader_stats.total_volume_sol_open_active) if trader_stats else Decimal("0")
            new_amount = Decimal(amount_sol)
            total_after_trade = current_invested + new_amount
            max_amount_dec = Decimal(max_amount)

            if total_after_trade <= max_amount_dec:
                details = {
                    'trader': trader_wallet,
                    'current_invested': format(current_invested, "f"),
                    'new_amount': amount_sol,
                    'total_after_trade': format(total_after_trade, "f"),
                    'max_allowed': max_amount,
                    'side': side
                }
                check.passthrough(f"Inversión del trader válida: {total_after_trade:.6f}/{max_amount} SOL", details)
            else:
                details = {
                    'trader': trader_wallet,
                    'current_invested': format(current_invested, "f"),
                    'new_amount': amount_sol,
                    'total_after_trade': format(total_after_trade, "f"),
                    'max_allowed': max_amount,
                    'excess': format(total_after_trade - max_amount_dec, "f"),
                    'side': side
                }
                check.fail(f"Trader excederaía máximo de inversión: {total_after_trade:.6f} > {max_amount} SOL", details)

        except Exception as e:
            self._logger.error(f"Error verificando max_amount_to_invest para {trader_wallet}: {e}")
            check.fail("Error al verificar máximo de inversión por trader", {'error': str(e)})

        return check

    async def check_max_open_tokens_per_trader(self, trader_wallet: str, token_address: Optional[str] = None, side: str = "buy") -> ValidationCheck:
        """Verifica que no se exceda el máximo de tokens abiertos por trader."""
        check = ValidationCheck(name="MaxOpenTokensPerTraderCheck")

        # Las ventas no requieren esta validación ya que no abren nuevas posiciones
        if side.lower() == "sell":
            check.passthrough("Validación de máximo tokens por trader omitida para ventas", {
                'trader': trader_wallet,
                'side': side,
                'reason': 'Las ventas no abren nuevas posiciones'
            })
            return check

        # Verificar si la validación está configurada
        if self._should_skip_validation(trader_wallet, 'max_open_tokens_per_trader'):
            check.passthrough("Validación de máximo tokens por trader no configurada")
            return check

        # Verificar si tenemos TokenTraderManager disponible
        if not self.token_trader_manager:
            check.warning("TokenTraderManager no disponible, saltando validación de max_open_tokens")
            return check

        try:
            # Obtener configuración
            max_tokens = self._get_trader_config_value(trader_wallet, 'max_open_tokens_per_trader')

            if max_tokens is None:
                check.passthrough("Máximo de tokens por trader no configurado")
                return check

            # Obtener tokens del trader
            trader_tokens = await self.token_trader_manager.get_tokens_by_trader(trader_wallet)
            current_tokens = len(trader_tokens)

            # Contar solo tokens con posiciones activas
            active_tokens = 0
            target_token_has_active_positions = False

            for token_addr in trader_tokens:
                trader_token_stats = await self.token_trader_manager.get_trader_token_stats(trader_wallet, token_addr)
                if trader_token_stats and trader_token_stats.open_positions_active > 0:
                    active_tokens += 1
                    # Verificar si el token objetivo ya tiene posiciones activas
                    if token_address and token_addr == token_address:
                        target_token_has_active_positions = True

            # Si el trader ya tiene posiciones activas en el token objetivo, no cuenta como nuevo token
            # Si no tiene posiciones activas en el token objetivo, se contará como nuevo token activo
            effective_active_tokens = active_tokens
            if token_address and not target_token_has_active_positions:
                # El trader no tiene posiciones activas en este token, se contará como nuevo
                effective_active_tokens = active_tokens + 1

            if effective_active_tokens <= max_tokens:
                details = {
                    'trader': trader_wallet,
                    'active_tokens': active_tokens,
                    'effective_active_tokens': effective_active_tokens,
                    'max_allowed': max_tokens,
                    'target_token': token_address,
                    'target_token_has_active_positions': target_token_has_active_positions,
                    'side': side
                }
                check.passthrough(f"Tokens activos del trader válidos: {effective_active_tokens}/{max_tokens}", details)
            else:
                details = {
                    'trader': trader_wallet,
                    'active_tokens': active_tokens,
                    'effective_active_tokens': effective_active_tokens,
                    'max_allowed': max_tokens,
                    'target_token': token_address,
                    'target_token_has_active_positions': target_token_has_active_positions,
                    'excess': effective_active_tokens - max_tokens,
                    'side': side
                }
                check.fail(f"Trader tiene demasiados tokens activos: {effective_active_tokens} >= {max_tokens} máximo", details)

        except Exception as e:
            self._logger.error(f"Error verificando max_open_tokens para {trader_wallet}: {e}")
            check.fail("Error al verificar máximo de tokens por trader", {'error': str(e)})

        return check

    async def check_max_open_positions_per_token_per_trader(self, trader_wallet: str, token_address: str, side: str = "buy") -> ValidationCheck:
        """Verifica que no se exceda el máximo de posiciones por token por trader."""
        check = ValidationCheck(name="MaxOpenPositionsPerTokenPerTraderCheck")

        # Las ventas no requieren esta validación ya que no abren nuevas posiciones
        if side.lower() == "sell":
            check.passthrough("Validación de máximo posiciones por token omitida para ventas", {
                'trader': trader_wallet,
                'token': token_address,
                'side': side,
                'reason': 'Las ventas no abren nuevas posiciones'
            })
            return check

        # Verificar si la validación está configurada
        if self._should_skip_validation(trader_wallet, 'max_open_positions_per_token_per_trader'):
            check.passthrough("Validación de máximo posiciones por token no configurada")
            return check

        # Verificar si tenemos TokenTraderManager disponible
        if not self.token_trader_manager:
            check.warning("TokenTraderManager no disponible, saltando validación de max_open_positions")
            return check

        try:
            # Obtener configuración
            max_positions = self._get_trader_config_value(trader_wallet, 'max_open_positions_per_token_per_trader')

            if max_positions is None:
                check.passthrough("Máximo de posiciones por token no configurado")
                return check

            # Obtener estadísticas del trader para este token
            trader_token_stats = await self.token_trader_manager.get_trader_token_stats(trader_wallet, token_address)
            current_positions = trader_token_stats.open_positions_active if trader_token_stats else 0

            # La nueva posición incrementará el contador
            total_after_trade = current_positions + 1

            if total_after_trade <= max_positions:
                details = {
                    'trader': trader_wallet,
                    'token': token_address,
                    'current_positions': current_positions,
                    'total_after_trade': total_after_trade,
                    'max_allowed': max_positions,
                    'side': side
                }
                check.passthrough(f"Posiciones del trader en token válidas: {total_after_trade}/{max_positions}", details)
            else:
                details = {
                    'trader': trader_wallet,
                    'token': token_address,
                    'current_positions': current_positions,
                    'total_after_trade': total_after_trade,
                    'max_allowed': max_positions,
                    'excess': total_after_trade - max_positions,
                    'side': side
                }
                check.fail(f"Trader excederaía máximo de posiciones en token: {total_after_trade} > {max_positions}", details)

        except Exception as e:
            self._logger.error(f"Error verificando max_open_positions para {trader_wallet} en {token_address}: {e}")
            check.fail("Error al verificar máximo de posiciones por token", {'error': str(e)})

        return check

    async def check_max_daily_volume_sol_open(self, trader_wallet: str, amount_sol: str, side: str = "buy") -> ValidationCheck:
        """Verifica que no se exceda el máximo volumen diario de SOL en posiciones abiertas."""
        check = ValidationCheck(name="MaxDailyVolumeSolOpenCheck")

        # Las ventas no requieren esta validación ya que no abren nuevas posiciones
        if side.lower() == "sell":
            check.passthrough("Validación de máximo volumen diario omitida para ventas", {
                'trader': trader_wallet,
                'amount': amount_sol,
                'side': side,
                'reason': 'Las ventas no abren nuevas posiciones'
            })
            return check

        # Verificar si la validación está configurada
        if self._should_skip_validation(trader_wallet, 'max_daily_volume_sol_open'):
            check.passthrough("Validación de máximo volumen diario no configurada")
            return check

        try:
            # Obtener configuración
            max_daily_volume = self._get_trader_config_value(trader_wallet, 'max_daily_volume_sol_open')

            if max_daily_volume is None:
                check.passthrough("Máximo volumen diario no configurado")
                return check

            # Obtener volumen diario actual del trader (desde nuestro tracking interno)
            current_daily_volume = self.daily_volume.get(trader_wallet, 0.0)
            new_amount = float(amount_sol)
            total_after_trade = current_daily_volume + new_amount
            max_daily_volume_float = float(max_daily_volume)

            if total_after_trade <= max_daily_volume_float:
                details = {
                    'trader': trader_wallet,
                    'current_daily_volume': current_daily_volume,
                    'new_amount': new_amount,
                    'total_after_trade': total_after_trade,
                    'max_allowed': max_daily_volume_float,
                    'side': side
                }
                check.passthrough(f"Volumen diario del trader válido: {total_after_trade:.6f}/{max_daily_volume} SOL", details)
            else:
                details = {
                    'trader': trader_wallet,
                    'current_daily_volume': current_daily_volume,
                    'new_amount': new_amount,
                    'total_after_trade': total_after_trade,
                    'max_allowed': max_daily_volume_float,
                    'excess': total_after_trade - max_daily_volume_float,
                    'side': side
                }
                check.fail(f"Trader excederaía máximo volumen diario: {total_after_trade:.6f} > {max_daily_volume} SOL", details)

        except Exception as e:
            self._logger.error(f"Error verificando max_daily_volume_sol_open para {trader_wallet}: {e}")
            check.fail("Error al verificar máximo volumen diario", {'error': str(e)})

        return check

    def _get_trader_config_value(self, trader_wallet: str, attr_name: str, global_default: Any = None) -> Any:
        """
        Obtiene un valor de configuración con prioridad trader > global > default.
        
        Args:
            trader_wallet: Wallet del trader
            attr_name: Nombre del atributo de configuración
            global_default: Valor por defecto si no se encuentra configuración
            
        Returns:
            Valor de configuración con prioridad
        """
        # Obtener información del trader
        trader_info = self.config.get_trader_info(trader_wallet)
        if not trader_info:
            # Si no hay trader_info, usar configuración global directamente
            return getattr(self.config, attr_name, global_default)

        # Obtener configuración específica del trader
        trader_config = self.config.get_trader_config(trader_info)
        if trader_config:
            # Mapeo de nombres de atributos entre TraderConfig y CopyTradingConfig
            trader_attr_map = {
                'max_amount_to_invest_per_trader': 'max_amount_to_invest',
                'max_open_tokens_per_trader': 'max_open_tokens',
                'max_open_positions_per_token_per_trader': 'max_open_positions_per_token',
                'use_balanced_allocation_per_trader': 'use_balanced_allocation',
                'min_position_size': 'min_position_size',
                'max_position_size': 'max_position_size',
                'adjust_position_size': 'adjust_position_size',
                'max_daily_volume_sol_open': 'max_daily_volume_sol_open',
                'min_trade_interval_seconds_per_trader': 'min_trade_interval_seconds'
            }

            # Obtener el nombre del atributo en TraderConfig
            trader_attr = trader_attr_map.get(attr_name, attr_name)

            # Obtener valor del trader
            trader_value = getattr(trader_config, trader_attr, None)
            if trader_value is not None:
                return trader_value

        # Fallback a configuración global
        global_value = getattr(self.config, attr_name, global_default)
        return global_value if global_value is not None else global_default

    def _should_skip_validation(self, trader_wallet: str, attr_name: str) -> bool:
        """
        Determina si una validación debe saltarse porque no está configurada.
        
        Args:
            trader_wallet: Wallet del trader
            attr_name: Nombre del atributo de configuración
            
        Returns:
            True si la validación debe saltarse (pasar como válida)
        """
        trader_value = None
        global_value = None

        # Obtener información del trader
        trader_info = self.config.get_trader_info(trader_wallet)
        if trader_info:
            trader_config = self.config.get_trader_config(trader_info)
            if trader_config:
                # Mapeo de nombres de atributos
                trader_attr_map = {
                    'max_amount_to_invest_per_trader': 'max_amount_to_invest',
                    'max_open_tokens_per_trader': 'max_open_tokens',
                    'max_open_positions_per_token_per_trader': 'max_open_positions_per_token',
                    'use_balanced_allocation_per_trader': 'use_balanced_allocation',
                    'min_position_size': 'min_position_size',
                    'max_position_size': 'max_position_size',
                    'adjust_position_size': 'adjust_position_size',
                    'max_daily_volume_sol_open': 'max_daily_volume_sol_open',
                    'min_trade_interval_seconds_per_trader': 'min_trade_interval_seconds'
                }

                trader_attr = trader_attr_map.get(attr_name, attr_name)
                trader_value = getattr(trader_config, trader_attr, None)

        # Obtener valor global
        global_value = getattr(self.config, attr_name, None)

        # Si ambos son None, saltear la validación
        return trader_value is None and global_value is None

    def _is_critical_failure(self, validation_name: str) -> bool:
        """
        Determina si un fallo en una validación es crítico y debería cancelar otras validaciones.
        
        Args:
            validation_name: Nombre de la validación
            
        Returns:
            True si el fallo es crítico
        """
        critical_validations = {
            'SolBalanceCheck',           # Sin SOL no se puede hacer nada
            'TokenBalanceCheck',         # Sin tokens no se puede vender
            'PositionSizeCheck'          # Tamaño de posición inválido es crítico
        }
        return validation_name in critical_validations

    def _is_critical_validation(self, validation_name: str) -> bool:
        """
        Determina si una validación es crítica y no debe ser cancelada.
        
        Args:
            validation_name: Nombre de la validación
            
        Returns:
            True si la validación es crítica
        """
        critical_validations = {
            'SolBalanceCheck',
            'TokenBalanceCheck', 
            'PositionSizeCheck'
        }
        return validation_name in critical_validations

    def record_trade_execution(self, trader_wallet: str, token_address: str, amount_sol: float):
        """Registra la ejecución de un trade para validaciones futuras."""
        try:
            self._check_daily_reset()

            # Actualizar volumen diario
            self.daily_volume[trader_wallet] = self.daily_volume.get(trader_wallet, 0.0) + amount_sol

            # Actualizar conteo de trades
            self.daily_trades[trader_wallet] = self.daily_trades.get(trader_wallet, 0) + 1

            # Actualizar último trade para este token específico
            self.last_trade_time[token_address] = datetime.now()

            self._logger.debug(f"Trade ejecutado registrado: {trader_wallet} - {amount_sol} SOL en {token_address}")
        except Exception as e:
            self._logger.error(f"Error registrando ejecución de trade: {e}")

    def _check_daily_reset(self):
        """Verifica si es un nuevo día para resetear contadores diarios."""
        current_date = datetime.now().date()
        if current_date > self.last_reset:
            self.daily_volume.clear()
            self.daily_trades.clear()
            self.last_reset = current_date
            self._logger.info("Contadores de validación diarios reseteados")

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

    def get_performance_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas detalladas de rendimiento de validaciones concurrentes."""
        stats = self.get_stats()
        performance_stats = {
            'concurrent_validations_executed': stats.get('concurrent_validations', 0),
            'total_validation_time_seconds': round(stats.get('total_validation_time', 0.0), 3),
            'average_validation_time_seconds': round(stats.get('avg_validation_time', 0.0), 3),
            'total_checks_performed': stats.get('total_checks', 0),
            'cancelled_validations': stats.get('cancelled_validations', 0),
            'success_rate_percent': 0.0,
            'performance_improvement': "N/A",
            'cancellation_efficiency': "N/A"
        }

        # Calcular tasa de éxito
        total_checks = stats.get('total_checks', 0)
        passed_checks = stats.get('passed', 0)
        if total_checks > 0:
            performance_stats['success_rate_percent'] = round((passed_checks / total_checks) * 100, 2)

        # Calcular mejora de rendimiento (estimación)
        concurrent_validations = stats.get('concurrent_validations', 0)
        avg_time = stats.get('avg_validation_time', 0.0)
        if concurrent_validations > 0 and avg_time > 0:
            # Estimación: validaciones secuenciales tomarían ~8 veces más tiempo
            estimated_sequential_time = avg_time * 8
            time_saved = estimated_sequential_time - avg_time
            performance_stats['performance_improvement'] = f"~{time_saved:.3f}s por validación"

        # Calcular eficiencia de cancelación
        cancelled_validations = stats.get('cancelled_validations', 0)
        if concurrent_validations > 0 and cancelled_validations > 0:
            cancellation_rate = (cancelled_validations / concurrent_validations) * 100
            performance_stats['cancellation_efficiency'] = f"{cancellation_rate:.1f}% de validaciones canceladas"

        return performance_stats

    def reset_stats(self):
        """Resetea las estadísticas de validación."""
        self.validation_stats = {
            'total_checks': 0, 
            'passed': 0, 
            'failed': 0, 
            'warnings': 0,
            'concurrent_validations': 0,
            'total_validation_time': 0.0,
            'avg_validation_time': 0.0,
            'cancelled_validations': 0
        }
        self._logger.info("Estadísticas de validación reseteadas manualmente.")
