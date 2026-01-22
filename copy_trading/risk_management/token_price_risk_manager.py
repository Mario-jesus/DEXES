# -*- coding: utf-8 -*-
"""
TokenPriceRiskManager - Gestor de Stop Loss (Trailing) y Take Profit basado en eventos de trades

Este módulo reemplaza PositionRiskManager usando datos en tiempo real de subscribeTokenTrade.
Recibe trades a través de un callback, los añade a una cola asíncrona y procesa las posiciones
abiertas para aplicar stop loss y take profit.

Responsabilidades:
- Recibir eventos de trades de tokens activos (con posiciones abiertas)
- Monitorear precios en tiempo real desde los datos de trades
- Implementar trailing stop loss dinámico
- Implementar take profit
- Liquidar automáticamente posiciones que excedan umbrales
"""
from __future__ import annotations

import asyncio
from typing import Optional, Set, Any, Dict, List, Tuple, TYPE_CHECKING
from datetime import datetime
from decimal import Decimal, getcontext
from cachetools import TTLCache

from logging_system import AppLogger
from ..config import CopyTradingConfig
from ..data_management.moralis.price_client import MoralisPriceClient
from ..position_management.models import OpenPosition, PositionTraderTradeData, TraderTradeData
from ..events import PositionEventBus, PositionOpenedEvent, PositionCloseExecutedEvent, PositionAnalysisFinishedEvent

if TYPE_CHECKING:
    from ..position_management.managers.position_queue_manager import PositionQueueManager
    from ..transactions_management.protocols import TransactionExecutorProtocol
    from ..notifications import NotificationManager

# Configurar precisión alta para Decimal (28 dígitos = suficiente para 16+ cifras significativas)
getcontext().prec = 28


