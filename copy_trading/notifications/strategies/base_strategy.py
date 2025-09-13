# -*- coding: utf-8 -*-
"""
Estrategia base de notificación
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseNotificationStrategy(ABC):
    """Clase base abstracta para estrategias de notificación"""

    def __init__(self, config: Dict[str, Any]):
        """
        Inicializa la estrategia base
        
        Args:
            config: Configuración específica de la estrategia
        """
        self.config = config

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Indica si la estrategia está corriendo"""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Inicializa la estrategia"""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Cierra la estrategia"""
        pass

    @abstractmethod
    async def send_notification(self, message: str, notification_type: str = "info") -> None:
        """
        Envía una notificación
        
        Args:
            message: Mensaje a enviar
            notification_type: Tipo de la notificación (info, success, warning, error, etc.)
        """
        pass
