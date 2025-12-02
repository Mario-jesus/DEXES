# -*- coding: utf-8 -*-
"""
Callback especializado para notificaciones de posiciones en Copy Trading.
Integra con NotificationManager para procesar diferentes tipos de eventos.
"""
import re
import uuid
from typing import Optional, Union, Dict, Any, Tuple
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from cachetools import TTLCache

from logging_system import AppLogger
from ..notifications import NotificationManager
from ..data_management.moralis.price_client import MoralisPriceClient
from ..data_management import TokenTraderManager
from ..data_management.models import TokenInfo
from ..position_management.models import (
    OpenPosition, 
    ClosePosition, 
    SubClosePosition, 
    PositionStatus, 
    ClosePositionStatus, 
)
from ..position_management.services import (
    PositionValidationService, 
    PnLCalculationService, 
    PositionCalculationService
)
from ..persistence.repositories import PNLRepository



class PositionNotificationCallback:
    """
    Callback especializado para notificaciones de posiciones.
    Procesa diferentes tipos de eventos y envía notificaciones apropiadas.
    """

    def __init__(
        self,
        run_id: uuid.UUID,
        notification_manager: Optional[NotificationManager] = None,
        price_client: Optional[MoralisPriceClient] = None,
        token_trader_manager: Optional[TokenTraderManager] = None,
        pnl_repository: Optional[PNLRepository] = None
    ):
        """
        Inicializa el callback de notificaciones.
        
        Args:
            run_id: ID del run al que pertenecen las posiciones
            notification_manager: Manager de notificaciones
            price_client: Cliente de Moralis para obtener precios
            token_trader_manager: Manager de traders y tokens
            pnl_repository: Repositorio para almacenar PNL realizado
        """
        self.run_id = run_id
        self.notification_manager = notification_manager
        self.price_client = price_client
        self.token_trader_manager = token_trader_manager
        self.pnl_repository = pnl_repository or PNLRepository()
        self._logger = AppLogger(self.__class__.__name__)

        # Instanciar servicios
        self.validation_service = PositionValidationService()
        self.pnl_calculation_service = PnLCalculationService()
        self.position_calculation_service = PositionCalculationService()

        # Cache de precios de SOL en USD
        self.sol_price_usd_cache: TTLCache[str, str] = TTLCache(maxsize=1, ttl=300)

        # Estadísticas
        self.stats = {
            'total_notifications': 0,
            'success_notifications': 0,
            'failed_notifications': 0,
            'error_notifications': 0,
            'last_notification_time': None
        }

        self._logger.debug("PositionNotificationCallback inicializado")

    async def __call__(self, position: Union[OpenPosition, ClosePosition, SubClosePosition]) -> None:
        """
        Procesa una posición y envía la notificación apropiada.
        
        Args:
            position: Posición a notificar
        """
        try:
            self.stats['total_notifications'] += 1
            self.stats['last_notification_time'] = datetime.now()

            position_id = position.id
            self._logger.debug(f"Procesando notificación para posición: {position_id}")

            # Determinar el tipo de notificación según el tipo y estado de la posición
            if isinstance(position, OpenPosition):
                self._logger.debug(f"Posición {position_id} es OpenPosition")
                await self._handle_open_position_notification(position)
            elif isinstance(position, (ClosePosition, SubClosePosition)):
                self._logger.debug(f"Posición {position_id} es ClosePosition/SubClosePosition")
                await self._handle_close_position_notification(position)
            else:
                self._logger.warning(f"Tipo de posición desconocido: {type(position)}")
                return

            self.stats['success_notifications'] += 1
            self._logger.debug(f"Notificación procesada exitosamente para posición: {position_id}")

        except Exception as e:
            self.stats['failed_notifications'] += 1
            position_id = position.id
            self._logger.error(f"Error procesando notificación para posición {position_id}: {e}", exc_info=True)

    async def _handle_open_position_notification(self, position: OpenPosition) -> None:
        """
        Maneja notificaciones para posiciones abiertas.
        Determina si es apertura, cierre total o fallida basado en el estado.
        
        Args:
            position: Posición abierta
        """
        if not self.notification_manager:
            self._logger.debug("NotificationManager no disponible, saltando notificación")
            return

        self._logger.debug(f"Manejando notificación de OpenPosition: {position.id}, estado: {position.status}")

        # Extraer información del token
        token_info = await self._extract_token_info(position)
        trader_info = await self._extract_trader_info(position)

        # Determinar el tipo de notificación según el estado
        if position.status == PositionStatus.OPEN:
            # Posición abierta exitosamente
            self._logger.debug(f"Notificando apertura de posición: {position.id}")
            await self._notify_position_opened(position, token_info, trader_info)
        elif position.status == PositionStatus.CLOSED:
            # Posición cerrada completamente
            self._logger.debug(f"Notificando cierre completo de posición: {position.id}")
            await self._notify_position_closed(position, token_info, trader_info)
        elif position.status == PositionStatus.FAILED:
            # Posición falló
            self._logger.debug(f"Notificando fallo de posición: {position.id}")
            await self._notify_position_failed(position, token_info, trader_info)
        elif position.status == PositionStatus.PARTIALLY_CLOSED:
            # Posición cerrada parcialmente (esto se maneja con ClosePosition/SubClosePosition)
            self._logger.debug(f"Posición parcialmente cerrada - se manejará con notificación de cierre")
        else:
            self._logger.debug(f"Estado de posición no manejado para notificación: {position.status}")

    async def _handle_close_position_notification(self, close_position: Union[ClosePosition, SubClosePosition]) -> None:
        """
        Maneja notificaciones para cierres de posición (parciales).
        Determina si fue exitoso o fallido basado en el estado.
        
        Args:
            close_position: Cierre de posición (ClosePosition o SubClosePosition)
        """
        if not self.notification_manager:
            self._logger.debug("NotificationManager no disponible, saltando notificación")
            return

        position_id = close_position.id
        self._logger.debug(f"Manejando notificación de ClosePosition: {position_id}, estado: {close_position.status}")

        # Extraer información del token
        token_info = await self._extract_token_info(close_position)
        trader_info = await self._extract_trader_info(close_position)

        # Determinar el tipo de notificación según el estado
        if close_position.status == ClosePositionStatus.SUCCESS:
            # Cierre parcial exitoso
            self._logger.debug(f"Notificando cierre parcial exitoso: {position_id}")
            await self._notify_partial_close_success(close_position, token_info, trader_info)
        elif close_position.status == ClosePositionStatus.FAILED:
            # Cierre parcial fallido
            self._logger.debug(f"Notificando cierre parcial fallido: {position_id}")
            await self._notify_partial_close_failed(close_position, token_info, trader_info)
        else:
            self._logger.debug(f"Estado de cierre no manejado para notificación: {close_position.status}")

    async def _extract_token_info(self, position: Union[OpenPosition, ClosePosition, SubClosePosition]) -> Dict[str, str]:
        """
        Extrae información del token desde metadata o usa fallbacks.
        
        Args:
            position: Posición de la cual extraer información
            
        Returns:
            Dict con name, symbol y address del token
        """
        # Extraer token_address
        token_address: str = position.token_address
        self._logger.debug(f"Extrayendo token_address: {token_address[:8] if token_address else 'None'}...")

        if not token_address and hasattr(position, 'trader_trade_data') and isinstance(position, (OpenPosition, ClosePosition)) and position.trader_trade_data:
            token_address = position.trader_trade_data.token_address
            self._logger.debug(f"token_address obtenido de trader_trade_data: {token_address[:8]}...")

        # SIEMPRE consultar token_trader_manager primero para obtener información fresca
        token_info: Optional[TokenInfo] = None
        if self.token_trader_manager:
            self._logger.debug(f"Consultando token_trader_manager para obtener información fresca del token {token_address[:8]}...")
            token_info = await self.token_trader_manager.get_token_info(token_address)
            self._logger.debug(f"token_info obtenido de token_trader_manager: {token_info.name if token_info else 'None'}")

            # Verificar si la información obtenida es válida (no genérica)
            if token_info:
                has_valid_name = token_info.name and token_info.name.strip() not in ('Unknown', '')
                has_valid_symbol = token_info.symbol and token_info.symbol.strip() not in ('UNK', '')

                if not has_valid_name or not has_valid_symbol:
                    self._logger.debug(f"token_info del manager tiene información genérica (name='{token_info.name}', symbol='{token_info.symbol}'), intentando refresh forzado")
                    # Intentar un refresh forzado una vez
                    token_info = await self.token_trader_manager.get_token_info(token_address, force_refresh=True)
                    self._logger.debug(f"token_info tras refresh forzado: {token_info.name if token_info else 'None'}")

        # Fallback: intentar extraer desde metadata solo si no se pudo obtener del manager
        if not token_info:
            self._logger.debug(f"No se pudo obtener token_info del manager, intentando desde metadata")
            if isinstance(position, SubClosePosition):
                token_info = position.close_position.get_metadata('token_info')
            else:
                token_info = position.get_metadata('token_info')
            self._logger.debug(f"token_info desde metadata: {token_info.name if token_info else 'None'}")

        # Actualizar metadata con la información más fresca obtenida
        if token_info:
            if isinstance(position, SubClosePosition):
                self._logger.debug(f"Actualizando token_info en close_position.metadata para SubClosePosition")
                position.close_position.add_metadata('token_info', token_info)
            else:
                self._logger.debug(f"Actualizando token_info en position.metadata")
                position.add_metadata('token_info', token_info)

        resultado = {
            'name': token_info.name if token_info else 'Unknown',
            'symbol': token_info.symbol if token_info else 'UNK',
            'address': token_address,
        }
        self._logger.debug(f"Resultado de _extract_token_info: {resultado['name']} ({resultado['symbol']})")
        return resultado

    def _is_timeout_liquidation(self, position: OpenPosition) -> Tuple[bool, Optional[str]]:
        """
        Verifica si una posición de apertura fue cerrada por timeout o es una posición errónea por timeout.
        Solo lee los metadatos de la posición de apertura.
        
        Args:
            position: Posición de apertura a verificar
            
        Returns:
            Tuple con (es_timeout, timeout_info)
            - es_timeout: True si fue por timeout
            - timeout_info: Información adicional del timeout (edad en segundos, intentos, etc.)
        """
        # Verificar si el message_error indica timeout fallido
        if position.message_error and "Timeout closure failed" in position.message_error:
            attempts_match = re.search(r'after (\d+) attempts', position.message_error)
            attempts = attempts_match.group(1) if attempts_match else "?"
            return True, f"Timeout closure failed after {attempts} attempts"

        # Verificar si fue removida por timeout (fallo)
        timeout_removed = position.get_metadata("timeout_removed_from_open_queue")
        if timeout_removed:
            attempts = int(position.get_metadata("timeout_closure_attempts", 0) or 0)
            return True, f"Removed after {attempts} timeout closure attempts"

        # Verificar metadata de timeout_closed en la posición de apertura
        timeout_closed = position.get_metadata("timeout_closed")
        if timeout_closed:
            timeout_age = position.get_metadata("timeout_age_seconds")
            if timeout_age:
                try:
                    age_seconds = int(timeout_age)
                    hours = age_seconds // 3600
                    minutes = (age_seconds % 3600) // 60
                    if hours > 0:
                        age_str = f"{hours}h {minutes}m"
                    else:
                        age_str = f"{minutes}m"
                    return True, f"Closed by timeout after {age_str}"
                except (ValueError, TypeError):
                    return True, "Closed by timeout"
            return True, "Closed by timeout"

        return False, None

    async def _extract_trader_info(self, position: Union[OpenPosition, ClosePosition, SubClosePosition]) -> Dict[str, str]:
        """
        Extrae información del trader desde metadata o usa fallbacks.
        """
        if isinstance(position, SubClosePosition):
            trader_nickname = position.close_position.get_metadata("trader_nickname")
        else:
            trader_nickname = position.get_metadata("trader_nickname")
        self._logger.debug(f"Trader nickname from metadata: {trader_nickname}")

        if not trader_nickname and self.token_trader_manager:
            trader_stats = await self.token_trader_manager.get_trader_stats(position.trader_wallet)
            trader_nickname = trader_stats.nickname
            self._logger.debug(f"Trader nickname from token_trader_manager: {trader_nickname}")

        return {
            'nickname': trader_nickname if trader_nickname else 'Unknown',
        }

    async def _get_sol_price_usd(self) -> Optional[str]:
        """Obtiene el precio del SOL en USD"""
        if not self.price_client:
            self._logger.warning("MoralisPriceClient no está disponible para obtener el precio SOL/USD")
            return

        if "sol_price_usd" not in self.sol_price_usd_cache:
            self._logger.info("Precio SOL/USD no encontrado en cache, solicitando a MoralisPriceClient")
            try:
                # Dirección del token SOL en Solana
                SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"
                sol_price_usd = await self.price_client.get_token_price_usd(SOL_MINT_ADDRESS)
                if sol_price_usd:
                    self.sol_price_usd_cache["sol_price_usd"] = sol_price_usd
                    self._logger.debug(f"Precio SOL/USD obtenido y almacenado en cache: {sol_price_usd}")
                else:
                    self._logger.error("No se pudo obtener el precio SOL/USD desde MoralisPriceClient")
                    return
            except Exception as e:
                self._logger.error(f"Error obteniendo precio SOL/USD desde MoralisPriceClient: {e}")
                return
        else:
            self._logger.debug(f"Precio SOL/USD obtenido del cache: {self.sol_price_usd_cache['sol_price_usd']}")

        return self.sol_price_usd_cache["sol_price_usd"]

    async def _calculate_pnl(self, position: Union[OpenPosition, ClosePosition, SubClosePosition], sol_price_usd: Optional[str]) -> Dict[str, str]:
        """Calcula el P&L de una posición sin registrarlo."""
        try:
            position_id = position.id
            self._logger.debug(f"Calculando P&L para la posición: {position_id}")

            pnl_sol = "0.0"
            pnl_usd = "0.0"
            pnl_sol_with_costs = "0.0"
            pnl_usd_with_costs = "0.0"

            if sol_price_usd:
                if isinstance(position, OpenPosition):
                    pnl_sol, pnl_usd, pnl_sol_with_costs, pnl_usd_with_costs = self.pnl_calculation_service.calculate_realized_pnl_with_costs_breakdown(position, sol_price_usd)
                elif isinstance(position, (ClosePosition, SubClosePosition)):
                    pnl_sol, pnl_usd, pnl_sol_with_costs, pnl_usd_with_costs = self.pnl_calculation_service.calculate_realized_pnl_for_partial_close_with_costs_breakdown(position, sol_price_usd)
                else:
                    self._logger.error(f"Tipo de posición desconocido: {type(position)}")
                    return {
                        "pnl_sol": pnl_sol,
                        "pnl_usd": pnl_usd,
                        "pnl_sol_with_costs": pnl_sol_with_costs,
                        "pnl_usd_with_costs": pnl_usd_with_costs,
                    }

                self._logger.debug(f"P&L calculado: pnl_sol={pnl_sol}, pnl_usd={pnl_usd}, pnl_sol_with_costs={pnl_sol_with_costs}, pnl_usd_with_costs={pnl_usd_with_costs}")

                # Agregar P&L a la posición
                position.add_metadata('pnl_sol', pnl_sol)
                position.add_metadata('pnl_usd', pnl_usd)
                position.add_metadata('pnl_sol_with_costs', pnl_sol_with_costs)
                position.add_metadata('pnl_usd_with_costs', pnl_usd_with_costs)

            return {
                "pnl_sol": pnl_sol,
                "pnl_usd": pnl_usd,
                "pnl_sol_with_costs": pnl_sol_with_costs,
                "pnl_usd_with_costs": pnl_usd_with_costs,
            }
        except Exception as e:
            self._logger.error(f"Error al calcular P&L: {e}")
            return {
                "pnl_sol": "0.0",
                "pnl_usd": "0.0",
                "pnl_sol_with_costs": "0.0",
                "pnl_usd_with_costs": "0.0",
            }

    async def _register_trader_stats(self, position: OpenPosition, pnl_sol: str, pnl_sol_with_costs: str, sol_price_usd: Optional[str]) -> Dict[str, str]:
        """Registra las estadísticas del trader en el token_trader_manager.

        Args:
            position: Posición para registrar estadísticas
            pnl_sol: P&L en SOL sin costos
            pnl_sol_with_costs: P&L en SOL con costos
            sol_price_usd: Precio de SOL en USD

        Returns:
            Dict con las estadísticas acumuladas por token y totales
        """
        position_id = position.id
        self._logger.debug(f"Registrando estadísticas del trader para la posición: {position_id}")

        pnl_sol_acc_token = "0.0"
        pnl_usd_acc_token = "0.0"
        pnl_sol_with_costs_acc_token = "0.0"
        pnl_usd_with_costs_acc_token = "0.0"

        pnl_sol_acc_total = "0.0"
        pnl_usd_acc_total = "0.0"
        pnl_sol_with_costs_acc_total = "0.0"
        pnl_usd_with_costs_acc_total = "0.0"

        total_volume_sol_open_token = "0.0"
        total_volume_sol_closed_token = "0.0"
        total_volume_sol_open_total = "0.0"
        total_volume_sol_closed_total = "0.0"

        if self.token_trader_manager:
            self._logger.debug(f"Registrando P&L en token_trader_manager para wallet: {position.trader_wallet[:8]}... y token: {position.token_address[:8]}... | pnl_sol={pnl_sol}, pnl_sol_with_costs={pnl_sol_with_costs}")
            # Usar el nuevo método que actualiza TraderStats y TraderTokenStats simultáneamente
            await self.token_trader_manager.register_trader_token_pnl(
                position.trader_wallet, 
                position.token_address, 
                pnl_sol, 
                pnl_sol_with_costs
            )

            # Obtener estadísticas específicas del trader para este token
            trader_token_stats = await self.token_trader_manager.get_trader_token_stats(position.trader_wallet, position.token_address)
            self._logger.debug(f"Trader token stats obtenidas para {position.token_address[:8]}... | pnl_sol={pnl_sol_acc_token}, pnl_sol_with_costs={pnl_sol_with_costs_acc_token}")

            # Calcular P&L acumulado específico por token
            pnl_sol_acc_token = trader_token_stats.total_pnl_sol
            pnl_usd_acc_token = format(Decimal(pnl_sol_acc_token) * Decimal(sol_price_usd or "0.0"), "f")
            pnl_sol_with_costs_acc_token = trader_token_stats.total_pnl_sol_with_costs
            pnl_usd_with_costs_acc_token = format(Decimal(pnl_sol_with_costs_acc_token) * Decimal(sol_price_usd or "0.0"), "f")

            total_volume_sol_open_token = trader_token_stats.total_volume_sol_open
            total_volume_sol_closed_token = trader_token_stats.total_volume_sol_closed

            self._logger.debug(f"P&L acumulado por token: pnl_sol_acc_token={pnl_sol_acc_token}, pnl_usd_acc={pnl_usd_acc_token}, pnl_sol_with_costs_acc_token={pnl_sol_with_costs_acc_token}, pnl_usd_with_costs_acc_token={pnl_usd_with_costs_acc_token}")

            # Agregar metadatos específicos por token
            position.add_metadata('pnl_sol_acc_token', pnl_sol_acc_token)
            position.add_metadata('pnl_usd_acc_token', pnl_usd_acc_token)
            position.add_metadata('pnl_sol_with_costs_acc_token', pnl_sol_with_costs_acc_token)
            position.add_metadata('pnl_usd_with_costs_acc_token', pnl_usd_with_costs_acc_token)

            # También agregar estadísticas generales del trader para referencia
            trader_stats = await self.token_trader_manager.get_trader_stats(position.trader_wallet)
            pnl_sol_acc_total = trader_stats.total_pnl_sol
            pnl_usd_acc_total = format(Decimal(pnl_sol_acc_total) * Decimal(sol_price_usd or "0.0"), "f")
            pnl_sol_with_costs_acc_total = trader_stats.total_pnl_sol_with_costs
            pnl_usd_with_costs_acc_total = format(Decimal(pnl_sol_with_costs_acc_total) * Decimal(sol_price_usd or "0.0"), "f")

            position.add_metadata('pnl_sol_acc_total', pnl_sol_acc_total)
            position.add_metadata('pnl_usd_acc_total', pnl_usd_acc_total)
            position.add_metadata('pnl_sol_with_costs_acc_total', pnl_sol_with_costs_acc_total)
            position.add_metadata('pnl_usd_with_costs_acc_total', pnl_usd_with_costs_acc_total)

            total_volume_sol_open_total = trader_stats.total_volume_sol_open
            total_volume_sol_closed_total = trader_stats.total_volume_sol_closed

        return {
            "pnl_sol_acc_token": pnl_sol_acc_token,
            "pnl_usd_acc_token": pnl_usd_acc_token,
            "pnl_sol_with_costs_acc_token": pnl_sol_with_costs_acc_token,
            "pnl_usd_with_costs_acc_token": pnl_usd_with_costs_acc_token,
            "pnl_sol_acc_total": pnl_sol_acc_total,
            "pnl_usd_acc_total": pnl_usd_acc_total,
            "pnl_sol_with_costs_acc_total": pnl_sol_with_costs_acc_total,
            "pnl_usd_with_costs_acc_total": pnl_usd_with_costs_acc_total,
            "total_volume_sol_open_token": total_volume_sol_open_token,
            "total_volume_sol_closed_token": total_volume_sol_closed_token,
            "total_volume_sol_open_total": total_volume_sol_open_total,
            "total_volume_sol_closed_total": total_volume_sol_closed_total
        }

    async def _calculate_pnl_and_register_trader_stats(self, position: OpenPosition) -> Dict[str, str]:
        """Método general que calcula el P&L y registra las estadísticas del trader.

        Args:
            position: Posición a calcular el P&L y registrar estadísticas

        Returns:
            Dict con el P&L en SOL, USD, P&L acumulado en SOL, USD
        """
        position_id = position.id
        self._logger.debug(f"Iniciando cálculo de P&L y registro de estadísticas para la posición: {position_id}")

        # Obtener precio de SOL en USD
        sol_price_usd = await self._get_sol_price_usd()
        self._logger.debug(f"Precio SOL/USD obtenido: {sol_price_usd}")

        # 1. Calcular P&L
        pnl_data = await self._calculate_pnl(position, sol_price_usd)

        # 2. Registrar estadísticas del trader
        trader_stats_data = await self._register_trader_stats(
            position,
            pnl_data['pnl_sol'],
            pnl_data['pnl_sol_with_costs'],
            sol_price_usd
        )

        # Combinar resultados
        resultado = {**pnl_data, **trader_stats_data}
        self._logger.debug(f"Cálculo de P&L y registro de estadísticas completado para posición: {position_id}")
        return resultado

    async def _notify_position_opened(self, position: OpenPosition, token_info: Dict[str, str], trader_info: Dict[str, str]) -> None:
        """Notifica apertura exitosa de posición"""
        try:
            self._logger.debug(f"Enviando notificación de posición abierta: {position.id}")

            trader_wallet = position.trader_wallet
            amount_sol = position.amount_sol_executed
            amount_tokens = position.amount_tokens_executed

            self._logger.debug(f"amount_sol: {amount_sol}, amount_tokens: {amount_tokens}, total_cost_sol: {position.total_cost_sol}, fee_sol: {position.fee_sol}")

            sol_price_usd = await self._get_sol_price_usd()
            amount_sol_usd = float(amount_sol or "0.0") * float(sol_price_usd or "0.0")

            fee_sol = position.total_cost_sol
            fee_sol_usd = float(fee_sol or "0.0") * float(sol_price_usd or "0.0")

            # Obtener información de porcentajes
            percentage_info = await self._get_percentage_info(position)

            # Añadir información de validaciones
            min_sol_amount_valid = position.get_metadata("min_sol_amount_valid")
            activity_valid = position.get_metadata("activity_valid")
            is_min_sol_enabled = position.get_metadata("is_min_sol_enabled")
            is_activity_enabled = position.get_metadata("is_activity_enabled")

            def _validation_status(val: Optional[bool], enabled: Optional[bool]) -> str:
                if not enabled or enabled in [False, "False", None, ""]:
                    return "Not active"
                if val is True or val == "True":
                    return "✅"
                elif val is False or val == "False":
                    return "❌"
                elif val is None or val == "":
                    return "❔"
                return f"❔ ({val})"

            message = (
                f"🟢 <b>Position Opened</b>\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address']}\n\n"

                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                f"🔗 <b>Address:</b> {trader_wallet}\n\n"

                f"💰 <b>Trade Details</b>\n"
                f"{'─'*12}\n"
                f"🔑 <b>ID Position:</b> {position.id}\n"
                f"🔗 <b>Signature:</b> {position.execution_signature or 'N/A'}\n"
                f"📥 <b>Amount:</b> {self._format_amount(amount_sol)} SOL ({self._format_amount(amount_sol_usd)} USD)\n"
                f"🪙 <b>Tokens:</b> {self._format_amount(amount_tokens)}\n"
                f"🧾 <b>Fee:</b> {self._format_amount(fee_sol)} SOL ({self._format_amount(fee_sol_usd)} USD)\n\n"

                f"🛡️ <b>Validations</b>\n"
                f"{'─'*12}\n"
                f"💸 <b>Min SOL Amount:</b> {_validation_status(min_sol_amount_valid, is_min_sol_enabled)}\n"
                f"📈 <b>Trade Activity:</b> {_validation_status(activity_valid, is_activity_enabled)}\n\n"

                f"{percentage_info}"
                f"⏰ <b>Time:</b> {position.executed_at.strftime('%Y-%m-%d %H:%M:%S') if position.executed_at else 'N/A'}"
            )

            if self.notification_manager:
                await self.notification_manager.notify(message, "success")
                self._logger.debug(f"Notificación de posición abierta enviada: {position.id}")

        except Exception as e:
            self.stats['error_notifications'] += 1
            self._logger.error(f"Error en notificación de posición abierta: {e}")

    async def _notify_position_closed(self, position: OpenPosition, token_info: Dict[str, str], trader_info: Dict[str, str]) -> None:
        """Notifica cierre completo de posición"""
        try:
            self._logger.debug(f"Enviando notificación de posición cerrada: {position.id}")

            # Debug: Log información de la posición
            self._logger.debug(f"Position debug - ID: {position.id}, Amount SOL: {position.amount_sol_executed}, Amount Tokens: {position.amount_tokens_executed}, Total Cost: {position.total_cost_sol}")
            self._logger.debug(f"Close history count: {len(position.close_history)}")

            # Validar datos de la posición
            validation = self.validation_service.validate_position_data(position)
            if validation['has_issues']:
                self._logger.info(f"Position data issues: {validation['issues']}")

            def _safe_decimal(value: Union[str, Decimal, float, int]) -> Decimal:
                try:
                    if value is None:
                        return Decimal('0')
                    return Decimal(str(value))
                except (InvalidOperation, ValueError, TypeError):
                    self._logger.warning(f"Valor decimal inválido para conversión: {value}, usando 0")
                    return Decimal('0')

            # Obtener precio del SOL en USD
            sol_price_usd = await self._get_sol_price_usd()

            # Calcular métricas usando el servicio de cálculo de posición
            total_closed_sol, total_closed_tokens, _ = self.position_calculation_service.calculate_total_closed_amounts(position)

            # Calcular P&L total usando las claves correctas con manejo de errores
            total_pnl_sol = Decimal('0')
            total_pnl_usd = Decimal('0')
            total_pnl_sol_acc_token = Decimal('0')
            total_pnl_usd_acc_token = Decimal('0')
            total_pnl_sol_acc_total = Decimal('0')
            total_pnl_usd_acc_total = Decimal('0')

            # Usar método robusto de P&L
            pnl_data = await self._calculate_pnl_and_register_trader_stats(position)

            total_pnl_sol = Decimal(pnl_data['pnl_sol'])
            total_pnl_usd = Decimal(pnl_data['pnl_usd'])
            total_pnl_sol_with_costs = Decimal(pnl_data['pnl_sol_with_costs'])
            total_pnl_usd_with_costs = Decimal(pnl_data['pnl_usd_with_costs'])

            total_pnl_sol_acc_token = Decimal(pnl_data['pnl_sol_acc_token'])
            total_pnl_usd_acc_token = Decimal(pnl_data['pnl_usd_acc_token'])
            total_pnl_sol_with_costs_acc_token = Decimal(pnl_data['pnl_sol_with_costs_acc_token'])
            total_pnl_usd_with_costs_acc_token = Decimal(pnl_data['pnl_usd_with_costs_acc_token'])

            total_pnl_sol_acc_total = Decimal(pnl_data['pnl_sol_acc_total'])
            total_pnl_usd_acc_total = Decimal(pnl_data['pnl_usd_acc_total'])
            total_pnl_sol_with_costs_acc_total = Decimal(pnl_data['pnl_sol_with_costs_acc_total'])
            total_pnl_usd_with_costs_acc_total = Decimal(pnl_data['pnl_usd_with_costs_acc_total'])

            total_volume_sol_open_token = _safe_decimal(pnl_data.get('total_volume_sol_open_token', '0'))
            total_volume_sol_closed_token = _safe_decimal(pnl_data.get('total_volume_sol_closed_token', '0'))
            token_base_amount = total_volume_sol_open_token if total_volume_sol_open_token != Decimal('0') else total_volume_sol_closed_token

            total_volume_sol_open_total = _safe_decimal(pnl_data.get('total_volume_sol_open_total', '0'))
            total_volume_sol_closed_total = _safe_decimal(pnl_data.get('total_volume_sol_closed_total', '0'))
            total_base_amount = total_volume_sol_open_total if total_volume_sol_open_total != Decimal('0') else total_volume_sol_closed_total

            pnl_acc_token_percentage = self._calculate_pnl_percentage(total_pnl_sol_acc_token, token_base_amount)
            pnl_with_costs_acc_token_percentage = self._calculate_pnl_percentage(total_pnl_sol_with_costs_acc_token, token_base_amount)

            pnl_acc_total_percentage = self._calculate_pnl_percentage(total_pnl_sol_acc_total, total_base_amount)
            pnl_with_costs_acc_total_percentage = self._calculate_pnl_percentage(total_pnl_sol_with_costs_acc_total, total_base_amount)

            # Obtener wallet del trader
            trader_wallet = position.trader_wallet
            original_amount = position.amount_sol_executed
            original_amount_tokens = position.amount_tokens_executed

            original_amount_usd = float(original_amount or "0.0") * float(sol_price_usd or "0.0")
            total_closed_sol_usd = float(total_closed_sol or "0.0") * float(sol_price_usd or "0.0")

            # Calcular porcentajes de P&L
            original_amount_decimal = Decimal(original_amount or "0.0")
            pnl_percentage = self._calculate_pnl_percentage(total_pnl_sol, original_amount_decimal)
            pnl_with_costs_percentage = self._calculate_pnl_percentage(total_pnl_sol_with_costs, original_amount_decimal)

            # Preparar indicadores de P&L
            pnl_indicator = '🟢' if total_pnl_sol > 0 else '🔴'
            pnl_with_costs_indicator = '🟢' if total_pnl_sol_with_costs > 0 else '🔴'
            pnl_acc_token_indicator = '🟢' if total_pnl_sol_acc_token > 0 else '🔴'
            pnl_with_costs_acc_token_indicator = '🟢' if total_pnl_sol_with_costs_acc_token > 0 else '🔴'
            pnl_acc_total_indicator = '🟢' if total_pnl_sol_acc_total > 0 else '🔴'
            pnl_with_costs_acc_total_indicator = '🟢' if total_pnl_sol_with_costs_acc_total > 0 else '🔴'

            # Verificar si fue liquidación por timeout
            is_timeout, timeout_info = self._is_timeout_liquidation(position)
            timeout_header = "🔴 <b>Position Closed</b>"
            if is_timeout:
                timeout_header = "⏱️ <b>Position Closed (Timeout Liquidation)</b>"
            timeout_section = ""
            if is_timeout and timeout_info:
                timeout_section = f"⏱️ <b>Timeout Info</b>\n{'─'*12}\n{timeout_info}\n\n"

            message = (
                f"{timeout_header}\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address']}\n\n"

                f"{timeout_section}"
                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                f"🔗 <b>Address:</b> {trader_wallet}\n\n"

                f"💰 <b>Trade Details</b>\n"
                f"{'─'*12}\n"
                f"🔑 <b>ID Position:</b> {position.id}\n"
                f"📥 <b>Sent SOL:</b> {self._format_amount(original_amount)} SOL ({self._format_amount(original_amount_usd)} USD)\n"
                f"📤 <b>Received SOL:</b> {self._format_amount(total_closed_sol)} SOL ({self._format_amount(total_closed_sol_usd)} USD)\n"
                f"🪙 <b>Received Tokens:</b> {self._format_amount(original_amount_tokens)} Tokens\n"
                f"🪙 <b>Sent Tokens:</b> {self._format_amount(total_closed_tokens)} Tokens\n\n"

                f"📈 <b>P&L Without Costs</b>\n"
                f"{'─'*12}\n"
                f"{pnl_indicator} <b>SOL:</b> {self._format_amount(total_pnl_sol)} SOL\n"
                f"{pnl_indicator} <b>USD:</b> {self._format_amount(total_pnl_usd)} USD\n"
                f"{pnl_indicator} <b>%:</b> {pnl_percentage}%\n\n"

                f"💹 <b>P&L With Costs</b>\n"
                f"{'─'*12}\n"
                f"{pnl_with_costs_indicator} <b>SOL:</b> {self._format_amount(total_pnl_sol_with_costs)} SOL\n"
                f"{pnl_with_costs_indicator} <b>USD:</b> {self._format_amount(total_pnl_usd_with_costs)} USD\n"
                f"{pnl_with_costs_indicator} <b>%:</b> {pnl_with_costs_percentage}%\n\n"

                f"📊 <b>Accumulated P&L (This Token)</b>\n"
                f"{'─'*12}\n"
                f"{pnl_acc_token_indicator} <b>Without Costs:</b> {self._format_amount(total_pnl_sol_acc_token)} SOL ({self._format_amount(total_pnl_usd_acc_token)} USD)\n"
                f"{pnl_acc_token_indicator} <b>%:</b> {pnl_acc_token_percentage}%\n"
                f"{pnl_with_costs_acc_token_indicator} <b>With Costs:</b> {self._format_amount(total_pnl_sol_with_costs_acc_token)} SOL ({self._format_amount(total_pnl_usd_with_costs_acc_token)} USD)\n"
                f"{pnl_with_costs_acc_token_indicator} <b>%:</b> {pnl_with_costs_acc_token_percentage}%\n\n"

                f"📊 <b>Accumulated P&L (Total Trader)</b>\n"
                f"{'─'*12}\n"
                f"{pnl_acc_total_indicator} <b>Without Costs:</b> {self._format_amount(total_pnl_sol_acc_total)} SOL ({self._format_amount(total_pnl_usd_acc_total)} USD)\n"
                f"{pnl_acc_total_indicator} <b>%:</b> {pnl_acc_total_percentage}%\n"
                f"{pnl_with_costs_acc_total_indicator} <b>With Costs:</b> {self._format_amount(total_pnl_sol_with_costs_acc_total)} SOL ({self._format_amount(total_pnl_usd_with_costs_acc_total)} USD)\n"
                f"{pnl_with_costs_acc_total_indicator} <b>%:</b> {pnl_with_costs_acc_total_percentage}%\n\n"

                f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # Añadir información de cierres múltiples si aplica
            if len(position.close_history) > 1:
                message += f"\n📝 Closed in {len(position.close_history)} transactions"

            if self.notification_manager:
                await self.notification_manager.notify(message, "success")
                self._logger.debug(f"Notificación de posición cerrada enviada: {position.id}")

            # Almacenar PNL en la base de datos
            await self._store_pnl(position, pnl_data)

        except Exception as e:
            self.stats['error_notifications'] += 1
            self._logger.error(f"Error en notificación de posición cerrada: {e}")

    async def _notify_position_failed(self, position: OpenPosition, token_info: Dict[str, str], trader_info: Dict[str, str]) -> None:
        """Notifica fallo de posición"""
        try:
            self._logger.debug(f"Enviando notificación de posición fallida: {position.id}")

            trader_wallet = position.trader_wallet
            amount_sol = position.amount_sol_executed
            amount_tokens = position.amount_tokens_executed
            error_message = position.message_error

            sol_price_usd = await self._get_sol_price_usd()
            amount_sol_usd = float(amount_sol or "0.0") * float(sol_price_usd or "0.0")

            # Verificar si fue fallo por timeout
            is_timeout, timeout_info = self._is_timeout_liquidation(position)
            failed_header = "❌ <b>Trade Opening Failed</b>"
            if is_timeout:
                failed_header = "⏱️ <b>Position Failed (Timeout Liquidation)</b>"
            timeout_section = ""
            if is_timeout and timeout_info:
                timeout_section = f"⏱️ <b>Timeout Info</b>\n{'─'*12}\n{timeout_info}\n\n"

            message = (
                f"{failed_header}\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address']}\n\n"

                f"{timeout_section}"
                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                f"🔗 <b>Address:</b> {trader_wallet}\n\n"

                f"💰 <b>Trade Details</b>\n"
                f"{'─'*12}\n"
                f"🔑 <b>ID Position:</b> {position.id}\n"
                f"🔗 <b>Signature:</b> {position.execution_signature or 'N/A'}\n"
                f"📥 <b>Amount:</b> {self._format_amount(amount_sol)} SOL ({self._format_amount(amount_sol_usd)} USD)\n"
                f"🪙 <b>Tokens:</b> {self._format_amount(amount_tokens)}\n"
                f"⚠️ <b>Error:</b> {error_message}\n\n"

                f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            if self.notification_manager:
                await self.notification_manager.notify(message, "error")
                self._logger.debug(f"Notificación de posición fallida enviada: {position.id}")

        except Exception as e:
            self.stats['error_notifications'] += 1
            self._logger.error(f"Error en notificación de posición fallida: {e}")

    async def _notify_partial_close_success(self, close_position: Union[ClosePosition, SubClosePosition], token_info: Dict[str, str], trader_info: Dict[str, str]) -> None:
        """Notifica éxito de cierre parcial"""
        try:
            position_id = close_position.id
            self._logger.debug(f"Enviando notificación de cierre parcial exitoso: {position_id}")

            # Extraer información de la posición
            trader_wallet = close_position.trader_wallet
            amount_sol = close_position.amount_sol_executed
            amount_tokens = close_position.amount_tokens_executed
            executed_at = close_position.created_at
            signature = close_position.signature

            sol_price_usd = await self._get_sol_price_usd()
            amount_sol_usd = float(amount_sol or "0.0") * float(sol_price_usd or "0.0")
            self._logger.debug(f"Amount SOL USD: {amount_sol_usd}")

            # Calcular P&L para el cierre parcial
            pnl_data = await self._calculate_pnl(close_position, sol_price_usd)
            total_pnl_sol = Decimal(pnl_data['pnl_sol'])
            total_pnl_usd = Decimal(pnl_data['pnl_usd'])
            total_pnl_sol_with_costs = Decimal(pnl_data['pnl_sol_with_costs'])
            total_pnl_usd_with_costs = Decimal(pnl_data['pnl_usd_with_costs'])

            # Calcular monto inicial proporcional para el porcentaje de P&L
            # El monto inicial es aproximadamente el monto recibido menos el P&L
            amount_sol_decimal = Decimal(amount_sol or "0.0")
            initial_amount_proportional = amount_sol_decimal - total_pnl_sol

            # Calcular porcentajes de P&L
            pnl_percentage = self._calculate_pnl_percentage(total_pnl_sol, initial_amount_proportional)
            pnl_with_costs_percentage = self._calculate_pnl_percentage(total_pnl_sol_with_costs, initial_amount_proportional)

            # Preparar indicadores de P&L
            pnl_indicator = '🟢' if total_pnl_sol > 0 else '🔴'
            pnl_with_costs_indicator = '🟢' if total_pnl_sol_with_costs > 0 else '🔴'

            if not close_position.is_liquidation:
                trader_info_message = f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                trader_info_message += f"🔗 <b>Address:</b> {trader_wallet}\n\n"
            else:
                trader_info_message = "⚡ Automatic liquidation by the system\n\n"

            # Obtener información de porcentajes
            percentage_info = await self._get_percentage_info(close_position)

            message = (
                f"🟡 <b>Partial Close Success</b>\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address']}\n\n"

                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                + trader_info_message +

                f"💰 <b>Close Details</b>\n"
                f"{'─'*12}\n"
                f"🔑 <b>ID Position:</b> {position_id}\n"
                f"🔗 <b>Signature:</b> {signature or 'N/A'}\n"
                f"📤 <b>Amount:</b> {self._format_amount(amount_sol)} SOL ({self._format_amount(amount_sol_usd)} USD)\n"
                f"🪙 <b>Tokens:</b> {self._format_amount(amount_tokens)}\n\n"

                f"📈 <b>P&L Without Costs</b>\n"
                f"{'─'*12}\n"
                f"{pnl_indicator} <b>SOL:</b> {self._format_amount(total_pnl_sol)} SOL\n"
                f"{pnl_indicator} <b>USD:</b> {self._format_amount(total_pnl_usd)} USD\n"
                f"{pnl_indicator} <b>%:</b> {pnl_percentage}%\n\n"

                f"💹 <b>P&L With Costs</b>\n"
                f"{'─'*12}\n"
                f"{pnl_with_costs_indicator} <b>SOL:</b> {self._format_amount(total_pnl_sol_with_costs)} SOL\n"
                f"{pnl_with_costs_indicator} <b>USD:</b> {self._format_amount(total_pnl_usd_with_costs)} USD\n"
                f"{pnl_with_costs_indicator} <b>%:</b> {pnl_with_costs_percentage}%\n\n"

                f"{percentage_info}"
                f"⏰ <b>Time:</b> {executed_at.strftime('%Y-%m-%d %H:%M:%S') if executed_at else 'N/A'}"
            )

            if self.notification_manager:
                await self.notification_manager.notify(message, "info")
                self._logger.debug(f"Notificación de cierre parcial exitoso enviada: {position_id}")

        except Exception as e:
            self.stats['error_notifications'] += 1
            self._logger.error(f"Error en notificación de cierre parcial exitoso: {e}")

    async def _notify_partial_close_failed(self, close_position: Union[ClosePosition, SubClosePosition], token_info: Dict[str, str], trader_info: Dict[str, str]) -> None:
        """Notifica fallo de cierre parcial"""
        try:
            position_id = close_position.id
            self._logger.debug(f"Enviando notificación de cierre parcial fallido: {position_id}")

            # Extraer información de la posición
            trader_wallet = close_position.trader_wallet
            amount_sol = close_position.amount_sol_executed
            amount_tokens = close_position.amount_tokens_executed
            error_message = close_position.message_error
            executed_at = close_position.created_at
            signature = close_position.signature

            sol_price_usd = await self._get_sol_price_usd()
            amount_sol_usd = float(amount_sol or "0.0") * float(sol_price_usd or "0.0")

            # Calcular P&L para el cierre parcial fallido (si aplica)
            pnl_data = await self._calculate_pnl(close_position, sol_price_usd)
            total_pnl_sol = Decimal(pnl_data['pnl_sol'])
            total_pnl_usd = Decimal(pnl_data['pnl_usd'])
            total_pnl_sol_with_costs = Decimal(pnl_data['pnl_sol_with_costs'])
            total_pnl_usd_with_costs = Decimal(pnl_data['pnl_usd_with_costs'])

            # Preparar indicadores de P&L
            pnl_indicator = '🟢' if total_pnl_sol > 0 else '🔴'
            pnl_with_costs_indicator = '🟢' if total_pnl_sol_with_costs > 0 else '🔴'

            if not close_position.is_liquidation:
                trader_info_message = f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                trader_info_message += f"🔗 <b>Address:</b> {trader_wallet}\n\n"
            else:
                trader_info_message = "⚡ Automatic liquidation by the system\n\n"

            message = (
                f"❌ <b>Partial Close Failed</b>\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address']}\n\n"

                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                + trader_info_message +

                f"💰 <b>Close Details</b>\n"
                f"{'─'*12}\n"
                f"🔑 <b>ID Position:</b> {position_id}\n"
                f"🔗 <b>Signature:</b> {signature or 'N/A'}\n"
                f"📤 <b>Amount:</b> {self._format_amount(amount_sol)} SOL ({self._format_amount(amount_sol_usd)} USD)\n"
                f"🪙 <b>Tokens:</b> {self._format_amount(amount_tokens)}\n"
                f"⚠️ <b>Error:</b> {error_message}\n\n"

                f"📈 <b>P&L Without Costs</b>\n"
                f"{'─'*12}\n"
                f"{pnl_indicator} <b>SOL:</b> {self._format_amount(total_pnl_sol)} SOL\n"
                f"{pnl_indicator} <b>USD:</b> {self._format_amount(total_pnl_usd)} USD\n\n"

                f"💹 <b>P&L With Costs</b>\n"
                f"{'─'*12}\n"
                f"{pnl_with_costs_indicator} <b>SOL:</b> {self._format_amount(total_pnl_sol_with_costs)} SOL\n"
                f"{pnl_with_costs_indicator} <b>USD:</b> {self._format_amount(total_pnl_usd_with_costs)} USD\n\n"

                f"⏰ <b>Time:</b> {executed_at.strftime('%Y-%m-%d %H:%M:%S') if executed_at else 'N/A'}"
            )

            if self.notification_manager:
                await self.notification_manager.notify(message, "error")
                self._logger.debug(f"Notificación de cierre parcial fallido enviada: {position_id}")

        except Exception as e:
            self.stats['error_notifications'] += 1
            self._logger.error(f"Error en notificación de cierre parcial fallido: {e}")

    def _format_amount(self, value: Union[str, Decimal, float, int]) -> str:
        """
        Formatea un valor numérico para mostrar en notificaciones.
        Maneja casos de error de conversión decimal de forma segura.
        """
        try:
            # Si el valor es None o vacío, retornar '0'
            if value is None or value == '':
                return '0'

            # Si ya es Decimal, usarlo directamente
            if isinstance(value, Decimal):
                formatted_value = value
            else:
                # Convertir a string y limpiar caracteres problemáticos
                str_value = str(value).strip()

                # Remover caracteres no válidos para Decimal
                # Solo permitir dígitos, punto decimal, signo y 'e' para notación científica
                cleaned_value = re.sub(r'[^0-9.-eE]', '', str_value)

                # Si después de limpiar está vacío, retornar '0'
                if not cleaned_value or cleaned_value == '.' or cleaned_value == '-':
                    return '0'

                # Intentar convertir a Decimal
                try:
                    formatted_value = Decimal(cleaned_value)
                except (ValueError, InvalidOperation):
                    # Si falla la conversión, intentar con el valor original como string
                    try:
                        formatted_value = Decimal(str_value)
                    except (ValueError, InvalidOperation):
                        # Si todo falla, retornar '0'
                        self._logger.warning(f"No se pudo convertir valor '{value}' a Decimal, usando '0'")
                        return '0'

            # Formatear el valor
            formatted = format(formatted_value.quantize(Decimal('0.0000000000000001'), rounding=ROUND_DOWN), "f")
            resultado = formatted.rstrip('0').rstrip('.') if formatted else '0'
            return resultado

        except Exception as e:
            self._logger.error(f"Error formateando valor '{value}': {e}")
            return '0'

    def _calculate_pnl_percentage_decimal(self, pnl_sol: Decimal, initial_amount_sol: Decimal) -> Optional[Decimal]:
        """Calcula el porcentaje de P&L como Decimal (método base).
        
        Args:
            pnl_sol: P&L en SOL
            initial_amount_sol: Monto inicial invertido en SOL
            
        Returns:
            Decimal con el porcentaje de P&L o None si no se puede calcular
        """
        try:
            if initial_amount_sol == Decimal('0') or initial_amount_sol is None:
                return None

            pnl_percent = (pnl_sol / initial_amount_sol) * Decimal('100.0')
            return pnl_percent
        except Exception as e:
            self._logger.error(f"Error calculando porcentaje de P&L: {e}")
            return None

    def _calculate_pnl_percentage(self, pnl_sol: Decimal, initial_amount_sol: Decimal) -> str:
        """
        Calcula el porcentaje de P&L basado en el monto inicial invertido.
        Usa _calculate_pnl_percentage_decimal internamente y formatea el resultado como string.
        
        Args:
            pnl_sol: P&L en SOL
            initial_amount_sol: Monto inicial invertido en SOL
            
        Returns:
            String formateado con el porcentaje de P&L
        """
        try:
            pnl_percent = self._calculate_pnl_percentage_decimal(pnl_sol, initial_amount_sol)

            if pnl_percent is None:
                return '0.00'

            pnl_percent_str = format(pnl_percent.quantize(Decimal('0.01'), rounding=ROUND_DOWN).normalize(), "f")
            return pnl_percent_str.rstrip('0').rstrip('.') if pnl_percent_str else '0.00'
        except Exception as e:
            self._logger.error(f"Error calculando porcentaje de P&L: {e}")
            return '0.00'

    async def _get_percentage_info(self, position: Union[OpenPosition, ClosePosition, SubClosePosition]) -> str:
        try:
            if isinstance(position, SubClosePosition):
                trader_balance_used = position.close_position.get_metadata("trader_balance_used")
                own_balance_used = position.close_position.get_metadata("own_balance_used")
                original_percentage = position.close_position.get_metadata("original_percentage")
                amount_sol = position.close_position.amount_sol_executed
            else:
                trader_balance_used = position.get_metadata("trader_balance_used")
                own_balance_used = position.get_metadata("own_balance_used")
                original_percentage = position.get_metadata("original_percentage")
                amount_sol = position.amount_sol_executed

            if not trader_balance_used or not own_balance_used or not original_percentage:
                self._logger.debug("Trader balance, own balance or original percentage is None")
                return ""

            sol_price_usd = await self._get_sol_price_usd()

            trader_balance_used_usd = float(trader_balance_used or "0.0") * float(sol_price_usd or "0.0")
            own_balance_used_usd = float(own_balance_used or "0.0") * float(sol_price_usd or "0.0")

            applied_percentage = (
                (Decimal(amount_sol or "0.0") / Decimal(own_balance_used or "0.0")) * Decimal("100")
            ).quantize(Decimal("0.000001"), rounding=ROUND_DOWN).normalize()

            original_percentage = (
                Decimal(original_percentage or "0.0") * Decimal("100")
            ).quantize(Decimal("0.000001"), rounding=ROUND_DOWN).normalize()

            return (
                f"📈 <b>Percentage Info</b>\n"
                f"{'─'*12}\n"
                f"🎯 <b>Trader balance:</b> {float(trader_balance_used or "0.0"):.6f} SOL ({trader_balance_used_usd:.2f} USD)\n"
                f"💼 <b>Own balance:</b> {float(own_balance_used or "0.0"):.6f} SOL ({own_balance_used_usd:.2f} USD)\n"
                f"🔢 <b>Original pct:</b> {original_percentage}%\n"
                f"⚡ <b>Applied pct:</b> {format(applied_percentage, "f")}%\n\n"
            )
        except Exception as e:
            self._logger.error(f"Error en notificación de porcentaje: {e}")
            return ""

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del callback"""
        return {
            **self.stats,
            'success_rate': (
                (self.stats['success_notifications'] / self.stats['total_notifications'] * 100) 
                if self.stats['total_notifications'] > 0 else 0
            ),
            'error_rate': (
                (self.stats['error_notifications'] / self.stats['total_notifications'] * 100) 
                if self.stats['total_notifications'] > 0 else 0
            )
        }

    def reset_stats(self) -> None:
        """Resetea las estadísticas"""
        self.stats = {
            'total_notifications': 0,
            'success_notifications': 0,
            'failed_notifications': 0,
            'error_notifications': 0,
            'last_notification_time': None
        }
        self._logger.debug("Estadísticas del callback reseteadas")

    async def _store_pnl(self, position: OpenPosition, pnl_data: Dict[str, str]) -> None:
        """Almacena el PNL realizado en la base de datos.
        
        Args:
            position: Posición cerrada con PNL calculado
            pnl_data: Diccionario con los datos de PNL calculados
        """
        try:
            if not self.pnl_repository:
                self._logger.debug("PNLRepository no disponible, saltando almacenamiento de PNL")
                return

            # Convertir valores de PNL a Decimal
            pnl_without_cost_sol = Decimal(pnl_data.get('pnl_sol', '0.0'))
            pnl_without_cost_pct_sol = self._calculate_pnl_percentage_decimal(
                pnl_without_cost_sol,
                Decimal(position.amount_sol_executed or '0.0')
            )
            pnl_with_cost_sol = Decimal(pnl_data.get('pnl_sol_with_costs', '0.0'))
            pnl_with_cost_pct_sol = self._calculate_pnl_percentage_decimal(
                pnl_with_cost_sol,
                Decimal(position.amount_sol_executed or '0.0')
            )

            # Obtener volumen de la posición (monto inicial invertido)
            volume_sol = Decimal(position.amount_sol_executed or '0.0')

            # Convertir position.id (string UUID) a UUID
            open_positions_id = uuid.UUID(position.id)

            # Obtener wallet_address y mint_address
            wallet_address = position.trader_wallet
            mint_address = position.token_address

            if not wallet_address or not mint_address:
                self._logger.warning(
                    f"Faltan datos requeridos para almacenar PNL: "
                    f"wallet_address={wallet_address}, mint_address={mint_address}"
                )
                return

            # Almacenar PNL usando el repositorio
            await self.pnl_repository.record_realized_pnl(
                open_positions_id=open_positions_id,
                pnl_without_cost_sol=pnl_without_cost_sol,
                pnl_without_cost_pct_sol=pnl_without_cost_pct_sol,
                pnl_with_cost_sol=pnl_with_cost_sol,
                pnl_with_cost_pct_sol=pnl_with_cost_pct_sol,
                runs_id=self.run_id,
                wallet_address=wallet_address,
                mint_address=mint_address,
                volume_sol=volume_sol,
            )

            self._logger.debug(
                f"PNL almacenado exitosamente para posición {position.id}: "
                f"runs_id={self.run_id}, trader={wallet_address[:8]}..., mint={mint_address[:8]}..., volume={volume_sol}"
            )

        except Exception as e:
            self._logger.error(f"Error almacenando PNL para posición {position.id}: {e}", exc_info=True)
