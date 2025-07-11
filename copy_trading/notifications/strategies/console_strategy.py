# -*- coding: utf-8 -*-
"""
Estrategia de notificación para consola
"""
from typing import Dict
from .base_strategy import BaseNotificationStrategy


class ConsoleStrategy(BaseNotificationStrategy):
    """Implementación de notificaciones para consola"""

    def __init__(self, config: Dict = None, logger=None):
        """
        Inicializa la estrategia de consola
        
        Args:
            config: Configuración (puede incluir 'colored' para usar colores ANSI)
            logger: Logger opcional para registrar eventos
        """
        super().__init__(config or {})
        self.logger = logger
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

            if self.logger:
                self.logger.info(f"Mensaje enviado a consola: {clean_message}")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Error enviando notificación a consola: {e}")
            else:
                print(f"Error enviando notificación a consola: {e}")
