# -*- coding: utf-8 -*-
"""Bridge asíncrono entre PumpFun WebSocket y Redis Pub/Sub."""

import asyncio
import json
import signal
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

import redis.asyncio as aioredis

from logging_system import AppLogger
from .api_client import PumpFunWebSocketApiClient
from .subscriptions import PumpFunSubscriptions


@dataclass(frozen=True)
class RedisBridgeConfig:
    """Configuración para el puente Redis ↔ PumpFun."""

    redis_url: str = "redis://localhost:6379/0"
    namespace: str = "pumpfun"
    api_key: Optional[str] = None
    inactivity_watch_seconds: int = 600
    websocket_timeout: int = 60


class PumpFunRedisBridgeService:
    """Servicio productor que conecta PumpFun WebSocket con Redis Pub/Sub."""

    COMMAND_SUBSCRIBE_ACCOUNT = "subscribe_account_trade"
    COMMAND_UNSUBSCRIBE_ACCOUNT = "unsubscribe_account_trade"
    COMMAND_UNSUBSCRIBE_ALL = "unsubscribe_all"
    COMMAND_PING = "ping"

    EVENT_ACCOUNT_TRADE = "account_trade"
    EVENT_ERROR = "error"
    EVENT_SYSTEM = "system"

    def __init__(self, config: RedisBridgeConfig):
        self._config = config
        self._logger = AppLogger(self.__class__.__name__)

        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[Any] = None

        self._ws_client = PumpFunWebSocketApiClient(
            api_key=config.api_key,
            websocket_timeout=config.websocket_timeout,
            inactivity_watch_seconds=config.inactivity_watch_seconds,
        )
        self._subscriptions = PumpFunSubscriptions(ws_client=self._ws_client)

        self._command_task: Optional[asyncio.Task[Any]] = None
        self._running = False

        # Mapea client_id → set de account addresses que sigue ese cliente
        self._client_accounts: defaultdict[str, Set[str]] = defaultdict(set)
        # Mapea account address → set de client_ids que siguen esa cuenta (índice inverso)
        self._account_clients: defaultdict[str, Set[str]] = defaultdict(set)

        # Locks
        self._subscription_lock = asyncio.Lock()

    # ---------------------------------------------------------------------
    # Propiedades útiles
    # ---------------------------------------------------------------------

    @property
    def command_channel(self) -> str:
        return f"{self._config.namespace}:commands"

    def event_channel(self, client_id: str) -> str:
        return f"{self._config.namespace}:events:{client_id}"

    def response_channel(self, client_id: str) -> str:
        return f"{self._config.namespace}:responses:{client_id}"

    # ---------------------------------------------------------------------
    # Ciclo de vida
    # ---------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            self._logger.debug("Servicio ya está en ejecución, ignorando start()")
            return

        self._logger.info("Iniciando servicio PumpFun Redis Bridge")

        redis_client = aioredis.from_url(self._config.redis_url, decode_responses=True)
        self._redis = redis_client
        self._logger.debug(f"Cliente Redis conectado a {self._config.redis_url}")

        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        self._pubsub = pubsub
        await pubsub.subscribe(self.command_channel)
        self._logger.debug(f"Suscrito al canal de comandos: {self.command_channel}")

        await self._ws_client.connect()
        self._ws_client.set_error_callback(self._handle_ws_error_event)
        self._logger.debug("Cliente WebSocket PumpFun conectado")

        self._command_task = asyncio.create_task(self._command_loop())
        self._running = True
        self._logger.info("Servicio PumpFun Redis Bridge iniciado")

    async def stop(self) -> None:
        if not self._running:
            self._logger.debug("Servicio no está en ejecución, ignorando stop()")
            return

        self._logger.info("Deteniendo servicio PumpFun Redis Bridge")

        if self._command_task:
            self._logger.debug("Cancelando tarea de loop de comandos")
            self._command_task.cancel()
            try:
                await self._command_task
            except asyncio.CancelledError:
                self._logger.debug("Loop de comandos cancelado correctamente")
            except Exception as exc:  # pragma: no cover - logging defensivo
                self._logger.error(f"Error deteniendo loop de comandos: {exc}")
            finally:
                self._command_task = None

        self._logger.debug("Desuscribiendo todas las suscripciones del WebSocket")
        await self._subscriptions.unsubscribe_all()
        await self._ws_client.disconnect()
        self._logger.debug("Cliente WebSocket desconectado")

        pubsub = self._pubsub
        if pubsub:
            try:
                await pubsub.unsubscribe(self.command_channel)
                self._logger.debug(f"Desuscrito del canal de comandos: {self.command_channel}")
            except Exception:
                pass
            finally:
                await pubsub.close()
                self._pubsub = None

        if self._redis:
            await self._redis.close()
            self._redis = None
            self._logger.debug("Cliente Redis cerrado")

        self._client_accounts.clear()
        self._account_clients.clear()
        self._running = False
        self._logger.info("Servicio PumpFun Redis Bridge detenido")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    # ------------------------------------------------------------------
    # Loop de comandos
    # ------------------------------------------------------------------

    async def _command_loop(self) -> None:
        assert self._pubsub is not None, "PubSub no inicializado"

        self._logger.debug("Iniciando loop de comandos")
        try:
            async for raw_message in self._pubsub.listen():
                if raw_message is None:
                    continue
                if raw_message.get("type") != "message":
                    continue

                data = raw_message.get("data")
                if not data:
                    continue

                try:
                    payload = json.loads(data)
                    self._logger.debug(f"Comando recibido: {payload.get('action')} de cliente {payload.get('client_id')}")
                except json.JSONDecodeError:
                    self._logger.warning(f"Mensaje inválido en canal de comandos: {data}")
                    continue

                await self._dispatch_command(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - registro defensivo
            self._logger.error(f"Error en loop de comandos: {exc}", exc_info=True)

    async def _dispatch_command(self, payload: Dict[str, Any]) -> None:
        action = payload.get("action")
        client_id = payload.get("client_id")
        request_id = payload.get("request_id")

        if not client_id:
            self._logger.warning(f"Comando sin client_id: {payload}")
            return

        self._logger.debug(f"Despachando comando {action} para cliente {client_id}")

        if action == self.COMMAND_SUBSCRIBE_ACCOUNT:
            keys = self._sanitize_keys(payload.get("keys", []))
            await self._handle_subscribe_account_trade(client_id, keys, request_id)
        elif action == self.COMMAND_UNSUBSCRIBE_ACCOUNT:
            keys = self._sanitize_keys(payload.get("keys", []))
            await self._handle_unsubscribe_account_trade(client_id, keys, request_id)
        elif action == self.COMMAND_UNSUBSCRIBE_ALL:
            await self._handle_unsubscribe_all(client_id, request_id)
        elif action == self.COMMAND_PING:
            await self._send_response(
                client_id,
                {
                    "type": "pong",
                    "request_id": request_id,
                    "status": "ok",
                },
            )
        else:
            await self._send_response(
                client_id,
                {
                    "type": "error",
                    "request_id": request_id,
                    "status": "error",
                    "message": f"Acción no soportada: {action}",
                },
            )

    # ------------------------------------------------------------------
    # Handlers de comandos
    # ------------------------------------------------------------------

    async def _handle_subscribe_account_trade(
        self,
        client_id: str,
        keys: Iterable[str],
        request_id: Optional[str],
    ) -> None:
        keys = list({key for key in keys if key})
        self._logger.debug(f"Procesando suscripción de {len(keys)} cuentas para cliente {client_id}")

        if not keys:
            self._logger.debug(f"Lista de keys vacía para cliente {client_id}")
            await self._send_response(
                client_id,
                {
                    "type": "subscription",
                    "request_id": request_id,
                    "status": "error",
                    "message": "Lista de keys vacía",
                },
            )
            return

        new_keys: List[str] = []
        async with self._subscription_lock:
            for key in keys:
                self._client_accounts[client_id].add(key)
                clients = self._account_clients[key]
                was_empty = not clients
                clients.add(client_id)
                if was_empty:
                    new_keys.append(key)

        if new_keys:
            self._logger.debug(f"Suscribiendo {len(new_keys)} cuentas nuevas al WebSocket de PumpFun")
            await self._subscriptions.subscribe_account_trade(
                account_addresses=new_keys,
                callback=self._handle_account_trade_event,
            )
            self._logger.debug(
                f"Suscripción PumpFun agregada para {len(new_keys)} cuentas nuevas"
            )
        else:
            self._logger.debug(f"Todas las cuentas solicitadas ya estaban suscritas")

        await self._send_response(
            client_id,
            {
                "type": "subscription",
                "request_id": request_id,
                "status": "ok",
                "action": self.COMMAND_SUBSCRIBE_ACCOUNT,
                "keys": keys,
                "new_keys": new_keys,
            },
        )

    async def _handle_unsubscribe_account_trade(
        self,
        client_id: str,
        keys: Iterable[str],
        request_id: Optional[str],
    ) -> None:
        keys = list({key for key in keys if key})
        self._logger.debug(f"Procesando desuscripción de {len(keys)} cuentas para cliente {client_id}")

        if not keys:
            self._logger.debug(f"Lista de keys vacía para desuscripción de cliente {client_id}")
            await self._send_response(
                client_id,
                {
                    "type": "subscription",
                    "request_id": request_id,
                    "status": "error",
                    "message": "Lista de keys vacía",
                },
            )
            return

        to_unsubscribe: List[str] = []
        async with self._subscription_lock:
            for key in keys:
                clients = self._account_clients.get(key)
                if not clients or client_id not in clients:
                    continue
                clients.discard(client_id)
                if not clients:
                    to_unsubscribe.append(key)
                    self._account_clients.pop(key, None)

            client_keys = self._client_accounts.get(client_id)
            if client_keys:
                client_keys.difference_update(keys)
                if not client_keys:
                    self._client_accounts.pop(client_id, None)

        if to_unsubscribe:
            self._logger.debug(f"Desuscribiendo {len(to_unsubscribe)} cuentas del WebSocket de PumpFun")
            await self._subscriptions.unsubscribe_account_trade(to_unsubscribe)
            self._logger.debug(
                f"Suscripción PumpFun removida para {len(to_unsubscribe)} cuentas"
            )
        else:
            self._logger.debug(f"Ninguna cuenta requiere desuscripción del WebSocket")

        await self._send_response(
            client_id,
            {
                "type": "subscription",
                "request_id": request_id,
                "status": "ok",
                "action": self.COMMAND_UNSUBSCRIBE_ACCOUNT,
                "keys": keys,
                "released_keys": to_unsubscribe,
            },
        )

    async def _handle_unsubscribe_all(self, client_id: str, request_id: Optional[str]) -> None:
        async with self._subscription_lock:
            keys = list(self._client_accounts.get(client_id, set()))

        self._logger.debug(f"Desuscribiendo todas las cuentas ({len(keys)}) del cliente {client_id}")

        if keys:
            await self._handle_unsubscribe_account_trade(client_id, keys, request_id)
        else:
            self._logger.debug(f"Cliente {client_id} no tenía cuentas suscritas")
            await self._send_response(
                client_id,
                {
                    "type": "subscription",
                    "request_id": request_id,
                    "status": "ok",
                    "action": self.COMMAND_UNSUBSCRIBE_ALL,
                    "keys": [],
                    "released_keys": [],
                },
            )

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------

    async def _handle_account_trade_event(self, data: Dict[str, Any]) -> None:
        trader = data.get("traderPublicKey")
        if not trader:
            self._logger.debug("Evento sin traderPublicKey recibido, se ignora")
            return

        async with self._subscription_lock:
            consumers = list(self._account_clients.get(trader, set()))

        if not consumers:
            self._logger.debug(f"Evento de trade recibido para {trader[:8]}... pero sin consumidores")
            return

        self._logger.debug(f"Evento de trade para {trader[:8]}... distribuido a {len(consumers)} cliente(s)")

        message = json.dumps(
            {
                "event": self.EVENT_ACCOUNT_TRADE,
                "trader": trader,
                "data": data,
            }
        )

        await asyncio.gather(
            *[self._publish_event(client_id, message) for client_id in consumers],
            return_exceptions=True,
        )

    async def _publish_event(self, client_id: str, message: str) -> None:
        if not self._redis:
            return

        try:
            await self._redis.publish(self.event_channel(client_id), message)
        except Exception as exc:  # pragma: no cover
            self._logger.error(f"Error publicando evento para {client_id}: {exc}")

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    async def _handle_ws_error_event(self, data: Dict[str, Any]) -> None:
        async with self._subscription_lock:
            clients = list(self._client_accounts.keys())

        if not clients:
            self._logger.debug("Error del WebSocket recibido pero sin clientes conectados")
            return

        self._logger.warning(f"Propagando error del WebSocket a {len(clients)} cliente(s): {data}")

        message = json.dumps(
            {
                "event": self.EVENT_ERROR,
                "data": data,
            }
        )

        await asyncio.gather(
            *[self._publish_event(client_id, message) for client_id in clients],
            return_exceptions=True,
        )

    @staticmethod
    def _sanitize_keys(keys: Iterable[str]) -> List[str]:
        return [key.strip() for key in keys if isinstance(key, str) and key.strip()]

    async def _send_response(self, client_id: str, payload: Dict[str, Any]) -> None:
        if not self._redis:
            return

        channel = self.response_channel(client_id)
        try:
            await self._redis.publish(channel, json.dumps(payload))
        except Exception as exc:  # pragma: no cover
            self._logger.error(
                f"Error publicando respuesta para {client_id} en {channel}: {exc}"
            )

    def get_status(self) -> Dict[str, Any]:
        status = {
            "running": self._running,
            "redis_url": self._config.redis_url,
            "namespace": self._config.namespace,
            "clients": len(self._client_accounts),
            "accounts": len(self._account_clients),
        }
        self._logger.debug(f"Estado del servicio consultado: {status['clients']} clientes, {status['accounts']} cuentas")
        return status


@asynccontextmanager
async def start_redis_bridge(config: RedisBridgeConfig):
    service = PumpFunRedisBridgeService(config)
    await service.start()
    try:
        yield service
    finally:
        await service.stop()


async def run_service(config: RedisBridgeConfig) -> None:
    async with start_redis_bridge(config):
        stop_event = asyncio.Event()

        def _signal_handler(*_: Any) -> None:
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except (NotImplementedError, RuntimeError):  # pragma: no cover - Windows
                signal.signal(sig, lambda *_: stop_event.set())

        try:
            await stop_event.wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            stop_event.set()


def from_env() -> RedisBridgeConfig:
    import os

    return RedisBridgeConfig(
        redis_url=os.getenv("PUMPFUN_REDIS_URL", "redis://localhost:6379/0"),
        namespace=os.getenv("PUMPFUN_REDIS_NAMESPACE", "pumpfun"),
        api_key=os.getenv("PUMPFUN_API_KEY"),
    )


def _main() -> None:
    config = from_env()
    asyncio.run(run_service(config))


if __name__ == "__main__":
    _main()
