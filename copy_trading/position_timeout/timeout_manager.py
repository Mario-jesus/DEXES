# -*- coding: utf-8 -*-
"""
Manager de timeout de posiciones para Copy Trading.
Cierra automáticamente posiciones que han permanecido abiertas más tiempo del configurado.
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from decimal import Decimal, getcontext

from logging_system import AppLogger
from ..config import CopyTradingConfig
from ..position_management.models import (
    OpenPosition,
    ClosePosition,
    PositionTraderTradeData,
    TraderTradeData,
    ClosePositionStatus
)
from ..position_management.queues import OpenPositionQueue
from ..position_management.managers import PositionQueueManager
from ..position_management.services import PositionCalculationService
from ..events import PositionEventBus, PositionCloseRequestedEvent

if TYPE_CHECKING:
    from ..transactions_management.protocols import TransactionExecutorProtocol

getcontext().prec = 26


class PositionTimeoutManager:
    """
    Manager que cierra automáticamente posiciones abiertas que exceden el tiempo máximo configurado.
    Similar a Liquidations pero basado en tiempo en lugar de balance.
    """

    def __init__(
        self,
        config: CopyTradingConfig,
        position_queue_manager: PositionQueueManager,
        transaction_executor: 'TransactionExecutorProtocol',
        position_event_bus: PositionEventBus,
        system_wallet_address: str
    ):
        """
        Inicializa el manager de timeout de posiciones.
        
        Args:
            config: Configuración del sistema
            position_queue_manager: Manager de colas de posiciones
            transaction_executor: Ejecutor de transacciones
            position_event_bus: Bus de eventos de posiciones
            system_wallet_address: Dirección de la wallet del sistema
        """
        self.config = config
        self.position_queue_manager = position_queue_manager
        self.transaction_executor = transaction_executor
        self.position_event_bus = position_event_bus
        self.system_wallet_address = system_wallet_address
        self._logger = AppLogger(self.__class__.__name__)
        self.position_calculation_service = PositionCalculationService()

        # Estado
        self._is_running = False
        self._check_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Estadísticas
        self.stats = {
            'total_checks': 0,
            'positions_timeout_closed': 0,
            'positions_skipped': 0,
            'last_check_time': None,
            'last_closed_position_id': None
        }

        self._logger.debug("PositionTimeoutManager inicializado")

    async def start(self) -> None:
        """Inicia el manager de timeout de posiciones."""
        if self._is_running:
            self._logger.warning("PositionTimeoutManager ya está corriendo")
            return

        if not self.config.position_timeout_enabled:
            self._logger.debug("Timeout de posiciones deshabilitado en configuración")
            return

        if not self.config.max_position_age_seconds:
            self._logger.warning("Timeout de posiciones habilitado pero max_position_age_seconds no configurado")
            return

        self._is_running = True
        self._logger.info(
            f"Iniciando PositionTimeoutManager - "
            f"Timeout: {self.config.max_position_age_seconds}s, "
            f"Intervalo de verificación: {self.config.position_timeout_check_interval}s"
        )

        # Iniciar task de verificación periódica
        self._check_task = asyncio.create_task(self._timeout_check_loop())
        self._logger.debug("Task de verificación de timeout iniciado")

    async def stop(self) -> None:
        """Detiene el manager de timeout de posiciones."""
        if not self._is_running:
            return

        self._logger.info("Deteniendo PositionTimeoutManager")
        self._is_running = False

        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                self._logger.debug("Task de verificación de timeout cancelado")
            except Exception as e:
                self._logger.error(f"Error cancelando task de timeout: {e}")
            finally:
                self._check_task = None

        self._logger.debug("PositionTimeoutManager detenido")

    async def _timeout_check_loop(self) -> None:
        """
        Loop principal que verifica periódicamente las posiciones abiertas
        y cierra las que exceden el timeout.
        """
        self._logger.debug("Iniciando loop de verificación de timeout")

        while self._is_running:
            try:
                await self._check_and_close_timeout_positions()

                # Esperar el intervalo configurado antes de la siguiente verificación
                await asyncio.sleep(self.config.position_timeout_check_interval)

            except asyncio.CancelledError:
                self._logger.debug("Loop de verificación de timeout cancelado")
                break
            except Exception as e:
                self._logger.error(f"Error en loop de verificación de timeout: {e}", exc_info=True)
                # Esperar un poco antes de reintentar para no saturar con errores
                await asyncio.sleep(5)

    async def _check_and_close_timeout_positions(self) -> None:
        """
        Verifica todas las posiciones abiertas y cierra las que exceden el timeout.
        """
        if not self.position_queue_manager.open_queue:
            self._logger.warning("OpenPositionQueue no disponible para verificación de timeout")
            return

        try:
            async with self._lock:
                self.stats['total_checks'] += 1
                self.stats['last_check_time'] = datetime.now()

                # Obtener todas las posiciones abiertas
                all_positions = self.position_queue_manager.open_queue.get_open_positions()

                if not all_positions:
                    self._logger.debug("No hay posiciones abiertas para verificar")
                    return

                self._logger.debug(f"Verificando {len(all_positions)} posiciones abiertas para timeout")

                # Calcular el tiempo límite
                if not self.config.max_position_age_seconds:
                    self._logger.warning("max_position_age_seconds no configurado, saltando verificación")
                    return

                max_age = timedelta(seconds=self.config.max_position_age_seconds)
                now = datetime.now()
                timeout_positions: List[OpenPosition] = []

                # Identificar posiciones que exceden el timeout
                for position in all_positions:
                    if position.is_fully_closed():
                        continue

                    age = now - position.created_at
                    if age >= max_age:
                        timeout_positions.append(position)
                        self._logger.info(
                            f"Posición {position.id} excede timeout - "
                            f"Edad: {age.total_seconds():.0f}s, "
                            f"Límite: {self.config.max_position_age_seconds}s"
                        )

                if not timeout_positions:
                    self._logger.debug("No se encontraron posiciones que excedan el timeout")
                    return

                # Ordenar por antigüedad (más antiguas primero)
                timeout_positions.sort(key=lambda p: p.created_at)

                self._logger.info(
                    f"Encontradas {len(timeout_positions)} posiciones que exceden timeout. "
                    f"Iniciando cierre..."
                )

                # Cerrar cada posición que excede el timeout
                closed_count = 0
                skipped_count = 0

                for position in timeout_positions:
                    try:
                        success = await self._close_timeout_position(position)
                        if success:
                            closed_count += 1
                            self.stats['positions_timeout_closed'] += 1
                            self.stats['last_closed_position_id'] = position.id
                        else:
                            skipped_count += 1
                            self.stats['positions_skipped'] += 1

                        # Pequeña pausa entre cierres para no saturar
                        await asyncio.sleep(0.5)

                    except Exception as e:
                        self._logger.error(
                            f"Error cerrando posición por timeout {position.id}: {e}",
                            exc_info=True
                        )
                        skipped_count += 1
                        self.stats['positions_skipped'] += 1

                self._logger.info(
                    f"Proceso de timeout completado - "
                    f"Cerradas: {closed_count}, Omitidas: {skipped_count}"
                )

        except Exception as e:
            self._logger.error(f"Error en verificación de timeout: {e}", exc_info=True)

    async def _close_timeout_position(self, position: OpenPosition) -> bool:
        """
        Cierra una posición que ha excedido el timeout.
        
        Args:
            position: Posición abierta a cerrar
            
        Returns:
            True si el cierre fue exitoso, False en caso contrario
        """
        try:
            self._logger.info(
                f"Cerrando posición por timeout: {position.id} - "
                f"Token: {position.token_address[:8]}..., "
                f"Trader: {position.trader_wallet[:8]}..., "
                f"Tokens: {position.amount_tokens_executed}"
            )

            # Verificar que la posición tenga trader_trade_data
            if not position.trader_trade_data:
                self._logger.error(
                    f"Posición {position.id} no tiene trader_trade_data, "
                    f"no se puede cerrar por timeout"
                )
                return False

            # Calcular el monto de tokens restantes a cerrar
            remaining_amounts = self.position_calculation_service.calculate_remaining_amounts(
                position, exact=True
            )
            remaining_tokens = remaining_amounts[1]  # amount_tokens

            if Decimal(remaining_tokens) <= 0:
                self._logger.warning(
                    f"Posición {position.id} no tiene tokens restantes para cerrar"
                )
                return False

            # Crear TraderTradeData para el cierre por timeout
            trader_trade_data = TraderTradeData(
                trader_wallet=position.trader_wallet,
                side="sell",
                token_address=position.token_address,
                amount_sol="",  # Se calculará durante la ejecución
                signature="",  # Se asignará después de la ejecución
                token_amount=remaining_tokens,
                new_token_balance="",
                pool="auto",
                bonding_curve_key=position.trader_trade_data.bonding_curve_key if position.trader_trade_data else "",
                v_tokens_in_bonding_curve=position.trader_trade_data.v_tokens_in_bonding_curve if position.trader_trade_data else "",
                v_sol_in_bonding_curve=position.trader_trade_data.v_sol_in_bonding_curve if position.trader_trade_data else "",
                market_cap_sol=position.trader_trade_data.market_cap_sol if position.trader_trade_data else "",
                timestamp=datetime.now()
            )

            # Crear PositionTraderTradeData para el cierre
            position_trader_trade_data = PositionTraderTradeData(
                trader_trade_data=trader_trade_data,
                copy_amount_tokens=remaining_tokens,
                denominate_in_sol=False,
                is_liquidation=True
            )

            # Marcar como timeout en metadata
            position_trader_trade_data.add_metadata("timeout_closed", True)
            position_trader_trade_data.add_metadata("timeout_age_seconds", 
                str(int((datetime.now() - position.created_at).total_seconds())))

            # Emitir evento de solicitud de cierre
            if self.position_event_bus:
                timeout_age = int((datetime.now() - position.created_at).total_seconds())
                self.position_event_bus.emit_position_close_requested(
                    PositionCloseRequestedEvent(
                        position_id=str(uuid.uuid4()),  # Nuevo ID para el cierre
                        token_address=position.token_address,
                        trader_wallet=position.trader_wallet,
                        reason=f"timeout ({timeout_age}s)"
                    )
                )

            # Ejecutar el trade de cierre
            self._logger.debug(
                f"Ejecutando trade de cierre por timeout para posición {position.id}"
            )
            success, signature, error_message = await self.transaction_executor.execute_trade(
                position_trader_trade_data
            )

            if success and signature:
                self._logger.info(
                    f"Trade de cierre por timeout ejecutado exitosamente: {signature} "
                    f"para posición {position.id}"
                )

                # Procesar la posición ejecutada usando el sistema existente
                await self.position_queue_manager.process_executed_position(
                    position_trade_data=position_trader_trade_data,
                    signature=signature
                )

                return True
            else:
                error_msg = error_message or 'Error desconocido'
                self._logger.error(
                    f"Error ejecutando trade de cierre por timeout para posición {position.id}: {error_msg}"
                )
                return False

        except Exception as e:
            self._logger.error(
                f"Error cerrando posición por timeout {position.id}: {e}",
                exc_info=True
            )
            return False

    async def get_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas del manager de timeout.
        
        Returns:
            Diccionario con estadísticas
        """
        return {
            'enabled': self.config.position_timeout_enabled,
            'max_position_age_seconds': self.config.max_position_age_seconds,
            'check_interval_seconds': self.config.position_timeout_check_interval,
            'is_running': self._is_running,
            'stats': self.stats.copy()
        }

    async def run_once(self) -> Dict[str, Any]:
        """
        Ejecuta una verificación única de timeout (útil para testing o ejecución manual).
        
        Returns:
            Diccionario con resultados de la verificación
        """
        if not self.config.position_timeout_enabled:
            return {
                'success': False,
                'message': 'Timeout de posiciones deshabilitado'
            }

        try:
            await self._check_and_close_timeout_positions()
            return {
                'success': True,
                'stats': self.stats.copy()
            }
        except Exception as e:
            self._logger.error(f"Error en ejecución única de timeout: {e}")
            return {
                'success': False,
                'error': str(e)
            }
