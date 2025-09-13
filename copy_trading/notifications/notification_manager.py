# -*- coding: utf-8 -*-
"""
Gestor central de notificaciones
"""
from typing import Dict, List, Optional, Any

from .strategies.base_strategy import BaseNotificationStrategy
from logging_system import AppLogger


class NotificationManager:
    """Gestor central de notificaciones"""

    def __init__(self, strategies: Optional[List[BaseNotificationStrategy]] = None):
        """
        Inicializa el gestor de notificaciones
        
        Args:
            strategies: Lista opcional de estrategias de notificación
        """
        try:
            self._strategies: Dict[str, BaseNotificationStrategy] = {}
            self._logger = AppLogger(self.__class__.__name__)
            self._is_running = False

            # Registrar estrategias iniciales
            if strategies:
                for strategy in strategies:
                    self.add_strategy(strategy.__class__.__name__, strategy)

            self._logger.debug(f"NotificationManager configurado con {len(self._strategies)} estrategias")
        except Exception as e:
            print(f"Error inicializando NotificationManager: {e}")
            raise

    @property
    def is_running(self) -> bool:
        """Indica si el gestor de notificaciones está corriendo"""
        return self._is_running

    async def start(self) -> None:
        """
        Inicializa todas las estrategias de notificación registradas
        """
        try:
            for strategy_name, strategy in self._strategies.items():
                try:
                    await strategy.initialize()
                    self._logger.debug(f"Estrategia {strategy_name} inicializada correctamente")
                except Exception as e:
                    self._logger.error(f"Error inicializando estrategia {strategy_name}: {e}")
                    # Continuar con las demás estrategias aunque una falle
                    continue

            self._is_running = True
            self._logger.debug(f"NotificationManager iniciado correctamente con {len(self._strategies)} estrategias")

        except Exception as e:
            self._logger.error(f"Error inicializando NotificationManager: {e}")
            raise

    async def stop(self) -> None:
        """
        Cierra todas las estrategias de notificación registradas
        """
        try:
            self._logger.debug("Cerrando NotificationManager...")

            # Cerrar estrategias primero
            for strategy_name, strategy in self._strategies.items():
                try:
                    await strategy.shutdown()
                    self._logger.debug(f"Estrategia {strategy_name} cerrada correctamente")
                except Exception as e:
                    self._logger.error(f"Error cerrando estrategia {strategy_name}: {e}")
                    # Continuar cerrando las demás estrategias aunque una falle
                    continue

            # Cambiar estado después de cerrar las estrategias
            self._is_running = False

            self._logger.debug("NotificationManager cerrado correctamente")

        except Exception as e:
            self._logger.error(f"Error cerrando NotificationManager: {e}")
            raise

    def add_strategy(self, name: str, strategy: BaseNotificationStrategy) -> None:
        """Añade una estrategia de notificación (solo registro, no inicializa)"""
        try:
            if self._is_running:
                self._logger.warning(f"Estrategia {name} no se puede agregar si el manager está corriendo. Use add_and_initialize_strategy() para inicializar inmediatamente.")
                return

            self._strategies[name] = strategy
            self._logger.debug(f"Estrategia agregada: {name}")
        except Exception as e:
            self._logger.error(f"Error agregando estrategia {name}: {e}")

    async def add_and_initialize_strategy(self, name: str, strategy: BaseNotificationStrategy) -> None:
        """Añade una estrategia de notificación y la inicializa si el manager está corriendo"""
        try:
            self._strategies[name] = strategy
            self._logger.debug(f"Estrategia agregada: {name}")

            # Si el manager ya está corriendo, inicializar la nueva estrategia inmediatamente
            if self._is_running:
                self._logger.debug(f"Inicializando nueva estrategia {name}...")
                try:
                    await strategy.initialize()
                    self._logger.debug(f"Estrategia {name} inicializada correctamente")
                except Exception as e:
                    self._logger.error(f"Error inicializando estrategia {name}: {e}")
                    # Remover la estrategia si falla la inicialización
                    del self._strategies[name]
                    raise
            else:
                self._logger.debug(f"Estrategia {name} registrada, se inicializará cuando el manager se inicie")

        except Exception as e:
            self._logger.error(f"Error agregando e inicializando estrategia {name}: {e}")
            raise

    async def remove_strategy(self, name: str) -> None:
        """Elimina una estrategia de notificación"""
        try:
            if name in self._strategies:
                strategy = self._strategies[name]

                # Cerrar la estrategia antes de removerla si está corriendo
                if self._is_running and hasattr(strategy, 'is_running') and strategy.is_running:
                    self._logger.debug(f"Cerrando estrategia {name} antes de removerla...")
                    try:
                        await strategy.shutdown()
                    except Exception as e:
                        self._logger.error(f"Error cerrando estrategia {name} antes de remover: {e}")

                del self._strategies[name]
                self._logger.debug(f"Estrategia removida: {name}")
            else:
                self._logger.warning(f"Estrategia no encontrada para remover: {name}")
        except Exception as e:
            self._logger.error(f"Error removiendo estrategia {name}: {e}")

    def get_strategy(self, name: str) -> Optional[BaseNotificationStrategy]:
        """Obtiene una estrategia por nombre"""
        try:
            strategy = self._strategies.get(name)
            if strategy:
                self._logger.debug(f"Estrategia obtenida: {name}")
            else:
                self._logger.debug(f"Estrategia no encontrada: {name}")
            return strategy
        except Exception as e:
            self._logger.error(f"Error obteniendo estrategia {name}: {e}")
            return None

    def get_all_strategies(self) -> List[BaseNotificationStrategy]:
        """Obtiene todas las estrategias registradas"""
        try:
            strategies = list(self._strategies.values())
            self._logger.debug(f"Obtenidas {len(strategies)} estrategias")
            return strategies
        except Exception as e:
            self._logger.error(f"Error obteniendo todas las estrategias: {e}")
            return []

    async def notify(self, message: str, level: str = "info", **kwargs) -> None:
        """
        Envía una notificación a través de todas las estrategias registradas
        
        Args:
            message: Mensaje a enviar
            level: Nivel de la notificación (info, success, warning, error, critical)
            **kwargs: Argumentos adicionales para las estrategias
        """
        if not self._is_running:
            self._logger.warning("NotificationManager no está corriendo, no se puede enviar notificación")
            return

        try:
            self._logger.debug(f"Enviando notificación {level} a {len(self._strategies)} estrategias")

            for strategy_name, strategy in self._strategies.items():
                try:
                    # Verificar que la estrategia esté corriendo antes de enviar
                    if hasattr(strategy, 'is_running') and not strategy.is_running:
                        self._logger.warning(f"Estrategia {strategy_name} no está corriendo, saltando notificación")
                        continue

                    await strategy.send_notification(message, level)
                    self._logger.debug(f"Notificación enviada exitosamente a {strategy_name}")
                except Exception as e:
                    error_msg = f"Error al enviar notificación a través de {strategy_name}: {e}"
                    self._logger.error(error_msg)

            self._logger.debug("Proceso de notificación completado")
        except Exception as e:
            self._logger.error(f"Error general en proceso de notificación: {e}")

    async def notify_trade(self, trade_data: dict) -> None:
        """
        Envía una notificación específica de trade
        
        Args:
            trade_data: Datos del trade a notificar
        """
        try:
            if not self._is_running:
                self._logger.warning("NotificationManager no está corriendo, no se puede enviar notificación")
                return

            self._logger.debug("Procesando notificación de trade")

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
            # Convertir amount a float para formateo si es necesario
            try:
                amount_formatted = f"{float(amount):.6f}" if amount is not None else "0.000000"
            except (ValueError, TypeError):
                amount_formatted = str(amount) if amount is not None else "0"

            message = (
                f"{action_emoji.get(action, '❓')} Trade {action}\n"
                f"- Token: 💎 {token_name} ({token_symbol})\n"
                f"- Dirección: 🔗 {token_address[:8]}...\n"
                f"- Cantidad: 🔢 {amount_formatted} SOL\n"
            )

            if price and price is not None:
                try:
                    price_formatted = f"{float(price):.6f}"
                except (ValueError, TypeError):
                    price_formatted = str(price)
                message += f"- Precio: 💰 {price_formatted} SOL\n"

            if status not in ['executed', 'closed']:
                message += f"- Estado: {status_emoji.get(status, '❓')} {status}\n"

            # Añadir detalles adicionales si existen
            if 'error' in trade_data:
                message += f"- Error: ⚠️ {trade_data['error']}\n"

            if 'pnl' in trade_data and trade_data['pnl'] is not None:
                pnl = trade_data['pnl']
                message += f"- P&L: {'🟢' if pnl >= 0 else '🔴'} {pnl:.12f} SOL\n"

            if 'pnl_usd' in trade_data and trade_data['pnl_usd'] is not None:
                pnl_usd = trade_data['pnl_usd']
                message += f"- P&L USD: {'🟢' if pnl_usd >= 0 else '🔴'} {pnl_usd:.12f} USD\n"

            if 'fees' in trade_data and trade_data['fees'] is not None:
                try:
                    fees_formatted = f"{float(trade_data['fees']):.6f}"
                except (ValueError, TypeError):
                    fees_formatted = str(trade_data['fees'])
                message += f"- Fees: 💸 {fees_formatted} SOL\n"

            if 'signature' in trade_data and trade_data['signature']:
                message += f"- Signature: 🔗 {trade_data['signature'][:8]}...\n"

            if 'execution_price' in trade_data and trade_data['execution_price'] is not None:
                price = trade_data['execution_price']
                try:
                    price_float = float(price)
                    if price_float < 1e-6 and price_float > 0:
                        price_formatted = f"{price_float:.12f}"
                    else:
                        price_formatted = f"{price_float:.6f}"
                except (ValueError, TypeError):
                    price_formatted = str(price)
                message += f"- Precio ejecución: 💰 {price_formatted} SOL\n"

            if 'amount_tokens' in trade_data and trade_data['amount_tokens'] is not None:
                message += f"- Tokens: 🪙 {trade_data['amount_tokens']:.2f}\n"

            if 'slippage' in trade_data and trade_data['slippage'] is not None:
                message += f"- Slippage: 📊 {trade_data['slippage']:.2f}%\n"

            if 'close_price' in trade_data and trade_data['close_price'] is not None:
                try:
                    close_price_formatted = f"{float(trade_data['close_price']):.6f}"
                except (ValueError, TypeError):
                    close_price_formatted = str(trade_data['close_price'])
                message += f"- Precio cierre: 💰 {close_price_formatted} SOL\n"

            if 'close_amount_sol' in trade_data and trade_data['close_amount_sol'] is not None:
                try:
                    close_amount_formatted = f"{float(trade_data['close_amount_sol']):.6f}"
                except (ValueError, TypeError):
                    close_amount_formatted = str(trade_data['close_amount_sol'])
                message += f"- SOL recibidos: 💰 {close_amount_formatted} SOL\n"

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

            self._logger.debug(f"Notificación de trade formateada: {action} {token_symbol} - {status}")
            await self.notify(message, level)

        except Exception as e:
            self._logger.error(f"Error procesando notificación de trade: {e}")

    async def notify_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Envía una notificación de error
        
        Args:
            error: Excepción a notificar
            context: Contexto adicional del error
        """
        try:
            if not self._is_running:
                self._logger.warning("NotificationManager no está corriendo, no se puede enviar notificación")
                return

            self._logger.debug("Procesando notificación de error")

            message = f"❌ Error: {str(error)}"
            if context:
                message += f"\nContexto: {context}"

            self._logger.debug(f"Notificación de error formateada: {type(error).__name__}")
            await self.notify(message, "error", error=error, context=context)

        except Exception as e:
            self._logger.error(f"Error procesando notificación de error: {e}")

    async def notify_system(self, message: str, level: str = "info") -> None:
        """
        Envía una notificación del sistema
        
        Args:
            message: Mensaje a enviar
            level: Nivel de la notificación (info, success, warning, error)
        """
        try:
            if not self._is_running:
                self._logger.warning("NotificationManager no está corriendo, no se puede enviar notificación")
                return

            self._logger.debug("Procesando notificación del sistema")

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

            self._logger.debug(f"Notificación del sistema formateada: {level}")
            await self.notify(formatted_message, display_level)

        except Exception as e:
            self._logger.error(f"Error procesando notificación del sistema: {e}")

    def _format_trade_message(self, trade_data: dict) -> str:
        """
        Formatea un mensaje de trade
        
        Args:
            trade_data: Datos del trade
            
        Returns:
            str: Mensaje formateado
        """
        try:
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

            self._logger.debug("Mensaje de trade formateado exitosamente")
            return message

        except Exception as e:
            self._logger.error(f"Error formateando mensaje de trade: {e}")
            return "Error formateando mensaje de trade"
