# -*- coding: utf-8 -*-
"""
Gestor central de notificaciones
"""
from typing import Dict, List, Optional
from .strategies.base_strategy import BaseNotificationStrategy


class NotificationManager:
    """Gestor central de notificaciones"""

    def __init__(self, strategies: List[BaseNotificationStrategy] = None, logger=None):
        """
        Inicializa el gestor de notificaciones
        
        Args:
            strategies: Lista opcional de estrategias de notificación
            logger: Logger opcional para registrar eventos
        """
        self._strategies: Dict[str, BaseNotificationStrategy] = {}
        self.logger = logger

        # Registrar estrategias iniciales
        if strategies:
            for strategy in strategies:
                self.add_strategy(strategy.__class__.__name__, strategy)

    def add_strategy(self, name: str, strategy: BaseNotificationStrategy) -> None:
        """Añade una estrategia de notificación"""
        self._strategies[name] = strategy
        if self.logger:
            self.logger.info(f"Estrategia de notificación añadida: {name}")

    def remove_strategy(self, name: str) -> None:
        """Elimina una estrategia de notificación"""
        if name in self._strategies:
            del self._strategies[name]
            if self.logger:
                self.logger.info(f"Estrategia de notificación eliminada: {name}")

    def get_strategy(self, name: str) -> Optional[BaseNotificationStrategy]:
        """Obtiene una estrategia por nombre"""
        return self._strategies.get(name)

    def get_all_strategies(self) -> List[BaseNotificationStrategy]:
        """Obtiene todas las estrategias registradas"""
        return list(self._strategies.values())

    async def notify(self, message: str, level: str = "info", **kwargs) -> None:
        """
        Envía una notificación a través de todas las estrategias registradas
        
        Args:
            message: Mensaje a enviar
            level: Nivel de la notificación (info, success, warning, error, critical)
            **kwargs: Argumentos adicionales para las estrategias
        """
        for strategy in self._strategies.values():
            try:
                await strategy.send_notification(message, level)
            except Exception as e:
                error_msg = f"Error al enviar notificación a través de {strategy.__class__.__name__}: {e}"
                if self.logger:
                    self.logger.error(error_msg)
                else:
                    print(error_msg)

    async def notify_trade(self, trade_data: dict) -> None:
        """
        Envía una notificación específica de trade
        
        Args:
            trade_data: Datos del trade a notificar
        """
        # Determinar el tipo de trade
        action = trade_data.get('action', trade_data.get('side', 'unknown')).upper()

        # Obtener información del token
        token_name = trade_data.get('token_name', 'Token Desconocido')
        token_symbol = trade_data.get('token_symbol', trade_data.get('symbol', trade_data.get('token_address', 'unknown')))
        token_address = trade_data.get('token_address', 'unknown')

        amount = trade_data.get('amount', 0)
        price = trade_data.get('price', 0)
        status = trade_data.get('status', 'executed')

        # Emojis según acción
        action_emoji = {
            'BUY': '🟢',
            'SELL': '🔴',
            'LONG': '📈',
            'SHORT': '📉',
            'CLOSE': '⭕',
            'unknown': '❓'
        }

        # Emojis según estado
        status_emoji = {
            'executed': '✅',
            'failed': '❌',
            'pending': '⏳',
            'cancelled': '🚫',
            'closed': '🔒'
        }

        # Formatear mensaje
        message = (
            f"{action_emoji.get(action, '❓')} Trade {action}\n"
            f"- Token: 💎 {token_name} ({token_symbol})\n"
            f"- Dirección: 🔗 {token_address[:8]}...\n"
            f"- Cantidad: 🔢 {amount:.6f} SOL\n"
        )

        if price and price is not None:
            message += f"- Precio: 💰 {price:.6f} SOL\n"

        if status not in ['executed', 'closed']:
            message += f"- Estado: {status_emoji.get(status, '❓')} {status}\n"

        # Añadir detalles adicionales si existen
        if 'error' in trade_data:
            message += f"- Error: ⚠️ {trade_data['error']}\n"

        if 'pnl' in trade_data and trade_data['pnl'] is not None:
            pnl = trade_data['pnl']
            message += f"- P&L: {'🟢' if pnl >= 0 else '🔴'} {pnl:.6f} SOL\n"

        if 'fees' in trade_data and trade_data['fees'] is not None:
            message += f"- Fees: 💸 {trade_data['fees']:.6f} SOL\n"

        if 'signature' in trade_data and trade_data['signature']:
            message += f"- Signature: 🔗 {trade_data['signature'][:8]}...\n"

        if 'execution_price' in trade_data and trade_data['execution_price'] is not None:
            price = trade_data['execution_price']
            if price < 1e-6 and price > 0:
                message += f"- Precio ejecución: 💰 {price:.12f} SOL\n"
            else:
                message += f"- Precio ejecución: 💰 {price:.6f} SOL\n"

        if 'amount_tokens' in trade_data and trade_data['amount_tokens'] is not None:
            message += f"- Tokens: 🪙 {trade_data['amount_tokens']:.2f}\n"

        if 'slippage' in trade_data and trade_data['slippage'] is not None:
            message += f"- Slippage: 📊 {trade_data['slippage']:.2f}%\n"

        if 'close_price' in trade_data and trade_data['close_price'] is not None:
            message += f"- Precio cierre: 💰 {trade_data['close_price']:.6f} SOL\n"

        if 'close_amount_sol' in trade_data and trade_data['close_amount_sol'] is not None:
            message += f"- SOL recibidos: 💰 {trade_data['close_amount_sol']:.6f} SOL\n"

        # Determinar nivel según estado
        if status == "executed":
            level = "success"
        elif status == "closed":
            level = "success"
        elif status == "failed":
            level = "error"
        elif status == "cancelled":
            level = "warning"
        else:
            level = "info"

        await self.notify(message, level)

    async def notify_error(self, error: Exception, context: dict = None) -> None:
        """
        Envía una notificación de error
        
        Args:
            error: Excepción a notificar
            context: Contexto adicional del error
        """
        message = f"❌ Error: {str(error)}"
        if context:
            message += f"\nContexto: {context}"

        await self.notify(message, "error", error=error, context=context)

    async def notify_system(self, message: str, level: str = "info") -> None:
        """
        Envía una notificación del sistema
        
        Args:
            message: Mensaje a enviar
            level: Nivel de la notificación (info, success, warning, error)
        """
        # Formatear mensaje con emojis
        emoji_map = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
            "started": "🚀",
            "stopped": "🛑"
        }

        # Si el nivel es started/stopped, convertir a success/info
        display_level = level
        if level == "started":
            display_level = "success"
        elif level == "stopped":
            display_level = "info"

        emoji = emoji_map.get(level, "📢")
        formatted_message = f"{emoji} <b>{display_level.upper()}</b>\n\n🔧 Sistema: {message}"

        await self.notify(formatted_message, display_level)

    def _format_trade_message(self, trade_data: dict) -> str:
        """
        Formatea un mensaje de trade
        
        Args:
            trade_data: Datos del trade
            
        Returns:
            str: Mensaje formateado
        """
        # Emojis según el tipo de operación
        operation_emoji = "🟢" if trade_data.get("side") == "buy" else "🔴"
        status_emoji = "✅" if trade_data.get("status") == "success" else "⚠️"

        # Formatear mensaje base
        message = (
            f"{operation_emoji} Nuevo Trade {status_emoji}\n"
            f"Par: {trade_data.get('symbol', 'N/A')}\n"
            f"Tipo: {trade_data.get('side', 'N/A').upper()}\n"
            f"Precio: {trade_data.get('price', 'N/A')}\n"
            f"Cantidad: {trade_data.get('amount', 'N/A')}"
        )

        # Añadir detalles adicionales si están disponibles
        if "pnl" in trade_data:
            message += f"\nPNL: {trade_data['pnl']}"
        if "fees" in trade_data:
            message += f"\nComisiones: {trade_data['fees']}"

        return message
