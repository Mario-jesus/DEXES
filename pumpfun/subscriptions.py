# -*- coding: utf-8 -*-
"""
PumpFun Subscriptions - Clase de alto nivel para gestionar suscripciones WebSocket
Proporciona métodos convenientes para suscribirse/desuscribirse de eventos de PumpPortal.
"""
from typing import List, Callable, Optional

from .api_client import PumpFunApiClient
from .callbacks import EVENT_CALLBACKS


class PumpFunSubscriptions:
    """Wrapper de alto nivel sobre PumpFunApiClient para gestionar suscripciones"""

    def __init__(self, api_client: Optional[PumpFunApiClient] = None, api_key: Optional[str] = None):
        """
        Args:
            api_client: Instancia existente de PumpFunApiClient. Si es None, se creará una nueva.
            api_key: API key para autenticación. Requerida para algunas funcionalidades.
        """
        self.client = api_client or PumpFunApiClient(api_key=api_key, enable_http=False)
        self._active_subscriptions = set()

    async def __aenter__(self):
        """
        Método de entrada para el context manager asíncrono.
        Conecta el cliente WebSocket automáticamente.
        """
        print("🔌 Iniciando sesión PumpFun...")
        await self.client.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Método de salida para el context manager asíncrono.
        Desuscribe todos los eventos activos y desconecta el cliente.
        """
        print("\n🔌 Cerrando sesión PumpFun...")

        # Desuscribir de todos los eventos activos
        if self._active_subscriptions:
            print(f"📤 Desuscribiendo de {len(self._active_subscriptions)} eventos...")
            await self.unsubscribe_all()

        # Desconectar cliente
        await self.disconnect()
        print("✅ Sesión cerrada correctamente")

    # ==========================================================================
    # MÉTODOS DE SUSCRIPCIÓN
    # ==========================================================================

    async def subscribe_new_token(self, callback: Optional[Callable] = None):
        """
        Suscribe a eventos de creación de nuevos tokens.
        
        Args:
            callback: Función para procesar cada mensaje. Si es None, usa el callback por defecto.
        """
        method = "subscribeNewToken"
        await self.client.subscribe(
            method=method,
            callback=callback or EVENT_CALLBACKS[method],
            use_api_key=False  # No requiere API key
        )
        self._active_subscriptions.add(method)

    async def subscribe_token_trade(
        self,
        token_addresses: List[str],
        callback: Optional[Callable] = None,
        use_api_key: bool = False,
    ):
        """
        Suscribe a trades de tokens específicos.

        Args:
            token_addresses: Lista de token mints.
            callback: Función para procesar cada mensaje. Si es None, usa el callback por defecto.
            use_api_key: Si True, conecta el WebSocket con API key (requerido para PumpSwap).
        """
        method = "subscribeTokenTrade"
        await self.client.subscribe(
            method=method,
            keys=token_addresses,
            callback=callback or EVENT_CALLBACKS[method],
            use_api_key=use_api_key,
        )
        self._active_subscriptions.add(f"{method}:{','.join(token_addresses)}")

    async def subscribe_account_trade(
        self,
        account_addresses: List[str],
        callback: Optional[Callable] = None,
        use_api_key: bool = False,
    ):
        """
        Suscribe a trades de cuentas específicas.

        Args:
            account_addresses: Lista de direcciones de wallet.
            callback: Función para procesar cada mensaje. Si es None, usa el callback por defecto.
            use_api_key: Si True, conecta el WebSocket con API key (requerido para PumpSwap).
        """
        method = "subscribeAccountTrade"
        await self.client.subscribe(
            method=method,
            keys=account_addresses,
            callback=callback or EVENT_CALLBACKS[method],
            use_api_key=use_api_key,
        )
        self._active_subscriptions.add(f"{method}:{','.join(account_addresses)}")

    async def subscribe_migration(self, callback: Optional[Callable] = None):
        """
        Suscribe a eventos de migración de tokens.
        
        Args:
            callback: Función para procesar cada mensaje. Si es None, usa el callback por defecto.
        """
        method = "subscribeMigration"
        await self.client.subscribe(
            method=method,
            callback=callback or EVENT_CALLBACKS[method],
            use_api_key=False,
        )
        self._active_subscriptions.add(method)

    # ==========================================================================
    # MÉTODOS DE DESUSCRIPCIÓN
    # ==========================================================================

    async def unsubscribe_new_token(self):
        """Desuscribe de eventos de nuevos tokens."""
        method = "subscribeNewToken"
        await self.client.unsubscribe(method)
        self._active_subscriptions.discard(method)

    async def unsubscribe_token_trade(self, token_addresses: List[str]):
        """Desuscribe de trades de tokens específicos."""
        method = "subscribeTokenTrade"
        await self.client.unsubscribe(method, keys=token_addresses)
        self._active_subscriptions.discard(f"{method}:{','.join(token_addresses)}")

    async def unsubscribe_account_trade(self, account_addresses: List[str]):
        """Desuscribe de trades de cuentas específicas."""
        method = "subscribeAccountTrade"
        await self.client.unsubscribe(method, keys=account_addresses)
        self._active_subscriptions.discard(f"{method}:{','.join(account_addresses)}")

    async def unsubscribe_migration(self):
        """Desuscribe de eventos de migración."""
        method = "subscribeMigration"
        await self.client.unsubscribe(method)
        self._active_subscriptions.discard(method)

    async def unsubscribe_all(self):
        """Desuscribe de todos los eventos activos."""
        await self.client.unsubscribe_all()
        self._active_subscriptions.clear()

    # ==========================================================================
    # UTILIDADES
    # ==========================================================================

    async def disconnect(self):
        """Atajo para desconectar el cliente subyacente."""
        await self.client.disconnect()

    def get_status(self):
        """
        Obtiene el estado actual del cliente y las suscripciones.
        
        Returns:
            Dict con estado del cliente y suscripciones activas
        """
        status = self.client.get_status()
        status['active_subscriptions_count'] = len(self._active_subscriptions)
        status['active_subscriptions_list'] = list(self._active_subscriptions)
        return status
