# -*- coding: utf-8 -*-
"""
PumpFun Subscriptions - Clase de alto nivel para gestionar suscripciones WebSocket
Proporciona métodos convenientes para suscribirse/desuscribirse de eventos de PumpPortal.
"""
from typing import List, Callable, Optional, Set, Type, Any, TYPE_CHECKING

from logging_system import AppLogger
from .api_client import PumpFunWebSocketApiClient, WebSocketMethod
from .callbacks import EVENT_CALLBACKS

if TYPE_CHECKING:
    from types import TracebackType


class PumpFunSubscriptions:
    """Wrapper de alto nivel sobre PumpFunApiClient para gestionar suscripciones"""

    def __init__(self, ws_client: Optional[PumpFunWebSocketApiClient] = None, api_key: Optional[str] = None):
        """
        Args:
            ws_client: Instancia existente de PumpFunWebSocketApiClient. Si es None, se creará una nueva.
            api_key: API key para autenticación. Requerida para algunas funcionalidades.
        """
        self.ws_client = ws_client or PumpFunWebSocketApiClient(api_key=api_key)
        self._active_subscriptions: Set[str] = set()
        self._logger = AppLogger(self.__class__.__name__)

    async def __aenter__(self):
        """
        Método de entrada para el context manager asíncrono.
        Conecta el cliente WebSocket automáticamente.
        """
        self._logger.debug("Iniciando sesión PumpFun...")
        await self.ws_client.connect()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional["TracebackType"]):
        """
        Método de salida para el context manager asíncrono.
        Desuscribe todos los eventos activos y desconecta el cliente.
        """
        self._logger.debug("Cerrando sesión PumpFun...")

        # Desconectar cliente
        await self.disconnect()
        self._logger.debug("Sesión cerrada correctamente")

    # ==========================================================================
    # MÉTODOS DE SUSCRIPCIÓN
    # ==========================================================================

    async def subscribe_new_token(self, callback: Optional[Callable[[Any], Any]] = None):
        """
        Suscribe a eventos de creación de nuevos tokens.
        
        Args:
            callback: Función para procesar cada mensaje. Si es None, usa el callback por defecto.
        """
        method = WebSocketMethod.SUBSCRIBE_NEW_TOKEN
        await self.ws_client.subscribe(
            method=method,
            callback=callback or EVENT_CALLBACKS[method.value]
        )
        self._active_subscriptions.add(method.value)

    async def subscribe_token_trade(
        self,
        token_addresses: List[str],
        callback: Optional[Callable[[Any], Any]] = None,
    ):
        """
        Suscribe a trades de tokens específicos.

        Args:
            token_addresses: Lista de token mints.
            callback: Función para procesar cada mensaje. Si es None, usa el callback por defecto.
        """
        method = WebSocketMethod.SUBSCRIBE_TOKEN_TRADE
        await self.ws_client.subscribe(
            method=method,
            keys=token_addresses,
            callback=callback or EVENT_CALLBACKS[method.value]
        )
        self._active_subscriptions.add(f"{method.value}:{','.join(token_addresses)}")

    async def subscribe_account_trade(
        self,
        account_addresses: List[str],
        callback: Optional[Callable[[Any], Any]] = None,
    ):
        """
        Suscribe a trades de cuentas específicas.

        Args:
            account_addresses: Lista de direcciones de wallet.
            callback: Función para procesar cada mensaje. Si es None, usa el callback por defecto.
        """
        method = WebSocketMethod.SUBSCRIBE_ACCOUNT_TRADE
        await self.ws_client.subscribe(
            method=method,
            keys=account_addresses,
            callback=callback or EVENT_CALLBACKS[method.value],
        )
        self._active_subscriptions.add(f"{method.value}:{','.join(account_addresses)}")

    async def subscribe_migration(self, callback: Optional[Callable[[Any], Any]] = None):
        """
        Suscribe a eventos de migración de tokens.
        
        Args:
            callback: Función para procesar cada mensaje. Si es None, usa el callback por defecto.
        """
        method = WebSocketMethod.SUBSCRIBE_MIGRATION
        await self.ws_client.subscribe(
            method=method,
            callback=callback or EVENT_CALLBACKS[method.value],
        )
        self._active_subscriptions.add(method.value)

    # ==========================================================================
    # MÉTODOS DE DESUSCRIPCIÓN
    # ==========================================================================

    async def unsubscribe_new_token(self):
        """Desuscribe de eventos de nuevos tokens."""
        method = WebSocketMethod.SUBSCRIBE_NEW_TOKEN
        await self.ws_client.unsubscribe(method)
        self._active_subscriptions.discard(method.value)

    async def unsubscribe_token_trade(self, token_addresses: List[str]):
        """Desuscribe de trades de tokens específicos."""
        method = WebSocketMethod.SUBSCRIBE_TOKEN_TRADE
        await self.ws_client.unsubscribe(method, keys=token_addresses)
        self._active_subscriptions.discard(f"{method.value}:{','.join(token_addresses)}")

    async def unsubscribe_account_trade(self, account_addresses: List[str]):
        """Desuscribe de trades de cuentas específicas."""
        method = WebSocketMethod.SUBSCRIBE_ACCOUNT_TRADE
        await self.ws_client.unsubscribe(method, keys=account_addresses)
        self._active_subscriptions.discard(f"{method.value}:{','.join(account_addresses)}")

    async def unsubscribe_migration(self):
        """Desuscribe de eventos de migración."""
        method = WebSocketMethod.SUBSCRIBE_MIGRATION
        await self.ws_client.unsubscribe(method)
        self._active_subscriptions.discard(method.value)

    async def unsubscribe_all(self):
        """Desuscribe de todos los eventos activos."""
        await self.ws_client.unsubscribe_all()
        self._active_subscriptions.clear()

    # ==========================================================================
    # UTILIDADES
    # ==========================================================================

    async def disconnect(self):
        """Atajo para desconectar el cliente subyacente."""
        await self.ws_client.disconnect()

    def get_status(self):
        """
        Obtiene el estado actual del cliente y las suscripciones.
        
        Returns:
            Dict con estado del cliente y suscripciones activas
        """
        status = self.ws_client.get_status()
        status['active_subscriptions_count'] = len(self._active_subscriptions)
        status['active_subscriptions_list'] = list(self._active_subscriptions)
        return status
