# -*- coding: utf-8 -*-
"""
Callback especializado para notificaciones de posiciones en Copy Trading.
Integra con NotificationManager para procesar diferentes tipos de eventos.
"""
import re
from typing import Optional, Union, Dict, Any
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from cachetools import TTLCache

from logging_system import AppLogger
from ..notifications import NotificationManager
from ..data_management import TradingDataFetcher, TokenTraderManager
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


class PositionNotificationCallback:
    """
    Callback especializado para notificaciones de posiciones.
    Procesa diferentes tipos de eventos y envía notificaciones apropiadas.
    """

    def __init__(self, 
                    notification_manager: Optional[NotificationManager] = None,
                    trading_data_fetcher: Optional[TradingDataFetcher] = None,
                    token_trader_manager: Optional[TokenTraderManager] = None):
        """
        Inicializa el callback de notificaciones.
        
        Args:
            notification_manager: Manager de notificaciones
            trading_data_fetcher: Fetcher de datos de trading
            token_trader_manager: Manager de traders y tokens
        """
        self.notification_manager = notification_manager
        self.trading_data_fetcher = trading_data_fetcher
        self.token_trader_manager = token_trader_manager
        self._logger = AppLogger(self.__class__.__name__)

        # Instanciar servicios
        self.validation_service = PositionValidationService()
        self.pnl_calculation_service = PnLCalculationService()
        self.position_calculation_service = PositionCalculationService()

        # Cache de precios de SOL en USD
        self.sol_price_usd_cache: TTLCache = TTLCache(maxsize=1, ttl=60)

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
            token_info = position.metadata.get('token_info')
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

    async def _extract_trader_info(self, position: Union[OpenPosition, ClosePosition, SubClosePosition]) -> Dict[str, str]:
        """
        Extrae información del trader desde metadata o usa fallbacks.
        """
        trader_nickname = position.metadata.get("trader_nickname")
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
        if not self.trading_data_fetcher:
            self._logger.debug("TradingDataFetcher no disponible para obtener precio SOL/USD")
            return None

        if "sol_price_usd" not in self.sol_price_usd_cache:
            self._logger.debug("Obteniendo precio SOL/USD del cache")
            self.sol_price_usd_cache["sol_price_usd"] = await self.trading_data_fetcher.get_sol_price_usd()

        return self.sol_price_usd_cache.get("sol_price_usd")

    async def _calculate_pnl_and_register_trader_stats(self, position: OpenPosition) -> Dict[str, str]:
        """Calcula el P&L de una posición

        Args:
            position: Posición a calcular el P&L

        Returns:
            Dict con el P&L en SOL, USD, P&L acumulado en SOL, USD
        """
        position_id = position.id
        self._logger.debug(f"Iniciando cálculo de P&L para la posición: {position_id}")

        pnl_sol = "0.0"
        pnl_usd = "0.0"
        pnl_sol_with_costs = "0.0"
        pnl_usd_with_costs = "0.0"

        pnl_sol_acc_token = "0.0"
        pnl_usd_acc_token = "0.0"
        pnl_sol_with_costs_acc_token = "0.0"
        pnl_usd_with_costs_acc_token = "0.0"

        pnl_sol_acc_total = "0.0"
        pnl_usd_acc_total = "0.0"
        pnl_sol_with_costs_acc_total = "0.0"
        pnl_usd_with_costs_acc_total = "0.0"

        sol_price_usd = await self._get_sol_price_usd()
        self._logger.debug(f"Precio SOL/USD obtenido: {sol_price_usd}")

        if sol_price_usd:
            pnl_sol, pnl_usd, pnl_sol_with_costs, pnl_usd_with_costs = self.pnl_calculation_service.calculate_realized_pnl_with_costs_breakdown(position, sol_price_usd)
            self._logger.debug(f"P&L calculado: pnl_sol={pnl_sol}, pnl_usd={pnl_usd}, pnl_sol_with_costs={pnl_sol_with_costs}, pnl_usd_with_costs={pnl_usd_with_costs}")

            # Agregar P&L a la posición
            position.add_metadata('pnl_sol', pnl_sol)
            position.add_metadata('pnl_usd', pnl_usd)
            position.add_metadata('pnl_sol_with_costs', pnl_sol_with_costs)
            position.add_metadata('pnl_usd_with_costs', pnl_usd_with_costs)

            if self.token_trader_manager:
                self._logger.debug(f"Registrando P&L en token_trader_manager para wallet: {position.trader_wallet[:8]}... y token: {position.token_address[:8]}...")
                # Usar el nuevo método que actualiza TraderStats y TraderTokenStats simultáneamente
                await self.token_trader_manager.register_trader_token_pnl(
                    position.trader_wallet, 
                    position.token_address, 
                    pnl_sol, 
                    pnl_sol_with_costs
                )

        if self.token_trader_manager:
            # Obtener estadísticas específicas del trader para este token
            trader_token_stats = await self.token_trader_manager.get_trader_token_stats(position.trader_wallet, position.token_address)
            self._logger.debug(f"Trader token stats obtenidas para {position.token_address[:8]}...")

            # Calcular P&L acumulado específico por token
            pnl_sol_acc_token = trader_token_stats.total_pnl_sol
            pnl_usd_acc_token = format(Decimal(pnl_sol_acc_token) * Decimal(sol_price_usd) if sol_price_usd else "0.0", "f")
            pnl_sol_with_costs_acc_token = trader_token_stats.total_pnl_sol_with_costs
            pnl_usd_with_costs_acc_token = format(Decimal(pnl_sol_with_costs_acc_token) * Decimal(sol_price_usd) if sol_price_usd else "0.0", "f")

            self._logger.debug(f"P&L acumulado por token: pnl_sol_acc_token={pnl_sol_acc_token}, pnl_usd_acc={pnl_usd_acc_token}")

            # Agregar metadatos específicos por token
            position.add_metadata('pnl_sol_acc_token', pnl_sol_acc_token)
            position.add_metadata('pnl_usd_acc_token', pnl_usd_acc_token)
            position.add_metadata('pnl_sol_with_costs_acc_token', pnl_sol_with_costs_acc_token)
            position.add_metadata('pnl_usd_with_costs_acc_token', pnl_usd_with_costs_acc_token)

            # También agregar estadísticas generales del trader para referencia
            trader_stats = await self.token_trader_manager.get_trader_stats(position.trader_wallet)
            pnl_sol_acc_total = trader_stats.total_pnl_sol
            pnl_usd_acc_total = format(Decimal(pnl_sol_acc_total) * Decimal(sol_price_usd) if sol_price_usd else "0.0", "f")
            pnl_sol_with_costs_acc_total = trader_stats.total_pnl_sol_with_costs
            pnl_usd_with_costs_acc_total = format(Decimal(pnl_sol_with_costs_acc_total) * Decimal(sol_price_usd) if sol_price_usd else "0.0", "f")

            position.add_metadata('pnl_sol_acc_total', pnl_sol_acc_total)
            position.add_metadata('pnl_usd_acc_total', pnl_usd_acc_total)
            position.add_metadata('pnl_sol_with_costs_acc_total', pnl_sol_with_costs_acc_total)
            position.add_metadata('pnl_usd_with_costs_acc_total', pnl_usd_with_costs_acc_total)

        resultado = {
            "pnl_sol": pnl_sol,
            "pnl_usd": pnl_usd,
            "pnl_sol_with_costs": pnl_sol_with_costs,
            "pnl_usd_with_costs": pnl_usd_with_costs,
            "pnl_sol_acc_token": pnl_sol_acc_token,
            "pnl_usd_acc_token": pnl_usd_acc_token,
            "pnl_sol_with_costs_acc_token": pnl_sol_with_costs_acc_token,
            "pnl_usd_with_costs_acc_token": pnl_usd_with_costs_acc_token,
            "pnl_sol_acc_total": pnl_sol_acc_total,
            "pnl_usd_acc_total": pnl_usd_acc_total,
            "pnl_sol_with_costs_acc_total": pnl_sol_with_costs_acc_total,
            "pnl_usd_with_costs_acc_total": pnl_usd_with_costs_acc_total
        }
        self._logger.debug(f"Cálculo de P&L completado para posición: {position_id}")
        return resultado

    async def _notify_position_opened(self, position: OpenPosition, token_info: Dict[str, str], trader_info: Dict[str, str]) -> None:
        """Notifica apertura exitosa de posición"""
        try:
            self._logger.debug(f"Enviando notificación de posición abierta: {position.id}")

            trader_wallet = position.trader_wallet
            amount_sol = position.amount_sol_executed
            amount_tokens = position.amount_tokens_executed
            entry_price = position.entry_price

            self._logger.debug(f"amount_sol: {amount_sol}, amount_tokens: {amount_tokens}, entry_price: {entry_price}, total_cost_sol: {position.total_cost_sol}, fee_sol: {position.fee_sol}")

            message = (
                f"🟢 <b>Position Opened</b>\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address'][:8]}...\n\n"

                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                f"🔗 <b>Address:</b> {trader_wallet[:8]}...\n\n"

                f"💰 <b>Trade Details</b>\n"
                f"{'─'*12}\n"
                f"📥 <b>Amount:</b> {self._format_amount(amount_sol)} SOL\n"
                f"🪙 <b>Tokens:</b> {self._format_amount(amount_tokens)}\n"
                f"🧾 <b>Fee:</b> {self._format_amount(position.total_cost_sol)} SOL\n"
                f"📈 <b>Entry Price:</b> {self._format_amount(entry_price)} SOL\n\n"

                f"⏰ <b>Time:</b> {position.executed_at.strftime('%H:%M:%S') if position.executed_at else 'N/A'}"
            )

            if position.execution_signature:
                message += f"\n🔗 Signature: {position.execution_signature[:8]}..."

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
                self._logger.warning(f"Position data issues: {validation['issues']}")

            # Obtener precio del SOL en USD
            #sol_price_usd = await self._get_sol_price_usd()

            # Calcular métricas usando el servicio de cálculo de posición
            total_closed_sol, _ = self.position_calculation_service.calculate_total_closed_amounts(position)

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

            # Obtener wallet del trader
            trader_wallet = position.trader_wallet
            original_amount = position.amount_sol

            # Preparar indicadores de P&L
            pnl_indicator = '🟢' if total_pnl_sol >= 0 else '🔴'
            pnl_with_costs_indicator = '🟢' if total_pnl_sol_with_costs >= 0 else '🔴'
            pnl_acc_token_indicator = '🟢' if total_pnl_sol_acc_token >= 0 else '🔴'
            pnl_with_costs_acc_token_indicator = '🟢' if total_pnl_sol_with_costs_acc_token >= 0 else '🔴'
            pnl_acc_total_indicator = '🟢' if total_pnl_sol_acc_total >= 0 else '🔴'
            pnl_with_costs_acc_total_indicator = '🟢' if total_pnl_sol_with_costs_acc_total >= 0 else '🔴'

            message = (
                f"🔴 <b>Position Closed</b>\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address'][:8]}...\n\n"

                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                f"🔗 <b>Address:</b> {trader_wallet[:8]}...\n\n"

                f"💰 <b>Amount Details</b>\n"
                f"{'─'*12}\n"
                f"📥 <b>Original:</b> {self._format_amount(original_amount)} SOL\n"
                f"📤 <b>Received:</b> {self._format_amount(total_closed_sol)} SOL\n\n"

                f"📈 <b>P&L Without Costs</b>\n"
                f"{'─'*12}\n"
                f"{pnl_indicator} <b>SOL:</b> {self._format_amount(total_pnl_sol)} SOL\n"
                f"{pnl_indicator} <b>USD:</b> {self._format_amount(total_pnl_usd)} USD\n\n"

                f"💹 <b>P&L With Costs</b>\n"
                f"{'─'*12}\n"
                f"{pnl_with_costs_indicator} <b>SOL:</b> {self._format_amount(total_pnl_sol_with_costs)} SOL\n"
                f"{pnl_with_costs_indicator} <b>USD:</b> {self._format_amount(total_pnl_usd_with_costs)} USD\n\n"

                f"📊 <b>Accumulated P&L (This Token)</b>\n"
                f"{'─'*12}\n"
                f"{pnl_acc_token_indicator} <b>Without Costs:</b> {self._format_amount(total_pnl_sol_acc_token)} SOL ({self._format_amount(total_pnl_usd_acc_token)} USD)\n"
                f"{pnl_with_costs_acc_token_indicator} <b>With Costs:</b> {self._format_amount(total_pnl_sol_with_costs_acc_token)} SOL ({self._format_amount(total_pnl_usd_with_costs_acc_token)} USD)\n\n"

                f"📊 <b>Accumulated P&L (Total Trader)</b>\n"
                f"{'─'*12}\n"
                f"{pnl_acc_total_indicator} <b>Without Costs:</b> {self._format_amount(total_pnl_sol_acc_total)} SOL ({self._format_amount(total_pnl_usd_acc_total)} USD)\n"
                f"{pnl_with_costs_acc_total_indicator} <b>With Costs:</b> {self._format_amount(total_pnl_sol_with_costs_acc_total)} SOL ({self._format_amount(total_pnl_usd_with_costs_acc_total)} USD)\n\n"

                f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
            )

            # Añadir información de cierres múltiples si aplica
            if len(position.close_history) > 1:
                message += f"\n📝 Closed in {len(position.close_history)} transactions"

            if self.notification_manager:
                await self.notification_manager.notify(message, "success")
                self._logger.debug(f"Notificación de posición cerrada enviada: {position.id}")

        except Exception as e:
            self.stats['error_notifications'] += 1
            self._logger.error(f"Error en notificación de posición cerrada: {e}")

    async def _notify_position_failed(self, position: OpenPosition, token_info: Dict[str, str], trader_info: Dict[str, str]) -> None:
        """Notifica fallo de posición"""
        try:
            self._logger.debug(f"Enviando notificación de posición fallida: {position.id}")

            trader_wallet = position.trader_wallet
            amount_sol = position.amount_sol
            error_message = position.message_error

            message = (
                f"❌ <b>Trade Opening Failed</b>\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address'][:8]}...\n\n"

                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                f"🔗 <b>Address:</b> {trader_wallet[:8]}...\n\n"

                f"💰 <b>Trade Details</b>\n"
                f"{'─'*12}\n"
                f"📥 <b>Amount:</b> {self._format_amount(amount_sol)} SOL\n"
                f"⚠️ <b>Error:</b> {error_message}\n\n"

                f"⏰ <b>Time:</b> {datetime.now().strftime('%H:%M:%S')}"
            )

            if position.execution_signature:
                message += f"\n🔗 Signature: {position.execution_signature[:8]}..."

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

            message = (
                f"🟡 <b>Partial Close Success</b>\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address'][:8]}...\n\n"

                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                f"🔗 <b>Address:</b> {trader_wallet[:8]}...\n\n"

                f"💰 <b>Close Details</b>\n"
                f"{'─'*12}\n"
                f"📤 <b>Amount:</b> {self._format_amount(amount_sol)} SOL\n"
                f"🪙 <b>Tokens:</b> {self._format_amount(amount_tokens)}\n\n"

                f"⏰ <b>Time:</b> {executed_at.strftime('%H:%M:%S') if executed_at else 'N/A'}"
            )

            if signature:
                message += f"\n🔗 Signature: {signature[:8]}..."

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
            error_message = close_position.message_error
            executed_at = close_position.created_at
            signature = close_position.signature

            message = (
                f"❌ <b>Partial Close Failed</b>\n\n"
                f"📊 <b>Trade Summary</b>\n"
                f"{'─'*12}\n"
                f"💎 <b>Token:</b> {token_info['name']} ({token_info['symbol']})\n"
                f"🔗 <b>Address:</b> {token_info['address'][:8]}...\n\n"

                f"👤 <b>Trader Info</b>\n"
                f"{'─'*12}\n"
                f"🎭 <b>Nickname:</b> {trader_info['nickname']}\n"
                f"🔗 <b>Address:</b> {trader_wallet[:8]}...\n\n"

                f"💰 <b>Close Details</b>\n"
                f"{'─'*12}\n"
                f"📤 <b>Amount:</b> {self._format_amount(amount_sol)} SOL\n"
                f"⚠️ <b>Error:</b> {error_message}\n\n"

                f"⏰ <b>Time:</b> {executed_at.strftime('%H:%M:%S') if executed_at else 'N/A'}"
            )

            if signature:
                message += f"\n🔗 Signature: {signature[:8]}..."

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
