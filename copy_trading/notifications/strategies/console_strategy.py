# -*- coding: utf-8 -*-
"""
Estrategia de notificación para consola
"""
from typing import Dict, Optional
import asyncio

from logging_system import AppLogger
from .base_strategy import BaseNotificationStrategy


class ConsoleStrategy(BaseNotificationStrategy):
    """Implementación de notificaciones para consola"""

    def __init__(self, config: Optional[Dict] = None):
        """
        Inicializa la estrategia de consola
        
        Args:
            config: Configuración (puede incluir 'colored' para usar colores ANSI)
        """
        try:
            super().__init__(config or {})
            self._logger = AppLogger(self.__class__.__name__)
            self.colored = self.config.get('colored', True)

            # Colores ANSI
            self._colors = {
                "info": "\033[94m",     # Azul
                "success": "\033[92m",   # Verde
                "warning": "\033[93m",   # Amarillo
                "error": "\033[91m",     # Rojo
                "critical": "\033[95m",  # Magenta
                "reset": "\033[0m"       # Reset
            }

            # Emojis por nivel
            self._level_emojis = {
                "info": "ℹ️",
                "success": "✅",
                "warning": "⚠️",
                "error": "❌",
                "critical": "🚨"
            }

            self._logger.debug("ConsoleStrategy inicializada")
        except Exception as e:
            print(f"Error inicializando ConsoleStrategy: {e}")
            raise

    @property
    def is_running(self) -> bool:
        """Indica si la estrategia está corriendo"""
        return True

    async def initialize(self) -> None:
        """No requiere inicialización"""
        pass

    async def shutdown(self) -> None:
        """No requiere limpieza"""
        pass

    async def send_notification(self, message: str, level: str = "info") -> None:
        """
        Envía una notificación a la consola
        
        Args:
            message: Mensaje a enviar
            level: Nivel de la notificación
        """
        try:
            # Eliminar etiquetas HTML
            clean_message = message.replace('<b>', '').replace('</b>', '')

            # Colores según nivel
            colors = {
                'info': '\033[94m',    # Azul
                'success': '\033[92m',  # Verde
                'warning': '\033[93m',  # Amarillo
                'error': '\033[91m',    # Rojo
                'critical': '\033[95m'  # Magenta
            }

            # Color por defecto
            color = colors.get(level, '\033[0m')

            # Imprimir mensaje con color
            print(f"{color}{clean_message}\033[0m")

            self._logger.debug(f"Notificación enviada a consola: {level}")

        except asyncio.CancelledError:
            self._logger.debug("Notificación de consola cancelada")
            raise  # Re-lanzar para que el sistema maneje la cancelación
        except Exception as e:
            self._logger.error(f"Error enviando notificación a consola: {e}")
            # No re-lanzar la excepción para evitar que bloquee el sistema
