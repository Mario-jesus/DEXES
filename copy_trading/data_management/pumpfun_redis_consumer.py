# -*- coding: utf-8 -*-
"""Cliente Redis para consumir eventos de PumpFun compartidos."""

import asyncio
import json
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

import redis.asyncio as aioredis

from logging_system import AppLogger


class PumpFunRedisSubscriptions:
    """Cliente consumidor que interactúa con el PumpFunRedisBridgeService."""

    _ACTION_SUBSCRIBE_ACCOUNT = "subscribe_account_trade"
    _ACTION_UNSUBSCRIBE_ACCOUNT = "unsubscribe_account_trade"
    _ACTION_SUBSCRIBE_TOKEN = "subscribe_token_trade"
    _ACTION_UNSUBSCRIBE_TOKEN = "unsubscribe_token_trade"
    _ACTION_UNSUBSCRIBE_ALL = "unsubscribe_all"
    _ACTION_PING = "ping"

    def __init__(
        self,
        *,
        redis_url: str,
        namespace: str = "pumpfun",
        client_id: Optional[str] = None,
        ack_timeout: float = 10.0,
    ) -> None:
        self._redis_url = redis_url
        self._namespace = namespace
        self._client_id = client_id or f"copytrading-{uuid.uuid4()}"
        self._ack_timeout = ack_timeout

        self._logger = AppLogger(self.__class__.__name__)

        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[Any] = None
        self._listener_task: Optional[asyncio.Task[Any]] = None

        self._pending_requests: Dict[str, asyncio.Future[Any]] = {}

        self._account_callback: Optional[Callable[[Any], Any]] = None
        self._token_callback: Optional[Callable[[Any], Any]] = None
        self._error_callback: Optional[Callable[[Any], Any]] = None
        self._disconnect_time_exceeded_callback: Optional[Callable[[Any], Any]] = None
        self._reconnect_after_disconnect_time_exceeded_callback: Optional[Callable[[Any], Any]] = None
        self._global_callback: Optional[Callable[[Any], Any]] = None

        self._active_accounts: Set[str] = set()
        self._active_tokens: Set[str] = set()
        self._running = False

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def _command_channel(self) -> str:
        return f"{self._namespace}:commands"

    @property
    def _event_channel(self) -> str:
        return f"{self._namespace}:events:{self._client_id}"

    @property
    def _response_channel(self) -> str:
        return f"{self._namespace}:responses:{self._client_id}"

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            self._logger.debug("Cliente ya está en ejecución, ignorando start()")
            return

        self._logger.info(
            f"Inicializando PumpFunRedisSubscriptions con client_id={self._client_id}"
        )

        redis_client = aioredis.from_url(self._redis_url, decode_responses=True)
        self._redis = redis_client
        self._logger.debug(f"Cliente Redis conectado a {self._redis_url}")

        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        self._pubsub = pubsub
        await pubsub.subscribe(self._event_channel, self._response_channel)
        self._logger.debug(f"Suscrito a canales: eventos={self._event_channel}, respuestas={self._response_channel}")

        self._listener_task = asyncio.create_task(self._listener_loop())
        self._running = True
        self._logger.info("Cliente PumpFunRedisSubscriptions iniciado")

    async def stop(self) -> None:
        if not self._running:
            self._logger.debug("Cliente no está en ejecución, ignorando stop()")
            return

        self._logger.info("Deteniendo PumpFunRedisSubscriptions")

        if self._listener_task:
            self._logger.debug("Cancelando tarea de listener")
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                self._logger.debug("Listener cancelado correctamente")
            except Exception as exc:  # pragma: no cover
                self._logger.error(f"Error deteniendo listener: {exc}")
            finally:
                self._listener_task = None

        pubsub = self._pubsub
        if pubsub:
            try:
                await pubsub.unsubscribe(self._event_channel, self._response_channel)
                self._logger.debug("Desuscrito de canales de eventos y respuestas")
            except Exception:
                pass
            finally:
                await pubsub.close()
                self._pubsub = None

        if self._redis:
            await self._redis.close()
            self._redis = None
            self._logger.debug("Cliente Redis cerrado")

        self._running = False
        self._logger.info("Cliente PumpFunRedisSubscriptions detenido")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    # ------------------------------------------------------------------
    # Suscripciones públicas (interfaz similar a PumpFunSubscriptions)
    # ------------------------------------------------------------------

    async def subscribe_account_trade(
        self,
        account_addresses: List[str],
        callback: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        keys = self._normalize_keys(account_addresses)
        if not keys:
            self._logger.debug("Lista de cuentas vacía, no se procesa suscripción")
            return

        self._logger.debug(f"Solicitando suscripción a {len(keys)} cuenta(s)")

        if callback:
            self._account_callback = callback
            self._logger.debug("Callback de cuenta registrado")

        await self._send_command(self._ACTION_SUBSCRIBE_ACCOUNT, keys=keys)
        async with self._lock:
            self._active_accounts.update(keys)

        self._logger.info(f"Suscrito a {len(keys)} cuenta(s), total activas: {len(self._active_accounts)}")

    async def unsubscribe_account_trade(self, account_addresses: List[str]) -> None:
        keys = self._normalize_keys(account_addresses)
        if not keys:
            self._logger.debug("Lista de cuentas vacía, no se procesa desuscripción")
            return

        self._logger.debug(f"Solicitando desuscripción de {len(keys)} cuenta(s)")

        await self._send_command(self._ACTION_UNSUBSCRIBE_ACCOUNT, keys=keys)
        async with self._lock:
            self._active_accounts.difference_update(keys)

        self._logger.info(f"Desuscrito de {len(keys)} cuenta(s), total activas: {len(self._active_accounts)}")

    async def subscribe_token_trade(
        self,
        token_addresses: List[str],
        callback: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        keys = self._normalize_keys(token_addresses)
        if not keys:
            self._logger.debug("Lista de tokens vacía, no se procesa suscripción")
            return

        self._logger.debug(f"Solicitando suscripción a {len(keys)} token(s)")

        if callback:
            self._token_callback = callback
            self._logger.debug("Callback de token registrado")

        await self._send_command(self._ACTION_SUBSCRIBE_TOKEN, keys=keys)
        async with self._lock:
            self._active_tokens.update(keys)

        self._logger.info(f"Suscrito a {len(keys)} token(s), total activos: {len(self._active_tokens)}")

    async def unsubscribe_token_trade(self, token_addresses: List[str]) -> None:
        keys = self._normalize_keys(token_addresses)
        if not keys:
            self._logger.debug("Lista de tokens vacía, no se procesa desuscripción")
            return

        self._logger.debug(f"Solicitando desuscripción de {len(keys)} token(s)")

        await self._send_command(self._ACTION_UNSUBSCRIBE_TOKEN, keys=keys)
        async with self._lock:
            self._active_tokens.difference_update(keys)

        self._logger.info(f"Desuscrito de {len(keys)} token(s), total activos: {len(self._active_tokens)}")

    async def unsubscribe_all(self) -> None:
        account_count = len(self._active_accounts)
        token_count = len(self._active_tokens)
        self._logger.debug(f"Solicitando desuscripción de todas las suscripciones ({account_count} cuentas, {token_count} tokens)")

        await self._send_command(self._ACTION_UNSUBSCRIBE_ALL, keys=[])
        async with self._lock:
            self._active_accounts.clear()
            self._active_tokens.clear()

        self._logger.info(f"Desuscrito de todas las suscripciones (eran {account_count} cuentas, {token_count} tokens)")

    async def disconnect(self) -> None:
        await self.stop()

    def get_status(self) -> Dict[str, Any]:
        status = {
            "redis_url": self._redis_url,
            "namespace": self._namespace,
            "client_id": self._client_id,
            "running": self._running,
            "active_accounts": list(self._active_accounts),
            "active_tokens": list(self._active_tokens),
            "pending_requests": len(self._pending_requests),
        }
        self._logger.debug(
            f"Estado consultado: {len(self._active_accounts)} cuentas activas, "
            f"{len(self._active_tokens)} tokens activos, "
            f"{status['pending_requests']} solicitudes pendientes"
        )
        return status

    def set_error_callback(self, callback: Callable[[Any], Any]) -> None:
        self._error_callback = callback
        self._logger.debug("Callback de error registrado")

    def set_disconnect_time_exceeded_callback(self, callback: Callable[[Any], Any]) -> None:
        """Establece callback para eventos de desconexión excedida"""
        self._disconnect_time_exceeded_callback = callback
        self._logger.debug("Callback de desconexión excedida registrado")

    def set_reconnect_after_disconnect_time_exceeded_callback(self, callback: Callable[[Any], Any]) -> None:
        """Establece callback para eventos de reconexión después de desconexión excedida"""
        self._reconnect_after_disconnect_time_exceeded_callback = callback
        self._logger.debug("Callback de reconexión después de desconexión excedida registrado")

    def set_global_callback(self, callback: Callable[[Any], Any]) -> None:
        self._global_callback = callback
        self._logger.debug("Callback global registrado")

    # ------------------------------------------------------------------
    # Comunicación Redis
    # ------------------------------------------------------------------

    async def _listener_loop(self) -> None:
        assert self._pubsub is not None, "PubSub no inicializado"
        self._logger.debug("Iniciando loop de listener Redis")

        try:
            async for message in self._pubsub.listen():
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue

                channel = message.get("channel")
                data = message.get("data")
                if not channel or not data:
                    continue

                if channel == self._response_channel:
                    self._logger.debug("Respuesta recibida del bridge")
                    await self._handle_response_message(data)
                elif channel == self._event_channel:
                    self._logger.debug("Evento recibido del bridge")
                    await self._handle_event_message(data)
        except asyncio.CancelledError:
            self._logger.debug("Loop de listener cancelado")
            raise
        except Exception as exc:  # pragma: no cover
            self._logger.error(f"Error en listener Redis: {exc}", exc_info=True)

    async def _handle_response_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._logger.warning(f"Respuesta inválida recibida: {raw}")
            return

        request_id = payload.get("request_id")
        future = self._pending_requests.get(request_id)
        if future and not future.done():
            status = payload.get("status", "unknown")
            self._logger.debug(f"Respuesta procesada para request_id={request_id}, status={status}")
            future.set_result(payload)
        else:
            self._logger.debug(f"Respuesta ignorada (request_id={request_id} no encontrado o ya resuelto)")

    async def _handle_event_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._logger.warning(f"Evento inválido recibido: {raw}")
            return

        event_type = payload.get("event")
        self._logger.debug(f"Procesando evento tipo: {event_type}")

        if event_type == "account_trade":
            trader = payload.get("trader")
            self._logger.debug(f"Evento account_trade para trader {trader[:8] if trader else 'unknown'}...")
            await self._dispatch_callback(self._account_callback, payload.get("data"))
        elif event_type == "token_trade":
            token = payload.get("token")
            self._logger.debug(f"Evento token_trade para token {token[:8] if token else 'unknown'}...")
            await self._dispatch_callback(self._token_callback, payload.get("data"))
        elif event_type == "error":
            self._logger.warning(f"Evento de error recibido: {payload.get('data')}")
            await self._dispatch_callback(self._error_callback, payload.get("data"))
        elif event_type == "disconnect_time_exceeded":
            self._logger.warning(f"Evento de desconexión excedida recibido: {payload.get('data')}")
            await self._dispatch_callback(self._disconnect_time_exceeded_callback, payload.get("data"))
        elif event_type == "reconnect_after_disconnect_time_exceeded":
            self._logger.warning(f"Evento de reconexión después de desconexión excedida recibido: {payload.get('data')}")
            await self._dispatch_callback(self._reconnect_after_disconnect_time_exceeded_callback, payload.get("data"))
        else:
            self._logger.debug(f"Evento no clasificado: {event_type}")
            await self._dispatch_callback(self._global_callback, payload)

    async def _send_command(self, action: str, *, keys: Iterable[str]) -> None:
        if not self._redis:
            raise RuntimeError("Cliente Redis no inicializado")

        normalized_keys = self._normalize_keys(keys)

        payload = {
            "action": action,
            "client_id": self._client_id,
            "request_id": str(uuid.uuid4()),
            "keys": normalized_keys,
        }

        self._logger.debug(f"Enviando comando {action} con {len(normalized_keys)} keys, request_id={payload['request_id']}")

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending_requests[payload["request_id"]] = future

        start = time.perf_counter()
        await self._redis.publish(self._command_channel, json.dumps(payload))
        self._logger.debug(f"Comando {action} publicado, esperando ACK...")

        try:
            response = await asyncio.wait_for(future, timeout=self._ack_timeout)
            self._logger.debug(f"ACK recibido para comando {action}")
        except asyncio.TimeoutError as exc:
            self._pending_requests.pop(payload["request_id"], None)
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._logger.error(
                f"Timeout esperando ACK para acción {action} después de {self._ack_timeout}s "
                f"(request_id={payload['request_id']}, tiempo transcurrido={elapsed_ms:.2f} ms)"
            )
            raise TimeoutError(
                f"Timeout esperando ACK para acción {action}"
            ) from exc

        status = response.get("status")
        if status != "ok":
            message = response.get("message", "Error desconocido")
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._logger.error(
                f"Comando {action} rechazado: {message} "
                f"(request_id={payload['request_id']}, tiempo={elapsed_ms:.2f} ms)"
            )
            raise RuntimeError(f"Acción {action} falló: {message}")

        self._pending_requests.pop(payload["request_id"], None)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._logger.info(
            f"Comando {action} request_id={payload['request_id']} procesado en {elapsed_ms:.2f} ms (status=ok)"
        )

    async def _dispatch_callback(
        self,
        callback: Optional[Callable[[Any], Any]],
        data: Any,
    ) -> None:
        if not callback:
            self._logger.debug("Callback no definido, evento no procesado")
            return

        try:
            if asyncio.iscoroutinefunction(callback):
                self._logger.debug("Ejecutando callback asíncrono")
                await callback(data)
            elif hasattr(callback, "__call__") and asyncio.iscoroutinefunction(callback.__call__):
                self._logger.debug("Ejecutando callback asíncrono (callable)")
                await callback(data)
            else:
                self._logger.debug("Ejecutando callback síncrono")
                callback(data)
            self._logger.debug("Callback ejecutado exitosamente")
        except Exception as exc:  # pragma: no cover
            self._logger.error(f"Error ejecutando callback: {exc}", exc_info=True)

    @staticmethod
    def _normalize_keys(keys: Iterable[str]) -> List[str]:
        seen: Set[str] = set()
        normalized: List[str] = []
        for key in keys:
            if not isinstance(key, str):
                continue
            stripped = key.strip()
            if not stripped or stripped in seen:
                continue
            seen.add(stripped)
            normalized.append(stripped)
        return normalized


__all__ = ["PumpFunRedisSubscriptions"]