class TokenPriceRiskManager:
    """
    Gestor de riesgo que monitorea precios en tiempo real desde eventos de trades
    y liquida posiciones automáticamente con trailing stop loss y take profit.
    
    Diferencias con PositionRiskManager:
    - Usa datos de trades en tiempo real en lugar de polling periódico
    - Procesa eventos a través de una cola asíncrona
    - Se suscribe automáticamente a tokens con posiciones abiertas
    - Actualiza suscripciones dinámicamente cuando hay nuevas posiciones
    """

    def __init__(
        self,
        config: CopyTradingConfig,
        position_queue_manager: "PositionQueueManager",
        transaction_executor: "TransactionExecutorProtocol",
        price_client: MoralisPriceClient,
        position_event_bus: PositionEventBus,
        notification_manager: Optional["NotificationManager"] = None,
        subscription_manager: Optional[Any] = None,  # PumpFunSubscriptions o PumpFunRedisSubscriptions
    ):
        """
        Inicializa el TokenPriceRiskManager.
        
        Args:
            config: Configuración del sistema
            position_queue_manager: Manager de colas de posiciones
            transaction_executor: Ejecutor de transacciones para liquidar
            price_client: Cliente de Moralis solo para obtener precio SOL/USD (para notificaciones)
            position_event_bus: Bus de eventos para notificaciones
            notification_manager: Gestor de notificaciones (opcional)
            subscription_manager: Manager de suscripciones (PumpFunSubscriptions o PumpFunRedisSubscriptions)
        """
        self.config = config
        self.position_queue_manager = position_queue_manager
        self.transaction_executor = transaction_executor
        self.price_client = price_client
        self.position_event_bus = position_event_bus
        self.notification_manager = notification_manager
        self.subscription_manager = subscription_manager
        self._logger = AppLogger(self.__class__.__name__)

        # Lock para operaciones concurrentes
        self._lock = asyncio.Lock()

        # Flag de estado
        self._is_running = False
        self._processing_task: Optional[asyncio.Task[None]] = None

        # Cola asíncrona para recibir eventos de trades
        self._trade_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=1000)

        # Estadísticas
        self.stats: Dict[str, Any] = {
            'trades_received': 0,
            'trades_processed': 0,
            'positions_checked': 0,
            'stop_loss_triggered': 0,
            'take_profit_triggered': 0,
            'errors': 0,
            'last_trade_time': None,
            'peak_prices_updated': 0,
            'positions_discarded': 0,
            'tokens_subscribed': 0,
        }

        # Set para evitar liquidaciones duplicadas
        self._positions_being_liquidated: Set[str] = set()

        # Diccionario de eventos para esperar confirmación de cierre: {position_id: asyncio.Event}
        # Se usa para esperar el evento PositionCloseExecutedEvent antes de descartar de _positions_being_liquidated
        self._position_close_events: Dict[str, asyncio.Event] = {}

        # Diccionario de tareas de limpieza de seguridad: {position_id: asyncio.Task}
        # Para evitar que el garbage collector las limpie y poder cancelarlas específicamente
        self._cleanup_timeout_tasks: Dict[str, asyncio.Task] = {}

        # Semáforo para limitar ejecuciones concurrentes de _check_positions_for_token
        max_concurrent = self.config.risk_management_max_concurrent_check_positions
        self._check_positions_semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent)

        # Set de tareas activas de _check_positions_for_token
        # Usado para rastrear qué tokens están siendo procesados actualmente
        self._active_check_tasks: Set[asyncio.Task] = set()

        # Mapa de tokens suscritos: {token_address: timestamp de última suscripción}
        self._subscribed_tokens: Dict[str, datetime] = {}

        # Mapa de último precio conocido por token: {token_address: (price, timestamp)}
        # Usado para actualizar precios desde los trades recibidos
        self._token_prices: Dict[str, Tuple[Decimal, datetime]] = {}

        # Cache de precio SOL/USD: {'price': Decimal}
        # Solo se usa para notificaciones (conversión a USD)
        # maxsize=1 ya que solo guardamos un valor
        sol_cache_ttl = self.config.risk_management_sol_price_cache_ttl
        self._sol_price_cache: TTLCache[str, Decimal] = TTLCache(
            maxsize=1,
            ttl=sol_cache_ttl
        )

        # Cache de precios de entrada por posición: {position_id: Decimal}
        # El precio de entrada no cambia durante la vida de una posición
        # Usar un cache grande para evitar recalcular
        self._entry_price_cache: Dict[str, Decimal] = {}

        # Cache de thresholds como Decimal (evitar conversiones repetidas)
        self._stop_loss_threshold: Optional[Decimal] = None
        self._take_profit_threshold: Optional[Decimal] = None
        self._update_threshold_cache()

        self._logger.debug("TokenPriceRiskManager inicializado")

    def _update_threshold_cache(self) -> None:
        """Actualiza el cache de thresholds desde configuración."""
        if self.config.stop_loss_enabled and self.config.stop_loss_percentage:
            self._stop_loss_threshold = Decimal(str(self.config.stop_loss_percentage))
        else:
            self._stop_loss_threshold = None

        if self.config.take_profit_enabled and self.config.take_profit_percentage:
            self._take_profit_threshold = Decimal(str(self.config.take_profit_percentage))
        else:
            self._take_profit_threshold = None

    # ==========================================================================
    # MÉTODOS PÚBLICOS
    # ==========================================================================

    async def start(self) -> None:
        """Inicia el monitoreo de riesgo basado en eventos."""
        async with self._lock:
            if self._is_running:
                self._logger.warning("TokenPriceRiskManager ya está ejecutándose")
                return

            # Verificar si está habilitado
            if not self.config.stop_loss_enabled and not self.config.take_profit_enabled:
                self._logger.debug("Stop Loss y Take Profit deshabilitados en configuración")
                return

            # Validar configuración
            if self.config.stop_loss_enabled and not self.config.stop_loss_percentage:
                self._logger.warning("Stop Loss habilitado pero stop_loss_percentage no configurado")
                return

            if self.config.take_profit_enabled and not self.config.take_profit_percentage:
                self._logger.warning("Take Profit habilitado pero take_profit_percentage no configurado")
                return

            # Verificar que tengamos subscription_manager
            if not self.subscription_manager:
                self._logger.warning("TokenPriceRiskManager requiere subscription_manager para funcionar")
                return

            self._is_running = True
            self._processing_task = asyncio.create_task(self._processing_loop())

            # Suscribirse a eventos de posiciones para actualizar suscripciones automáticamente
            self.position_event_bus.on_position_opened(self._on_position_opened)
            self.position_event_bus.on_position_close_executed(self._on_position_close_executed)
            self.position_event_bus.on_position_analysis_finished(self._on_position_analysis_finished)

            # Suscribirse inicialmente a tokens con posiciones abiertas
            await self._update_token_subscriptions()

            stop_loss_info = f"Trailing Stop Loss: {self.config.stop_loss_percentage}%" if self.config.stop_loss_enabled else "Deshabilitado"
            take_profit_info = f"Take Profit: {self.config.take_profit_percentage}%" if self.config.take_profit_enabled else "Deshabilitado"

            self._logger.info(
                f"TokenPriceRiskManager iniciado - {stop_loss_info}, {take_profit_info}, "
                f"Modo: Eventos en tiempo real desde trades"
            )

    async def stop(self) -> None:
        """Detiene el monitoreo de riesgo."""
        async with self._lock:
            if not self._is_running:
                return

            self._is_running = False

            # Cancelar todas las tareas activas de verificación de posiciones
            if self._active_check_tasks:
                self._logger.debug(f"Cancelando {len(self._active_check_tasks)} tareas activas de verificación")
                for task in list(self._active_check_tasks):
                    if not task.done():
                        task.cancel()

                # Esperar a que todas las tareas se cancelen (con timeout)
                if self._active_check_tasks:
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*self._active_check_tasks, return_exceptions=True),
                            timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        self._logger.warning("Timeout esperando cancelación de tareas de verificación")
                    except Exception as e:
                        self._logger.debug(f"Error cancelando tareas: {e}")
                self._active_check_tasks.clear()

            # Cancelar todas las tareas de limpieza de timeout
            if self._cleanup_timeout_tasks:
                self._logger.debug(f"Cancelando {len(self._cleanup_timeout_tasks)} tareas de limpieza de timeout")
                tasks_to_cancel = []
                for _position_id, task in list(self._cleanup_timeout_tasks.items()):
                    if not task.done():
                        task.cancel()
                        tasks_to_cancel.append(task)

                # Esperar a que todas las tareas se cancelen (con timeout)
                if tasks_to_cancel:
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                            timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        self._logger.warning("Timeout esperando cancelación de tareas de limpieza de timeout")
                    except Exception as e:
                        self._logger.debug(f"Error cancelando tareas de limpieza: {e}")
                self._cleanup_timeout_tasks.clear()

            # Cerrar la cola de trades (Python 3.13+)
            # Por defecto, get() solo lanzará QueueShutDown cuando la cola esté vacía
            # permitiendo procesar todos los trades pendientes
            try:
                self._trade_queue.shutdown(immediate=False)
                self._logger.debug("Cola de trades cerrada (procesando trades pendientes)")
            except AttributeError:
                # Fallback para versiones anteriores de Python (no debería ocurrir)
                self._logger.debug("shutdown() no disponible en esta versión de Python")
            except Exception as e:
                self._logger.debug(f"Error cerrando cola de trades: {e}")

            if self._processing_task:
                self._processing_task.cancel()
                try:
                    await self._processing_task
                except asyncio.CancelledError:
                    pass
                self._processing_task = None

            # Desuscribirse de todos los tokens
            await self._unsubscribe_all_tokens()

            self._logger.info("TokenPriceRiskManager detenido")

    async def on_trade_event(self, trade_data: Dict[str, Any]) -> None:
        """
        Callback para recibir eventos de trades desde la suscripción.
        Añade el trade a la cola asíncrona para procesamiento.
        
        Args:
            trade_data: Datos del trade recibido desde subscribeTokenTrade
        """
        try:
            # Verificar que tenga los campos necesarios
            token_address = trade_data.get('mint')
            if not token_address:
                self._logger.debug("Trade recibido sin mint, ignorando")
                return

            # Añadir a la cola (no bloquea si la cola está llena, descarta el trade)
            try:
                self._trade_queue.put_nowait(trade_data)
                self.stats['trades_received'] += 1
                self.stats['last_trade_time'] = datetime.now()
            except asyncio.QueueFull:
                self._logger.warning("Cola de trades llena, descartando trade")
                self.stats['errors'] += 1
            except asyncio.QueueShutDown:
                # Cola cerrada (shutdown fue llamado)
                self._logger.debug("Intentando agregar trade a cola cerrada, ignorando")
                # No incrementar errores ya que es un cierre normal

        except Exception as e:
            self._logger.error(f"Error procesando callback de trade: {e}", exc_info=True)
            self.stats['errors'] += 1

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del manager."""
        return self.stats.copy()

    # ==========================================================================
    # MÉTODOS PRIVADOS - LOOP DE PROCESAMIENTO
    # ==========================================================================

    async def _processing_loop(self) -> None:
        """Loop principal que procesa trades de la cola asíncrona."""
        while self._is_running:
            try:
                # Obtener trade de la cola con timeout para permitir verificación periódica
                try:
                    trade_data = await asyncio.wait_for(
                        self._trade_queue.get(),
                        timeout=30.0  # Verificar estado cada 30 segundos (fallback de seguridad)
                    )
                except asyncio.TimeoutError:
                    # Timeout: actualizar suscripciones periódicamente como fallback
                    # (los eventos PositionOpenedEvent/PositionClosedEvent manejan la mayoría de las actualizaciones en tiempo real)
                    # Este timeout es principalmente una verificación de seguridad en caso de que algún evento no se procese
                    await self._update_token_subscriptions()
                    continue
                except asyncio.QueueShutDown:
                    # Cola cerrada (shutdown fue llamado) y vacía - terminar el loop
                    self._logger.debug("Cola cerrada y vacía, terminando loop de procesamiento")
                    break

                # Procesar el trade
                await self._process_trade(trade_data)
                self.stats['trades_processed'] += 1

            except asyncio.CancelledError:
                self._logger.debug("Loop de procesamiento cancelado")
                break
            except asyncio.QueueShutDown:
                # Cola cerrada y vacía - terminar el loop normalmente
                # (puede ocurrir si se llama shutdown(immediate=True) mientras procesamos)
                self._logger.debug("Cola cerrada y vacía, terminando loop de procesamiento")
                break
            except Exception as e:
                self._logger.error(f"Error en loop de procesamiento: {e}", exc_info=True)
                self.stats['errors'] += 1
                await asyncio.sleep(1)  # Pequeña pausa antes de continuar

    async def _process_trade(self, trade_data: Dict[str, Any]) -> None:
        """
        Procesa un trade individual y verifica posiciones abiertas.
        
        Args:
            trade_data: Datos del trade recibido con estructura según pool:
                - pool='pump': usa vSolInBondingCurve / vTokensInBondingCurve
                - pool='pump-amm': usa solInPool / tokensInPool
                - pool='bonk': usa solInPool / tokensInPool
                - Fallback: usa solAmount / tokenAmount del trade
        """
        try:
            token_address = trade_data.get('mint')
            if not token_address:
                return

            # Calcular precio actual desde el trade según el tipo de pool
            current_price = await self._calculate_price_from_trade(trade_data)

            if current_price and current_price > 0:
                timestamp = datetime.now()

                # Actualizar precio conocido del token
                self._token_prices[token_address] = (current_price, timestamp)

                # Verificar posiciones abiertas para este token (con límite de concurrencia)
                # Crear tarea que usa el semáforo para limitar ejecuciones concurrentes
                task = asyncio.create_task(
                    self._check_positions_for_token_with_semaphore(token_address)
                )
                self._active_check_tasks.add(task)
                # Remover la tarea del set cuando termine
                task.add_done_callback(self._active_check_tasks.discard)

        except Exception as e:
            self._logger.error(f"Error procesando trade: {e}", exc_info=True)
            self.stats['errors'] += 1

    async def _calculate_price_from_trade(self, trade_data: Dict[str, Any]) -> Optional[Decimal]:
        """
        Calcula el precio SOL/token desde los datos del trade según el tipo de pool.
        
        Args:
            trade_data: Datos del trade con campos según pool
            
        Returns:
            Precio en SOL/token o None si no se puede calcular
        """
        try:
            pool = trade_data.get('pool', '').lower()

            # Pool: pump-amm o bonk - usar valores del pool
            if pool == 'pump-amm' or pool == 'bonk':
                sol_in_pool = trade_data.get('solInPool')
                tokens_in_pool = trade_data.get('tokensInPool')

                if sol_in_pool and tokens_in_pool:
                    try:
                        sol_pool = Decimal(str(sol_in_pool))
                        tokens_pool = Decimal(str(tokens_in_pool))

                        if tokens_pool > 0:
                            # Precio = SOL en pool / Tokens en pool
                            price = sol_pool / tokens_pool
                            return price
                    except (ValueError, TypeError, ZeroDivisionError):
                        pass

            # Pool: pump - usar valores del bonding curve
            elif pool == 'pump':
                v_sol = trade_data.get('vSolInBondingCurve')
                v_tokens = trade_data.get('vTokensInBondingCurve')

                if v_sol and v_tokens:
                    try:
                        sol_curve = Decimal(str(v_sol))
                        tokens_curve = Decimal(str(v_tokens))

                        if tokens_curve > 0:
                            # Precio = vSOL / vTokens
                            price = sol_curve / tokens_curve
                            return price
                    except (ValueError, TypeError, ZeroDivisionError):
                        pass

            # Fallback: calcular desde el trade individual (solAmount / tokenAmount)
            # Esto da el precio efectivo del trade, no necesariamente el precio del pool
            sol_amount = trade_data.get('solAmount')
            token_amount = trade_data.get('tokenAmount')

            if sol_amount and token_amount:
                try:
                    sol_trade = Decimal(str(sol_amount))
                    tokens_trade = Decimal(str(token_amount))

                    if tokens_trade > 0:
                        # Precio del trade específico
                        price = sol_trade / tokens_trade
                        return price
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

            return None

        except Exception as e:
            self._logger.debug(f"Error en _calculate_price_from_trade: {e}")
            return None

    # ==========================================================================
    # MÉTODOS PRIVADOS - HANDLERS DE EVENTOS DE POSICIONES
    # ==========================================================================

    async def _on_position_opened(self, event: PositionOpenedEvent) -> None:
        """
        Handler para eventos de posición abierta.
        Suscribe al token si no está suscrito.
        
        Args:
            event: Evento de posición abierta
        """
        try:
            token_address = event.token_address
            if not token_address:
                return

            self._logger.debug(
                f"Evento PositionOpenedEvent recibido para token {token_address[:8]}... "
                f"(posición {event.position_id})"
            )

            # Si el token ya está suscrito, no hacer nada
            if token_address in self._subscribed_tokens:
                return

            # Verificar si hay otras posiciones abiertas para este token
            # (para estar seguros antes de suscribir)
            if not self.position_queue_manager or not self.position_queue_manager.open_queue:
                return

            positions = self.position_queue_manager.open_queue.get_open_positions(
                token_address=token_address
            )

            if positions:
                # Suscribirse solo a este token nuevo
                self._logger.info(
                    f"Suscribiéndose a token {token_address[:8]}... "
                    f"debido a posición abierta (posición {event.position_id})"
                )

                if self.subscription_manager and hasattr(self.subscription_manager, 'subscribe_token_trade'):
                    await self.subscription_manager.subscribe_token_trade(
                        token_addresses=[token_address],
                        callback=self.on_trade_event
                    )
                    self._subscribed_tokens[token_address] = datetime.now()
                    self.stats['tokens_subscribed'] = len(self._subscribed_tokens)
                    self._logger.debug(f"Suscrito exitosamente a token {token_address[:8]}...")
            else:
                self._logger.debug(
                    f"No se encontraron posiciones abiertas para token {token_address[:8]}..., "
                    f"posiblemente fue cerrada antes de procesar el evento"
                )

        except Exception as e:
            self._logger.error(f"Error en handler de PositionOpenedEvent: {e}", exc_info=True)
            self.stats['errors'] += 1

    async def _on_position_close_executed(self, event: PositionCloseExecutedEvent) -> None:
        """
        Handler para eventos de cierre ejecutado.
        Descarta posiciones de _positions_being_liquidated cuando se confirma el cierre.
        
        Args:
            event: Evento de cierre ejecutado con processed_open_position_ids
        """
        try:
            # Verificar cada posición procesada en el evento
            for position_id in event.processed_open_position_ids:
                if position_id in self._positions_being_liquidated:
                    self._logger.debug(
                        f"Confirmando cierre de posición {position_id} desde evento PositionCloseExecutedEvent"
                    )
                    # Remover de set de liquidaciones
                    self._positions_being_liquidated.discard(position_id)

                    # Señalar el evento si existe (para despertar la espera en _liquidate_position)
                    if position_id in self._position_close_events:
                        self._position_close_events[position_id].set()
                        # Limpiar el evento después de señalarlo
                        self._position_close_events.pop(position_id, None)

                    # Cancelar tarea de limpieza de timeout si existe (ya fue procesada por el handler)
                    self._cancel_cleanup_task_for_position(position_id)

            await self._check_and_unsuscribe_token_if_no_positions_left(event.token_address, event.processed_open_position_ids)

        except Exception as e:
            self._logger.error(f"Error en handler de PositionCloseExecutedEvent: {e}", exc_info=True)
            self.stats['errors'] += 1

    async def _on_position_analysis_finished(self, event: PositionAnalysisFinishedEvent) -> None:
        """
        Handler para eventos de análisis finalizado.
        Si el análisis de un cierre falló y la posición está siendo liquidada,
        significa que el cierre no se procesó exitosamente, así que descartamos la posición.
        
        Args:
            event: Evento de análisis finalizado con success y position_id
        """
        try:
            # Solo procesar si es un análisis de cierre (position_type == "close")
            # y el análisis no fue exitoso
            if event.position_type == "close" and not event.success:
                position_id = event.position_id

                # Verificar si la posición está siendo liquidada
                if position_id in self._positions_being_liquidated:
                    self._logger.warning(
                        f"Análisis de cierre fallido para posición {position_id} que está siendo liquidada. "
                        f"Error: {event.error_kind} - {event.error_message}. "
                        f"Descartando de _positions_being_liquidated"
                    )

                    # Remover de set de liquidaciones
                    self._positions_being_liquidated.discard(position_id)

                    # Señalar el evento si existe (para despertar la espera en _liquidate_position)
                    if position_id in self._position_close_events:
                        self._position_close_events[position_id].set()
                        # Limpiar el evento después de señalarlo
                        self._position_close_events.pop(position_id, None)

                    # Cancelar tarea de limpieza de timeout si existe (ya fue procesada por el handler)
                    self._cancel_cleanup_task_for_position(position_id)

        except Exception as e:
            self._logger.error(f"Error en handler de PositionAnalysisFinishedEvent: {e}", exc_info=True)
            self.stats['errors'] += 1

    # ==========================================================================
    # MÉTODOS PRIVADOS - SUSCRIPCIONES DE TOKENS
    # ==========================================================================

    async def _update_token_subscriptions(self) -> None:
        """Actualiza las suscripciones de tokens basado en posiciones abiertas (fallback periódico)."""
        try:
            if not self.position_queue_manager or not self.position_queue_manager.open_queue:
                return

            # Obtener todas las posiciones abiertas
            all_positions = self.position_queue_manager.open_queue.get_open_positions()

            # Extraer tokens únicos con posiciones abiertas
            active_tokens: Set[str] = set()
            for position in all_positions:
                token = position.token_address
                if token:
                    active_tokens.add(token)

            # Suscribirse a nuevos tokens y desuscribirse de tokens sin posiciones
            await self._sync_token_subscriptions(active_tokens)

        except Exception as e:
            self._logger.error(f"Error actualizando suscripciones: {e}", exc_info=True)
            self.stats['errors'] += 1

    async def _sync_token_subscriptions(self, active_tokens: Set[str]) -> None:
        """
        Sincroniza las suscripciones: suscribe tokens nuevos y desuscribe tokens inactivos.
        
        Args:
            active_tokens: Set de tokens que deberían estar suscritos
        """
        if not self.subscription_manager:
            return

        try:
            # Tokens a suscribir (están activos pero no suscritos)
            to_subscribe = active_tokens - set(self._subscribed_tokens.keys())

            # Tokens a desuscribir (están suscritos pero ya no activos)
            to_unsubscribe = set(self._subscribed_tokens.keys()) - active_tokens

            # Suscribirse a nuevos tokens
            if to_subscribe:
                tokens_list = list(to_subscribe)
                self._logger.info(f"Suscribiéndose a {len(tokens_list)} tokens nuevos: {[t[:8] + '...' for t in tokens_list]}")

                if hasattr(self.subscription_manager, 'subscribe_token_trade'):
                    await self.subscription_manager.subscribe_token_trade(
                        token_addresses=tokens_list,
                        callback=self.on_trade_event
                    )
                    for token in tokens_list:
                        self._subscribed_tokens[token] = datetime.now()
                    self.stats['tokens_subscribed'] = len(self._subscribed_tokens)

            # Desuscribirse de tokens inactivos
            if to_unsubscribe:
                tokens_list = list(to_unsubscribe)
                self._logger.info(f"Desuscribiéndose de {len(tokens_list)} tokens inactivos: {[t[:8] + '...' for t in tokens_list]}")

                if hasattr(self.subscription_manager, 'unsubscribe_token_trade'):
                    await self.subscription_manager.unsubscribe_token_trade(tokens_list)
                    for token in tokens_list:
                        self._subscribed_tokens.pop(token, None)

        except Exception as e:
            self._logger.error(f"Error sincronizando suscripciones: {e}", exc_info=True)
            self.stats['errors'] += 1

    async def _check_and_unsuscribe_token_if_no_positions_left(self, token_address: str, processed_open_position_ids: List[str]) -> None:
        """
        Verifica si hay posiciones abiertas para un token y desuscribe si no hay más.
        
        Args:
            token_address: Dirección del token a desuscribir
            processed_open_position_ids: IDs de las posiciones abiertas procesadas
            (Puede estar en los ultimos procesos de liquidacion)
        """
        try:
            # Verificar si todavía hay posiciones abiertas para este token
            if not self.position_queue_manager or not self.position_queue_manager.open_queue:
                return

            positions = self.position_queue_manager.open_queue.get_open_positions(
                token_address=token_address
            )
            positions_without_processed_open_position_ids = list(filter(lambda position: position.id not in processed_open_position_ids, positions))

            # Si no hay más posiciones abiertas, desuscribirse
            if not positions_without_processed_open_position_ids and token_address in self._subscribed_tokens:
                self._logger.info(
                    f"Desuscribiéndose de token {token_address}"
                    f"ya que no hay más posiciones abiertas (posiciones abiertas procesadas: {processed_open_position_ids})"
                )

                if self.subscription_manager and hasattr(self.subscription_manager, 'unsubscribe_token_trade'):
                    await self.subscription_manager.unsubscribe_token_trade([token_address])
                    self._subscribed_tokens.pop(token_address, None)
                    self._logger.debug(f"Desuscrito exitosamente de token {token_address}")
            elif positions_without_processed_open_position_ids:
                self._logger.debug(
                    f"Manteniendo suscripción a token {token_address} "
                    f"({len(positions_without_processed_open_position_ids)} posiciones abiertas restantes excluyendo las posiciones abiertas procesadas)"
                )
            else:
                self._logger.debug(
                    f"Token {token_address} no estaba suscrito, no hay acción necesaria"
                )

        except Exception as e:
            self._logger.error(f"Error desuscribiendo token {token_address}: {e}", exc_info=True)
            self.stats['errors'] += 1

    async def _unsubscribe_all_tokens(self) -> None:
        """Desuscribe todos los tokens activos."""
        if not self.subscription_manager or not self._subscribed_tokens:
            return

        try:
            tokens_list = list(self._subscribed_tokens.keys())
            if tokens_list and hasattr(self.subscription_manager, 'unsubscribe_token_trade'):
                await self.subscription_manager.unsubscribe_token_trade(tokens_list)
                self._subscribed_tokens.clear()
                self._logger.debug(f"Desuscrito de {len(tokens_list)} tokens")
        except Exception as e:
            self._logger.error(f"Error desuscribiendo todos los tokens: {e}", exc_info=True)

    # ==========================================================================
    # MÉTODOS PRIVADOS - VERIFICACIÓN DE POSICIONES
    # ==========================================================================

    async def _check_positions_for_token_with_semaphore(self, token_address: str) -> None:
        """
        Wrapper para _check_positions_for_token que usa semáforo para limitar concurrencia.
        
        Args:
            token_address: Dirección del token a verificar
        """
        # Esperar hasta que haya un slot disponible (máximo 10 ejecuciones concurrentes)
        async with self._check_positions_semaphore:
            await self._check_positions_for_token(token_address)

    async def _check_positions_for_token(self, token_address: str) -> None:
        """
        Verifica todas las posiciones abiertas para un token específico.
        
        Args:
            token_address: Dirección del token a verificar
        """
        try:
            if not self.position_queue_manager or not self.position_queue_manager.open_queue:
                return

            # Obtener posiciones abiertas para este token
            positions = self.position_queue_manager.open_queue.get_open_positions(
                token_address=token_address
            )

            if not positions:
                return

            # Obtener precio actual desde el último trade recibido
            # Solo usamos precios de trades en tiempo real, sin fallback a Moralis
            price_data = self._token_prices.get(token_address)
            if not price_data:
                return

            current_price = price_data[0]  # Extraer Decimal del tuple
            if not current_price or current_price <= 0:
                return

            # Verificar cada posición
            for position in positions:
                if not self._is_running:
                    break

                try:
                    await self._check_position(position, current_price)
                except Exception as e:
                    self._logger.error(
                        f"Error verificando posición {position.id}: {e}",
                        exc_info=True
                    )
                    self.stats['errors'] += 1

            self.stats['positions_checked'] += len(positions)

        except Exception as e:
            self._logger.error(f"Error en _check_positions_for_token: {e}", exc_info=True)
            self.stats['errors'] += 1

    async def _check_position(
        self,
        position: OpenPosition,
        current_price: Decimal
    ) -> None:
        """
        Verifica una posición individual y la liquida si excede umbrales.
        
        Args:
            position: Posición abierta a verificar
            current_price: Precio actual en SOL/token obtenido del trade
        """
        # Verificar si ya está siendo liquidada
        if position.id in self._positions_being_liquidated:
            return

        # Obtener precio de entrada desde cache (no cambia durante la vida de la posición)
        entry_price = self._entry_price_cache.get(position.id)
        if entry_price is None:
            # Calcular y cachear precio de entrada en SOL/token
            entry_price = await self._calculate_entry_price_sol(position)
            if not entry_price or entry_price <= 0:
                return
            # Guardar en cache para futuros checks
            self._entry_price_cache[position.id] = entry_price

        # Obtener o inicializar peak price (para trailing stop) en SOL/token
        peak_price = self._get_or_initialize_peak_price(position, entry_price, current_price)

        # Actualizar peak price si el precio actual es mayor
        if current_price > peak_price:
            peak_price = current_price
            self._update_peak_price(position, peak_price)
            self.stats['peak_prices_updated'] += 1

        # Calcular cambio porcentual desde entrada
        change_from_entry = ((current_price - entry_price) / entry_price) * Decimal("100.0")

        # Verificar Take Profit (si está habilitado y hay ganancia)
        # Filtrado temprano: solo verificar si hay ganancia positiva
        if self._take_profit_threshold is not None and change_from_entry > 0:
            if change_from_entry >= self._take_profit_threshold:
                self._logger.warning(
                    f"Take Profit activado para posición {position.id}: "
                    f"Ganancia {change_from_entry:.2f}% >= umbral {self._take_profit_threshold}%"
                )
                await self._liquidate_position(
                    position,
                    reason="take_profit",
                    change_percentage=change_from_entry,
                    entry_price=entry_price,
                    current_price=current_price,
                    peak_price=peak_price
                )
                return

        # Verificar Trailing Stop Loss (si está habilitado)
        if self._stop_loss_threshold is not None:
            # Calcular pérdida desde peak price (trailing stop)
            loss_from_peak = ((peak_price - current_price) / peak_price) * Decimal("100.0")

            # También verificar pérdida desde entrada (stop loss inicial)
            # Filtrado temprano: solo calcular si hay pérdida
            loss_from_entry = abs(change_from_entry) if change_from_entry < 0 else Decimal("0.0")

            # Activar si la pérdida desde peak excede el umbral O si la pérdida desde entrada excede el umbral
            if loss_from_peak >= self._stop_loss_threshold or loss_from_entry >= self._stop_loss_threshold:
                self._logger.warning(
                    f"Trailing Stop Loss activado para posición {position.id}: "
                    f"Pérdida desde peak {loss_from_peak:.2f}% >= umbral {self._stop_loss_threshold}% "
                    f"(Pérdida desde entrada: {loss_from_entry:.2f}%)"
                )
                await self._liquidate_position(
                    position,
                    reason="stop_loss",
                    change_percentage=change_from_entry,
                    entry_price=entry_price,
                    current_price=current_price,
                    peak_price=peak_price,
                    loss_from_peak=loss_from_peak
                )
                return


    # ==========================================================================
    # MÉTODOS PRIVADOS - CÁLCULOS Y PRECIOS
    # ==========================================================================
    # Estos métodos reutilizan la lógica de PositionRiskManager

    def _get_or_initialize_peak_price(
        self,
        position: OpenPosition,
        entry_price: Decimal,
        current_price: Decimal
    ) -> Decimal:
        """
        Obtiene el peak price desde metadata o lo inicializa.
        
        Args:
            position: Posición abierta
            entry_price: Precio de entrada en SOL/token
            current_price: Precio actual en SOL/token
            
        Returns:
            Peak price en SOL/token (máximo entre entry, current y peak guardado)
        """
        # Intentar obtener desde metadata
        peak_price_str = position.get_metadata('risk_peak_price_sol')
        if peak_price_str:
            try:
                peak_price = Decimal(str(peak_price_str))
                # Asegurar que peak_price sea al menos el máximo entre entry y current
                peak_price = max(peak_price, entry_price, current_price)
                return peak_price
            except (ValueError, TypeError):
                pass

        # Inicializar con el máximo entre entry y current
        peak_price = max(entry_price, current_price)
        self._update_peak_price(position, peak_price)
        return peak_price

    def _update_peak_price(self, position: OpenPosition, peak_price: Decimal) -> None:
        """
        Actualiza el peak price en metadata de la posición.
        Guarda como string de Decimal para mantener precisión completa (28 dígitos).
        """
        position.add_metadata('risk_peak_price_sol', str(peak_price))
        position.add_metadata('risk_peak_price_timestamp', datetime.now().isoformat())

    def _get_peak_price_from_metadata(self, position: OpenPosition) -> Optional[Decimal]:
        """Obtiene el peak price desde metadata."""
        peak_price_str = position.get_metadata('risk_peak_price_sol')
        if peak_price_str:
            try:
                return Decimal(str(peak_price_str))
            except (ValueError, TypeError):
                pass
        return None

    async def _calculate_entry_price_sol(self, position: OpenPosition) -> Optional[Decimal]:
        """
        Calcula el precio de entrada en SOL/token de una posición.
        
        Args:
            position: Posición abierta
            
        Returns:
            Precio de entrada en SOL/token o None si no se puede calcular
        """
        try:
            # Intentar obtener desde metadata (si fue guardado previamente)
            entry_price_sol_str = position.get_metadata('risk_entry_price_sol')
            if entry_price_sol_str:
                try:
                    return Decimal(str(entry_price_sol_str))
                except (ValueError, TypeError):
                    pass

            # Calcular desde execution_price si está disponible (está en SOL/token)
            if position.execution_price:
                try:
                    execution_price = Decimal(str(position.execution_price))
                    if execution_price > 0:
                        # Guardar en metadata para futuras referencias
                        position.add_metadata('risk_entry_price_sol', str(execution_price))
                        return execution_price
                except (ValueError, TypeError):
                    pass

            # Calcular desde amount_sol_executed / amount_tokens_executed
            if position.amount_sol_executed and position.amount_tokens_executed:
                try:
                    amount_sol = Decimal(str(position.amount_sol_executed))
                    amount_tokens = Decimal(str(position.amount_tokens_executed))

                    if amount_tokens > 0:
                        # Precio en SOL por token - cálculo con alta precisión (28 dígitos)
                        price_sol_per_token = amount_sol / amount_tokens
                        # Guardar en metadata
                        position.add_metadata('risk_entry_price_sol', str(price_sol_per_token))
                        return price_sol_per_token
                except (ValueError, TypeError, ZeroDivisionError) as e:
                    self._logger.debug(f"Error calculando precio desde amounts: {e}")

            # Intentar desde trader_trade_data
            if position.trader_trade_data:
                try:
                    amount_sol = Decimal(str(position.trader_trade_data.amount_sol or "0"))
                    token_amount = Decimal(str(position.trader_trade_data.token_amount or "0"))

                    if token_amount > 0:
                        # Precio en SOL por token - cálculo con alta precisión (28 dígitos)
                        price_sol_per_token = amount_sol / token_amount
                        # Guardar en metadata
                        position.add_metadata('risk_entry_price_sol', str(price_sol_per_token))
                        return price_sol_per_token
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

            return None

        except Exception as e:
            self._logger.error(f"Error calculando precio de entrada: {e}")
            return None

    def _get_cached_sol_price_usd(self) -> Optional[Decimal]:
        """
        Obtiene el precio de SOL/USD desde cache si está disponible y no ha expirado.
        TTLCache maneja automáticamente la expiración.
        
        Returns:
            Precio SOL/USD desde cache o None si no está en cache o expiró
        """
        return self._sol_price_cache.get('price')

    def _set_cached_sol_price_usd(self, price: Decimal) -> None:
        """Guarda el precio de SOL/USD en cache."""
        self._sol_price_cache['price'] = price

    async def _get_sol_price_usd(self) -> Optional[Decimal]:
        """
        Obtiene el precio de SOL en USD desde Moralis (solo para notificaciones).
        Usa cache con TTL alto para optimizar llamadas a la API.
        """
        # Intentar obtener desde cache primero
        cached_price = self._get_cached_sol_price_usd()
        if cached_price is not None:
            self._logger.debug("Precio SOL/USD obtenido desde cache")
            return cached_price

        try:
            SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"
            sol_price_str = await self.price_client.get_token_price_usd(SOL_MINT_ADDRESS)
            if sol_price_str:
                # Convertir a Decimal con alta precisión
                price = Decimal(str(sol_price_str))
                # Guardar en cache
                self._set_cached_sol_price_usd(price)
                return price
            return None
        except Exception as e:
            self._logger.debug(f"Error obteniendo precio SOL/USD: {e}")
            return None

    async def _calculate_token_price_usd_from_sol(
        self,
        token_address: str,
        price_sol_per_token: Decimal
    ) -> Optional[Decimal]:
        """
        Calcula el precio de un token en USD multiplicando SOL/token * SOL/USD.
        Solo para notificaciones - usa precio de SOL desde Moralis.
        
        Args:
            token_address: Dirección del token (no se usa, solo para logging)
            price_sol_per_token: Precio del token en SOL/token (desde trades)
            
        Returns:
            Precio del token en USD o None si no se puede calcular
        """
        try:
            sol_price_usd = await self._get_sol_price_usd()
            if sol_price_usd and sol_price_usd > 0 and price_sol_per_token > 0:
                # Multiplicación con alta precisión (ambos son Decimal)
                price_usd_per_token = price_sol_per_token * sol_price_usd
                return price_usd_per_token
            return None
        except Exception as e:
            self._logger.debug(f"Error calculando precio USD desde SOL para {token_address}: {e}")
            return None

    # ==========================================================================
    # MÉTODOS PRIVADOS - LIQUIDACIÓN
    # ==========================================================================

    def _get_liquidation_retry_count(self, position: OpenPosition) -> int:
        """Obtiene el número de reintentos de liquidación desde metadata."""
        retry_count_str = position.get_metadata('risk_liquidation_retry_count')
        if retry_count_str:
            try:
                return int(retry_count_str)
            except (ValueError, TypeError):
                pass
        return 0

    def _increment_liquidation_retry_count(self, position: OpenPosition) -> int:
        """Incrementa el contador de reintentos de liquidación."""
        current_count = self._get_liquidation_retry_count(position)
        new_count = current_count + 1
        position.add_metadata('risk_liquidation_retry_count', str(new_count))
        position.add_metadata('risk_liquidation_last_retry', datetime.now().isoformat())
        return new_count

    def _cancel_cleanup_task_for_position(self, position_id: str) -> None:
        """
        Cancela la tarea de limpieza de timeout para una posición específica.
        
        Args:
            position_id: ID de la posición
        """
        task = self._cleanup_timeout_tasks.get(position_id)
        if task and not task.done():
            task.cancel()
            self._cleanup_timeout_tasks.pop(position_id, None)

    async def _cleanup_position_on_timeout(self, position_id: str, timeout: float) -> None:
        """
        Tarea de limpieza de seguridad que remueve la posición después de un timeout
        si los handlers no lo hicieron antes.
        
        Args:
            position_id: ID de la posición a limpiar
            timeout: Tiempo en segundos antes de limpiar
        """
        try:
            await asyncio.sleep(timeout)

            # Verificar si aún está en el set (significa que los handlers no lo procesaron)
            if position_id in self._positions_being_liquidated:
                self._logger.warning(
                    f"Timeout de seguridad: removiendo posición {position_id} de "
                    f"_positions_being_liquidated después de {timeout}s sin recibir evento"
                )
                self._positions_being_liquidated.discard(position_id)
                self._position_close_events.pop(position_id, None)
        except asyncio.CancelledError:
            # Tarea cancelada (normal cuando se detiene el manager o cuando el handler procesa el evento)
            pass
        except Exception as e:
            self._logger.error(f"Error en limpieza de seguridad para posición {position_id}: {e}")
        finally:
            # Remover esta tarea del diccionario cuando termine (exitosa o cancelada)
            self._cleanup_timeout_tasks.pop(position_id, None)

    async def _discard_position(self, position: OpenPosition, reason: str) -> None:
        """Descarta una posición de la cola de abiertas después de máximo de reintentos."""
        try:
            self._logger.warning(
                f"Descartando posición {position.id} de cola de abiertas: "
                f"{reason} (máximo de reintentos alcanzado)"
            )

            if self.position_queue_manager.open_queue:
                await self.position_queue_manager.open_queue.remove_position(position, register_data=True)
                self.stats['positions_discarded'] += 1

                # Limpiar cache de precio de entrada cuando se descarta
                self._entry_price_cache.pop(position.id, None)

                if self.notification_manager:
                    message = (
                        f"⚠️ Posición descartada\n"
                        f"Posición: {position.id[:8]}...\n"
                        f"Razón: {reason}\n"
                        f"Token: {position.token_address[:8]}...\n"
                        f"Se alcanzó el máximo de reintentos de liquidación"
                    )
                    await self.notification_manager.notify_system(message, "error")
        except Exception as e:
            self._logger.error(f"Error descartando posición {position.id}: {e}", exc_info=True)

    async def _liquidate_position(
        self,
        position: OpenPosition,
        reason: str,
        change_percentage: Decimal,
        entry_price: Decimal,
        current_price: Decimal,
        peak_price: Decimal,
        loss_from_peak: Optional[Decimal] = None
    ) -> None:
        """
        Liquida una posición que excedió un umbral.
        
        Args:
            position: Posición a liquidar
            reason: "stop_loss" o "take_profit"
            change_percentage: Cambio porcentual desde entrada
            entry_price: Precio de entrada en SOL/token
            current_price: Precio actual en SOL/token
            peak_price: Peak price alcanzado en SOL/token
            loss_from_peak: Pérdida desde peak (solo para stop_loss)
        """
        if position.id in self._positions_being_liquidated:
            self._logger.debug(f"Posición {position.id} ya está siendo liquidada")
            return

        self._positions_being_liquidated.add(position.id)

        # Crear evento para esperar confirmación de cierre
        close_event = asyncio.Event()
        self._position_close_events[position.id] = close_event

        # Variables para el finally (inicializadas por si hay excepción antes de asignarlas)
        liquidation_success = False
        liquidation_signature: Optional[str] = None

        try:
            # Obtener precios en USD solo para logging y notificaciones
            # Calculamos desde SOL/token * SOL/USD (precio SOL desde Moralis)
            entry_price_usd = None
            current_price_usd = None
            peak_price_usd = None

            try:
                # Calcular USD desde SOL/token * SOL/USD
                # current_price viene de trades, SOL/USD viene de Moralis (solo para notificaciones)
                current_price_usd = await self._calculate_token_price_usd_from_sol(
                    position.token_address,
                    current_price
                )
                if current_price_usd and entry_price > 0 and current_price > 0:
                    # Calcular entry y peak en USD proporcionalmente
                    entry_price_usd = (entry_price / current_price) * current_price_usd
                    peak_price_usd = (peak_price / current_price) * current_price_usd
            except Exception as e:
                self._logger.debug(f"Error calculando precios USD para notificaciones: {e}")
                # Si falla, continuamos sin USD (no es crítico)

            if reason == "stop_loss":
                self._logger.info(
                    f"Liquidando posición {position.id} por Trailing Stop Loss: "
                    f"Pérdida desde peak {loss_from_peak:.2f}% "
                    f"(Entrada: {entry_price:.10f} SOL/token, Peak: {peak_price:.10f} SOL/token, "
                    f"Actual: {current_price:.10f} SOL/token)"
                )
            else:
                self._logger.info(
                    f"Liquidando posición {position.id} por Take Profit: "
                    f"Ganancia {change_percentage:.2f}% "
                    f"(Entrada: {entry_price:.10f} SOL/token, Actual: {current_price:.10f} SOL/token)"
                )

            # Crear PositionTraderTradeData para liquidación
            trader_trade_data = TraderTradeData(
                trader_wallet=position.trader_wallet,
                side="sell",
                token_address=position.token_address,
                amount_sol="",
                signature="",
                token_amount=position.amount_tokens_executed or position.amount_tokens,
                tokens_in_pool="",
                sol_in_pool="",
                new_token_balance="",
                pool="auto",
                bonding_curve_key="",
                v_tokens_in_bonding_curve="",
                v_sol_in_bonding_curve="",
                market_cap_sol="",
                timestamp=datetime.now(),
            )

            position_trader_trade_data = PositionTraderTradeData(
                trader_trade_data=trader_trade_data,
                copy_amount_tokens=position.amount_tokens_executed or position.amount_tokens,
                denominate_in_sol=False,
                is_liquidation=True
            )

            # Ejecutar liquidación
            success, signature, error_message = await self.transaction_executor.execute_trade(
                position_trader_trade_data
            )

            # Guardar para usar en finally
            liquidation_success = success
            liquidation_signature = signature

            if liquidation_success and liquidation_signature:
                # Resetear contador de reintentos si la liquidación fue exitosa
                position.add_metadata('risk_liquidation_retry_count', '0')

                # Limpiar cache de precio de entrada cuando se liquida exitosamente
                self._entry_price_cache.pop(position.id, None)

                # liquidation_signature ya fue verificado que no es None en el if anterior
                assert liquidation_signature is not None, "signature should not be None when success is True"

                if reason == "stop_loss":
                    self._logger.info(
                        f"Posición {position.id} liquidada exitosamente por Trailing Stop Loss: {liquidation_signature}"
                    )
                    self.stats['stop_loss_triggered'] += 1
                else:
                    self._logger.info(
                        f"Posición {position.id} liquidada exitosamente por Take Profit: {liquidation_signature}"
                    )
                    self.stats['take_profit_triggered'] += 1

                # Procesar posición ejecutada para actualizar colas y emitir eventos
                # Esto actualiza la cola de posiciones abiertas y envía notificaciones
                self._logger.debug(f"Procesando posición ejecutada para liquidación - Signature: {liquidation_signature}")
                await self.position_queue_manager.process_executed_position(
                    position_trade_data=position_trader_trade_data,
                    signature=liquidation_signature,
                )
                self._logger.debug(f"Posición de liquidación procesada exitosamente")

                # Notificar (usar USD solo para mostrar)
                if self.notification_manager:
                    entry_display = f"${entry_price_usd:.10f}" if entry_price_usd else f"{entry_price:.10f} SOL/token"
                    current_display = f"${current_price_usd:.10f}" if current_price_usd else f"{current_price:.10f} SOL/token"

                    if reason == "stop_loss":
                        peak_display = f"${peak_price_usd:.10f}" if peak_price_usd else f"{peak_price:.10f} SOL/token"
                        message = (
                            f"🛑 Trailing Stop Loss triggered\n"
                            f"Position: {position.id[:8]}...\n"
                            f"Loss from peak: {loss_from_peak:.2f}%\n"
                            f"Entry: {entry_display}\n"
                            f"Peak: {peak_display}\n"
                            f"Current: {current_display}\n"
                            f"Signature: {liquidation_signature[:16]}..."
                        )
                    else:
                        message = (
                            f"🎯 Take Profit triggered\n"
                            f"Position: {position.id[:8]}...\n"
                            f"Gain: {change_percentage:.2f}%\n"
                            f"Entry: {entry_display}\n"
                            f"Current: {current_display}\n"
                            f"Signature: {liquidation_signature[:16]}..."
                        )
                    await self.notification_manager.notify_system(message, "warning" if reason == "stop_loss" else "success")

            else:
                # Incrementar contador de reintentos
                retry_count = self._increment_liquidation_retry_count(position)
                max_retries = self.config.risk_management_max_liquidation_retries

                self._logger.warning(
                    f"Error al liquidar posición {position.id} por {reason}: {error_message} "
                    f"(Reintento {retry_count}/{max_retries})"
                )

                # Si se alcanzó el máximo de reintentos, descartar la posición
                if retry_count >= max_retries:
                    await self._discard_position(position, f"Error en liquidación: {error_message}")
                else:
                    self.stats['errors'] += 1

        except Exception as e:
            self._logger.error(
                f"Error inesperado liquidando posición {position.id}: {e}",
                exc_info=True
            )
            self.stats['errors'] += 1
            # Si hay error, los handlers no podrán procesar, así que limpiamos aquí
            self._positions_being_liquidated.discard(position.id)
            self._position_close_events.pop(position.id, None)
        finally:
            # Los handlers se encargan de limpiar _positions_being_liquidated cuando llegan los eventos
            # Aquí solo limpiamos el Event del diccionario si la liquidación falló
            # (si fue exitosa, los handlers lo limpiarán cuando llegue el evento)
            if not liquidation_success or liquidation_signature is None:
                # Si la liquidación falló, no esperamos eventos, limpiamos inmediatamente
                self._positions_being_liquidated.discard(position.id)
                self._position_close_events.pop(position.id, None)

            # Si fue exitosa, dejamos que los handlers limpien cuando llegue el evento
            # Pero programamos una tarea de limpieza de seguridad con timeout
            elif liquidation_success and liquidation_signature is not None:
                # Crear tarea de limpieza de seguridad por si el evento nunca llega
                # Guardar referencia para evitar que el garbage collector la limpie
                cleanup_task = asyncio.create_task(self._cleanup_position_on_timeout(position.id, 600.0))
                self._cleanup_timeout_tasks[position.id] = cleanup_task
