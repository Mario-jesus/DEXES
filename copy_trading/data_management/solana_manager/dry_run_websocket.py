# -*- coding: utf-8 -*-
"""
DryRunSolanaWebsocketManager: mock para simular confirmaciones de firmas en modo Dry Run.
No abre conexiones reales. Confirma automáticamente después de un pequeño delay.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Callable, Awaitable, Literal
from datetime import datetime

from logging_system import AppLogger
from ..models.websocket_models import (
    SignatureNotification,
    WebsocketSignatureNotificationParams,
    SignatureNotificationResult,
    SignatureNotificationValue,
    RpcContext,
)


class DryRunSolanaWebsocketManager:
    """
    Mock del gestor de WebSocket de Solana para Dry Run.
    """

    def __init__(self, ws_url: str = "wss://api.mainnet-beta.solana.com/", confirmation_delay_seconds: float = 0.8):
        self.ws_url = ws_url
        self._logger = AppLogger(self.__class__.__name__)

        # Callbacks
        self.on_signature_confirmed: Optional[Callable[[str, SignatureNotification], Awaitable[None]]] = None
        self.on_signature_timeout: Optional[Callable[[str, int], Awaitable[None]]] = None
        self.on_connection_error: Optional[Callable[[Exception], Awaitable[None]]] = None

        # Estado
        self.is_running = False
        self._confirmation_delay = confirmation_delay_seconds

        # Suscripciones activas
        self._active_signatures: set[str] = set()

        self._logger.info("[DRY RUN] DryRunSolanaWebsocketManager inicializado - sin conexión real")

    async def __aenter__(self):
        self.is_running = True
        self._logger.debug("[DRY RUN] Websocket mock iniciado")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        self.is_running = True
        self._logger.debug("[DRY RUN] start() llamado - no se inicia conexión real")

    async def stop(self):
        self.is_running = False
        self._active_signatures.clear()
        self._logger.debug("[DRY RUN] stop() llamado - limpiadas suscripciones mock")

    def set_callbacks(self,
                        on_signature_confirmed: Optional[Callable[[str, SignatureNotification], Awaitable[None]]] = None,
                        on_signature_timeout: Optional[Callable[[str, int], Awaitable[None]]] = None,
                        on_connection_error: Optional[Callable[[Exception], Awaitable[None]]] = None):
        if on_signature_confirmed is not None:
            self.on_signature_confirmed = on_signature_confirmed
        if on_signature_timeout is not None:
            self.on_signature_timeout = on_signature_timeout
        if on_connection_error is not None:
            self.on_connection_error = on_connection_error
        self._logger.debug("[DRY RUN] Callbacks registrados")

    @property
    def is_connected(self) -> bool:
        return True

    def get_subscribed_count(self) -> int:
        return len(self._active_signatures)

    async def subscribe_signature(self,
                                    signature: str,
                                    *,
                                    commitment: Literal["finalized", "confirmed", "processed"] = "finalized",
                                    enable_received_notification: bool = False,
                                    timeout: int = 60) -> bool:
        try:
            if not signature:
                self._logger.warning("[DRY RUN] Signature vacía, no se suscribe")
                return False

            self._active_signatures.add(signature)
            self._logger.info(f"[DRY RUN] Suscripción registrada para signature: {signature}")

            # Lanzar tarea que simula confirmación
            asyncio.create_task(self._simulate_confirmation(signature))
            return True
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error suscribiendo signature: {e}")
            return False

    async def unsubscribe_signature(self, signature: str) -> bool:
        try:
            self._active_signatures.discard(signature)
            self._logger.debug(f"[DRY RUN] Desuscrito: {signature}")
            return True
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error desuscribiendo {signature}: {e}")
            return False

    async def _simulate_confirmation(self, signature: str):
        try:
            await asyncio.sleep(self._confirmation_delay)

            if signature not in self._active_signatures:
                self._logger.debug(f"[DRY RUN] Signature {signature} ya no activa, omitiendo confirmación")
                return

            # Construir notificación de confirmación simulada según el modelo
            notification = SignatureNotification(
                params=WebsocketSignatureNotificationParams(
                    result=SignatureNotificationResult(
                        context=RpcContext(slot=0),
                        value=SignatureNotificationValue(err=None)
                    ),
                    subscription=1
                ),
                jsonrpc="2.0",
                method="signatureNotification"
            )

            self._logger.info(f"[DRY RUN] Signature confirmada (mock): {signature}")
            if self.on_signature_confirmed:
                await self.on_signature_confirmed(signature, notification)

            # Limpiar suscripción
            await self.unsubscribe_signature(signature)
        except Exception as e:
            self._logger.error(f"[DRY RUN] Error simulando confirmación para {signature}: {e}")
