# -*- coding: utf-8 -*-
"""
DrawdownManager - Gestor de drawdown para Copy Trading

Responsabilidades:
- Monitorear el capital actual vs peak histórico
- Calcular drawdown actual y máximo
- Actualizar peak cuando el balance supera el máximo histórico
- Emitir eventos cuando se alcancen umbrales
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple, TYPE_CHECKING, Callable, Awaitable, Set, Any
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, getcontext

from logging_system import AppLogger
from ..config import CopyTradingConfig
from ..balance_management import BalanceManager
from ..events import (
    PositionEventBus,
    DrawdownThresholdExceededEvent,
    DrawdownRecoveredEvent,
    DrawdownPeakUpdatedEvent
)

if TYPE_CHECKING:
    from ..notifications import NotificationManager
    SystemStopCallback = Callable[[], Awaitable[None]]

getcontext().prec = 26


@dataclass
class DrawdownMetrics:
    """Métricas de drawdown"""
    peak_capital_sol: Decimal = Decimal("0.0")
    current_capital_sol: Decimal = Decimal("0.0")
    drawdown_sol: Decimal = Decimal("0.0")
    drawdown_percent: Decimal = Decimal("0.0")
    max_drawdown_sol: Decimal = Decimal("0.0")
    max_drawdown_percent: Decimal = Decimal("0.0")
    peak_timestamp: Optional[datetime] = None
    last_update: datetime = field(default_factory=datetime.now)


class DrawdownManager:
    """
    Gestor de drawdown que monitorea el capital y calcula métricas de riesgo.
    """

    def __init__(
        self,
        config: CopyTradingConfig,
        balance_manager: BalanceManager,
        position_event_bus: PositionEventBus,
        system_stop_callback: Optional["SystemStopCallback"] = None,
        notification_manager: Optional["NotificationManager"] = None
    ):
        """
        Inicializa el DrawdownManager.
        
        Args:
            config: Configuración del sistema
            balance_manager: Gestor de balances
            position_event_bus: Bus de eventos para notificaciones
            system_stop_callback: Callback para detener el sistema completamente
            notification_manager: Gestor de notificaciones (Telegram, consola, etc.)
        """
        self.config = config
        self.balance_manager = balance_manager
        self.position_event_bus = position_event_bus
        self.system_stop_callback = system_stop_callback
        self.notification_manager = notification_manager
        self._logger = AppLogger(self.__class__.__name__)

        # Estado de drawdown
        self.metrics = DrawdownMetrics()

        # Lock para operaciones concurrentes
        self._lock = asyncio.Lock()

        # Flag de estado
        self._is_running = False
        self._monitoring_task: Optional[asyncio.Task] = None

        # Estado de umbrales
        self._threshold_exceeded = False
        self._recovery_threshold_met = False
        self._stop_trading_activated = False  # Flag para stop_trading activado
        self._system_stop_requested = False  # Flag para evitar múltiples llamadas a stop()

        # Set para tareas en background
        self._background_tasks: Set[Any] = set()

        self._logger.debug("DrawdownManager inicializado")

    async def start(self, initial_balance_sol: str) -> None:
        """
        Inicia el monitoreo de drawdown.
        
        Args:
            initial_balance_sol: Balance inicial en SOL como string
        """
        async with self._lock:
            if self._is_running:
                self._logger.warning("DrawdownManager ya está ejecutándose")
                return

            initial_balance = Decimal(initial_balance_sol or "0.0")

            # Inicializar peak con el balance inicial
            self.metrics.peak_capital_sol = initial_balance
            self.metrics.current_capital_sol = initial_balance
            self.metrics.peak_timestamp = datetime.now()
            self.metrics.last_update = datetime.now()

            self._is_running = True

            # Iniciar tarea de monitoreo si está habilitado
            if self.config.drawdown_enabled:
                self._monitoring_task = asyncio.create_task(self._monitoring_loop())
                self._logger.info(f"DrawdownManager iniciado con balance inicial: {initial_balance_sol} SOL")

    async def stop(self) -> None:
        """Detiene el monitoreo de drawdown."""
        async with self._lock:
            if not self._is_running:
                return

            self._is_running = False

            if self._monitoring_task:
                self._monitoring_task.cancel()
                try:
                    await self._monitoring_task
                except asyncio.CancelledError:
                    pass
                self._monitoring_task = None

            self._logger.info("DrawdownManager detenido")

    async def _monitoring_loop(self) -> None:
        """Loop de monitoreo que verifica el drawdown periódicamente."""
        while self._is_running:
            try:
                await self.update_drawdown()
                await asyncio.sleep(self.config.drawdown_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error en loop de monitoreo de drawdown: {e}", exc_info=True)
                await asyncio.sleep(self.config.drawdown_check_interval)

    async def update_drawdown(self, force_onchain: bool = False) -> DrawdownMetrics:
        """
        Actualiza las métricas de drawdown basándose en el balance actual.
        
        Args:
            force_onchain: Si True, fuerza lectura on-chain del balance
            
        Returns:
            DrawdownMetrics actualizadas
        """
        async with self._lock:
            try:
                # Obtener balance actual
                current_balance_str = await self.balance_manager.get_sol_balance(force_onchain=force_onchain)
                current_balance = Decimal(current_balance_str or "0.0")

                # Actualizar capital actual
                self.metrics.current_capital_sol = current_balance

                # Si el balance actual supera el peak, actualizar peak
                if current_balance > self.metrics.peak_capital_sol:
                    old_peak = self.metrics.peak_capital_sol
                    self.metrics.peak_capital_sol = current_balance
                    self.metrics.peak_timestamp = datetime.now()

                    self._logger.info(
                        f"Peak actualizado: {old_peak} SOL -> {current_balance} SOL "
                        f"(drawdown máximo: {self.metrics.max_drawdown_percent:.2f}%)"
                    )

                    # Emitir evento de peak actualizado
                    self.position_event_bus.emit_drawdown_peak_updated(
                        DrawdownPeakUpdatedEvent(
                            old_peak_sol=format(old_peak, "f"),
                            new_peak_sol=format(current_balance, "f"),
                            current_capital_sol=format(current_balance, "f")
                        )
                    )

                # Calcular drawdown actual
                if self.metrics.peak_capital_sol > 0:
                    drawdown_sol = self.metrics.peak_capital_sol - current_balance
                    drawdown_percent = (drawdown_sol / self.metrics.peak_capital_sol) * Decimal("100.0")

                    self.metrics.drawdown_sol = drawdown_sol
                    self.metrics.drawdown_percent = drawdown_percent

                    # Actualizar drawdown máximo si es mayor
                    if drawdown_sol > self.metrics.max_drawdown_sol:
                        self.metrics.max_drawdown_sol = drawdown_sol
                        self.metrics.max_drawdown_percent = drawdown_percent
                        self._logger.warning(
                            f"Nuevo drawdown máximo: {drawdown_percent:.2f}% ({drawdown_sol:.6f} SOL)"
                        )
                else:
                    self.metrics.drawdown_sol = Decimal("0.0")
                    self.metrics.drawdown_percent = Decimal("0.0")

                self.metrics.last_update = datetime.now()

                # Verificar umbrales y emitir eventos
                await self._check_thresholds()

                return self.metrics

            except Exception as e:
                self._logger.error(f"Error actualizando drawdown: {e}", exc_info=True)
                return self.metrics

    async def _check_thresholds(self) -> None:
        """Verifica si se han alcanzado umbrales de drawdown y emite eventos."""
        if not self.config.drawdown_enabled:
            return

        # Verificar si se excedió el umbral
        threshold_exceeded = False
        threshold_type = None

        if self.config.max_drawdown_percent:
            max_dd_percent = Decimal(self.config.max_drawdown_percent)
            if self.metrics.drawdown_percent >= max_dd_percent:
                threshold_exceeded = True
                threshold_type = "percent"

        if self.config.max_drawdown_sol:
            max_dd_sol = Decimal(self.config.max_drawdown_sol)
            if self.metrics.drawdown_sol >= max_dd_sol:
                threshold_exceeded = True
                threshold_type = "sol"

        # Emitir evento si se excedió el umbral por primera vez
        if threshold_exceeded and not self._threshold_exceeded:
            self._threshold_exceeded = True
            self._logger.warning(
                f"Umbral de drawdown excedido: {self.metrics.drawdown_percent:.2f}% "
                f"({self.metrics.drawdown_sol:.6f} SOL) - Acción: {self.config.drawdown_action}"
            )

            # Emitir evento
            self.position_event_bus.emit_drawdown_threshold_exceeded(
                DrawdownThresholdExceededEvent(
                    drawdown_percent=format(self.metrics.drawdown_percent, "f"),
                    drawdown_sol=format(self.metrics.drawdown_sol, "f"),
                    peak_capital_sol=format(self.metrics.peak_capital_sol, "f"),
                    current_capital_sol=format(self.metrics.current_capital_sol, "f"),
                    threshold_type=threshold_type or "both",
                    action=self.config.drawdown_action
                )
            )

            # Ejecutar acción según drawdown_action
            await self._execute_drawdown_action()

        # Verificar recuperación
        if self._threshold_exceeded and not threshold_exceeded:
            # Verificar si se cumplió el umbral de recuperación
            recovery_met = True
            if self.config.drawdown_recovery_threshold_percent:
                recovery_threshold = Decimal(self.config.drawdown_recovery_threshold_percent)
                if self.metrics.drawdown_percent > recovery_threshold:
                    recovery_met = False

            if recovery_met:
                self._threshold_exceeded = False
                self._recovery_threshold_met = True

                self._logger.info(
                    f"Drawdown recuperado: {self.metrics.drawdown_percent:.2f}% "
                    f"({self.metrics.drawdown_sol:.6f} SOL)"
                )

                # Emitir evento de recuperación
                self.position_event_bus.emit_drawdown_recovered(
                    DrawdownRecoveredEvent(
                        drawdown_percent=format(self.metrics.drawdown_percent, "f"),
                        drawdown_sol=format(self.metrics.drawdown_sol, "f"),
                        peak_capital_sol=format(self.metrics.peak_capital_sol, "f"),
                        current_capital_sol=format(self.metrics.current_capital_sol, "f")
                    )
                )

    async def _execute_drawdown_action(self) -> None:
        """
        Ejecuta la acción configurada cuando se excede el umbral de drawdown.
        """
        action = self.config.drawdown_action

        if action == "notify_only":
            # Solo notificar, no hacer nada más
            self._logger.info("Drawdown excedido - Modo: notify_only - Continuando operaciones")
            await self._notify_drawdown_warning(
                "🟡 <b>Drawdown Alert (Notify Only)</b>",
                level="warning",
                action_description="🔔 Notification only: the system will continue operating normally."
            )
            return

        if action == "block_buys":
            # Solo bloquear BUYs, SELLs permitidos
            self._logger.warning("Drawdown excedido - Modo: block_buys - Bloqueando nuevos BUYs")
            await self._notify_drawdown_warning(
                "🟠 <b>Drawdown Alert (Block Buys)</b>",
                level="warning",
                action_description="🚫 New BUY orders blocked. 🟢 Sells allowed to recover balance."
            )
            return

        if action == "stop_trading":
            # Detener trading completamente
            self._stop_trading_activated = True
            self._logger.error("Drawdown excedido - Modo: stop_trading - Deteniendo sistema completamente")
            await self._notify_drawdown_warning(
                "🔴 <b>Critical Drawdown (Stop Trading)</b>",
                level="error",
                action_description="🛑 System is in the process of a full shutdown. The core module will execute the appropriate shutdown procedure."
            )

            # Delegar la detención completa del sistema al core
            if not self._system_stop_requested:
                self._system_stop_requested = True
                if self.system_stop_callback:
                    self._logger.error("Deteniendo sistema completamente por drawdown excedido")
                    try:
                        # Ejecutar stop en background para no bloquear el loop de monitoreo
                        stop_system_future = asyncio.create_task(self._stop_system())
                        self._background_tasks.add(stop_system_future)
                        stop_system_future.add_done_callback(self._background_tasks.discard)
                    except Exception as e:
                        self._logger.error(f"Error deteniendo sistema: {e}", exc_info=True)
                else:
                    self._logger.error("system_stop_callback no disponible, no se puede detener el sistema")
            else:
                self._logger.debug("Sistema ya está en proceso de detención por drawdown")

    async def _notify_drawdown_warning(self, title: str, level: str = "warning", action_description: str = "") -> None:
        """
        Envía una notificación del sistema sobre el drawdown actual.
        """
        if not self.notification_manager:
            self._logger.debug("NotificationManager no disponible, no se envía notificación de drawdown")
            return

        threshold_lines = []
        if self.config.max_drawdown_percent:
            threshold_lines.append(f"🎯 <b>Máx %:</b> {self.config.max_drawdown_percent}%")
        if self.config.max_drawdown_sol:
            threshold_lines.append(f"🎯 <b>Máx SOL:</b> {self.config.max_drawdown_sol}")
        threshold_section = "\n".join(threshold_lines) if threshold_lines else "🎯 <b>Sin umbrales configurados</b>"

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        message = (
            f"{title}\n\n"
            f"📉 <b>Drawdown Summary</b>\n"
            f"{'─'*12}\n"
            f"📊 <b>Drawdown:</b> {self.metrics.drawdown_percent:.2f}%\n"
            f"💸 <b>Loss:</b> {self.metrics.drawdown_sol:.6f} SOL\n"
            f"📈 <b>Peak:</b> {self.metrics.peak_capital_sol:.6f} SOL\n"
            f"💼 <b>Current Capital:</b> {self.metrics.current_capital_sol:.6f} SOL\n\n"
            f"⚙️ <b>System Action</b>\n"
            f"{'─'*12}\n"
            f"{action_description or 'No action specified.'}\n\n"
            f"🎯 <b>Configured Thresholds</b>\n"
            f"{'─'*12}\n"
            f"{threshold_section}\n\n"
            f"⏰ <b>Time:</b> {current_time}"
        )

        try:
            await self.notification_manager.notify_system(message, level)
        except Exception as e:
            self._logger.error(f"Error enviando notificación de drawdown: {e}")

    async def _stop_system(self) -> None:
        """
        Detiene el sistema completamente.
        """
        try:
            if not self.system_stop_callback:
                self._logger.error("system_stop_callback no disponible")
                return

            self._logger.error("Deteniendo sistema Copy Trading por drawdown excedido...")
            await self.system_stop_callback()
            self._logger.error("Sistema detenido completamente")
        except Exception as e:
            self._logger.error(f"Error deteniendo sistema: {e}", exc_info=True)

    async def get_drawdown_metrics(self) -> DrawdownMetrics:
        """
        Obtiene las métricas actuales de drawdown.
        
        Returns:
            DrawdownMetrics actuales
        """
        async with self._lock:
            return self.metrics

    async def check_drawdown_allows_trade(self, side: str) -> Tuple[bool, str]:
        """
        Verifica si el drawdown permite ejecutar un trade.
        
        Args:
            side: 'buy' o 'sell'
            
        Returns:
            Tuple de (is_allowed, reason)
        """
        if not self.config.drawdown_enabled:
            return True, "Drawdown deshabilitado"

        # Actualizar drawdown antes de verificar
        await self.update_drawdown()

        # Si stop_trading está activado, bloquear todos los trades
        if self._stop_trading_activated:
            return False, f"Trading detenido por drawdown excedido ({self.metrics.drawdown_percent:.2f}%)"

        # Los SELLs siempre están permitidos (ayudan a recuperar) excepto si stop_trading está activo
        if side.lower() == "sell":
            return True, "SELLs siempre permitidos para recuperación"

        # Verificar si se excedió el umbral
        threshold_exceeded = False

        if self.config.max_drawdown_percent:
            max_dd_percent = Decimal(self.config.max_drawdown_percent)
            if self.metrics.drawdown_percent >= max_dd_percent:
                threshold_exceeded = True

        if self.config.max_drawdown_sol:
            max_dd_sol = Decimal(self.config.max_drawdown_sol)
            if self.metrics.drawdown_sol >= max_dd_sol:
                threshold_exceeded = True

        if not threshold_exceeded:
            return True, "Drawdown dentro de límites"

        # Si se excedió el umbral, verificar la acción configurada
        action = self.config.drawdown_action

        if action == "notify_only":
            return True, "Drawdown excedido pero solo notificación - trades permitidos"

        if action == "block_buys":
            # block_buys solo bloquea BUYs, SELLs permitidos
            if side.lower() == "buy":
                return False, f"Drawdown excedido ({self.metrics.drawdown_percent:.2f}%), BUYs bloqueados"
            return True, "SELLs permitidos para recuperación"

        if action == "stop_trading":
            # stop_trading bloquea todos los trades (ya manejado arriba con _stop_trading_activated)
            return False, f"Drawdown excedido ({self.metrics.drawdown_percent:.2f}%), trading detenido"

        return True, "Acción de drawdown no reconocida"

    def is_threshold_exceeded(self) -> bool:
        """Retorna True si el umbral de drawdown está excedido."""
        return self._threshold_exceeded
