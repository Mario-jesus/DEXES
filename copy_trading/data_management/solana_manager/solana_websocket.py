# -*- coding: utf-8 -*-
"""
Sistema de websocket optimizado para seguimiento de firmas Solana
Diseñado para trabajar con la cola de análisis de posiciones
"""
import asyncio
import websockets
import json
import socket
from typing import Dict, Set, Optional, Callable, Any, List, Awaitable, Literal
from datetime import datetime

from logging_system import AppLogger
from ..models import WebsocketSubscription, SignatureNotification


class SolanaWebsocketManager:
    """Gestor de websocket único para múltiples suscripciones de firmas"""

    def __init__(self, 
                    ws_url: str = "wss://api.mainnet-beta.solana.com/",
                    max_retries: int = 5,
                    retry_delay: int = 3,
                    heartbeat_interval: int = 30,
                    max_subscriptions: int = 100,
                    max_queue_size: int = 1000):
        self.ws_url = ws_url
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.heartbeat_interval = heartbeat_interval
        self.max_subscriptions = max_subscriptions
        self.max_queue_size = max_queue_size

        self._logger = AppLogger(self.__class__.__name__)

        # Estado de la conexión
        self.websocket: Optional[websockets.ClientConnection] = None
        self.is_connected = False
        self.is_running = False

        # Gestión de suscripciones
        self.subscriptions: Dict[str, WebsocketSubscription] = {}  # signature -> subscription_data
        self.subscription_ids: Dict[int, str] = {}  # subscription_id -> signature
        self.pending_subscriptions: Set[str] = set()

        # Callbacks y handlers
        self.on_signature_confirmed: Optional[Callable[[str, SignatureNotification], Awaitable[None]]] = None
        self.on_signature_timeout: Optional[Callable[[str, int], Awaitable[None]]] = None
        self.on_connection_error: Optional[Callable[[Exception], Awaitable[None]]] = None

        # Tasks
        self.connection_task: Optional[asyncio.Task] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.message_task: Optional[asyncio.Task] = None

        # Contadores y métricas
        # Contador de IDs para requests JSON-RPC (se incrementa por cada request)
        self.next_subscription_id = 1
        self.total_signatures_processed = 0
        self.connection_attempts = 0

        # Control de concurrencia con semáforos
        self.subscription_semaphore = asyncio.Semaphore(max_subscriptions)
        self.pending_subscription_queue: asyncio.Queue[WebsocketSubscription] = asyncio.Queue(maxsize=max_queue_size)
        self.subscription_worker_task: Optional[asyncio.Task] = None

        # Gestión de respuestas RPC (para evitar múltiples recv simultáneos)
        # Mapa de request_id -> Future que será resuelto cuando llegue la respuesta con ese id
        self._pending_requests: Dict[int, asyncio.Future] = {}
        # Contexto auxiliar por request (e.g., tipo y firma asociada)
        self._pending_request_context: Dict[int, Dict[str, Any]] = {}
        # Timeout para esperar ACKs de RPC (suscribe/unsubscribe)
        self._request_response_timeout: int = 15
        # Buffer de notificaciones que llegan antes del ACK de suscripción
        self._pending_notifications: Dict[int, List[SignatureNotification]] = {}

        # Configuración de timeout global
        self.timeout_check_interval = 5  # segundos para verificar timeouts
        self.last_timeout_check = datetime.now()

        self._logger.debug(f"SolanaWebsocketManager inicializado - URL: {ws_url}")

    async def __aenter__(self):
        """Context manager para inicio automático"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager para cierre automático"""
        await self.stop()

    async def start(self):
        """Inicia el gestor de websocket"""
        try:
            self._logger.debug("Iniciando SolanaWebsocketManager")
            self.is_running = True
            self.connection_task = asyncio.create_task(self._connection_worker())
            self.subscription_worker_task = asyncio.create_task(self._subscription_worker())
            self._logger.debug("SolanaWebsocketManager iniciado correctamente")
        except Exception as e:
            self._logger.error(f"Error iniciando SolanaWebsocketManager: {e}")
            raise

    async def stop(self):
        """Detiene el gestor de websocket"""
        try:
            self._logger.debug("Deteniendo SolanaWebsocketManager")
            self.is_running = False

            # Cancelar tasks
            if self.connection_task:
                self.connection_task.cancel()
                try:
                    await self.connection_task
                except asyncio.CancelledError:
                    pass

            if self.heartbeat_task:
                self.heartbeat_task.cancel()
                try:
                    await self.heartbeat_task
                except asyncio.CancelledError:
                    pass

            if self.subscription_worker_task:
                self.subscription_worker_task.cancel()
                try:
                    await self.subscription_worker_task
                except asyncio.CancelledError:
                    pass

            if self.message_task:
                self.message_task.cancel()
                try:
                    await self.message_task
                except asyncio.CancelledError:
                    pass

            # Cerrar websocket
            if self.websocket:
                await self.websocket.close()

            self._logger.debug("SolanaWebsocketManager detenido correctamente")
        except Exception as e:
            self._logger.error(f"Error deteniendo SolanaWebsocketManager: {e}")

    def set_callbacks(self, 
                        on_signature_confirmed: Optional[Callable[[str, SignatureNotification], Awaitable[None]]] = None,
                        on_signature_timeout: Optional[Callable[[str, int], Awaitable[None]]] = None,
                        on_connection_error: Optional[Callable[[Exception], Awaitable[None]]] = None):
        """Configura los callbacks para eventos"""
        if on_signature_confirmed is not None:
            self.on_signature_confirmed = on_signature_confirmed
        if on_signature_timeout is not None:
            self.on_signature_timeout = on_signature_timeout
        if on_connection_error is not None:
            self.on_connection_error = on_connection_error
        self._logger.debug("Callbacks configurados")

    async def subscribe_signature(
        self,
        signature: str,
        *,
        commitment: Literal["finalized", "confirmed", "processed"] = "finalized",
        enable_received_notification: bool = False,
        timeout: int = 60
    ) -> bool:
        """
        Suscribe una firma para seguimiento usando semáforos para control de concurrencia
        
        Args:
            signature: Firma de la transacción
            timeout: Timeout en segundos para la confirmación
            
        Returns:
            bool: True si se agregó a la cola de suscripción
        """
        try:
            if signature in self.subscriptions:
                self._logger.debug(f"Firma {signature} ya está suscrita")
                return True

            # Agregar a la cola de suscripciones pendientes
            await self.pending_subscription_queue.put(WebsocketSubscription(
                signature=signature,
                timeout=timeout,
                queued_at=datetime.now(),
                commitment=commitment,
                enable_received_notification=enable_received_notification
            ))

            self._logger.info(f"Firma {signature} agregada a cola de suscripción (cola: {self.pending_subscription_queue.qsize()})")
            return True

        except Exception as e:
            self._logger.error(f"Error agregando firma {signature} a cola: {e}")
            return False

    async def unsubscribe_signature(self, signature: str) -> bool:
        """Desuscribe una firma del seguimiento y libera el semáforo"""
        try:
            if signature not in self.subscriptions:
                return True

            subscription_data = self.subscriptions[signature]
            subscription_id = subscription_data.subscription_id

            if subscription_id and self.is_connected:
                await self._unsubscribe_signature_immediate(signature, subscription_id)

            # Limpiar datos
            if subscription_id in self.subscription_ids:
                del self.subscription_ids[subscription_id]

            del self.subscriptions[signature]
            self.pending_subscriptions.discard(signature)

            # Liberar el semáforo para permitir una nueva suscripción
            self.subscription_semaphore.release()
            self._logger.info(f"Firma {signature} desuscrita y semáforo liberado")

            return True

        except Exception as e:
            self._logger.error(f"Error desuscribiendo firma {signature}: {e}")
            return False

    async def _subscription_worker(self):
        """Worker que procesa la cola de suscripciones usando semáforos"""
        self._logger.debug("Worker de suscripciones iniciado")

        while self.is_running:
            try:
                # Esperar una suscripción de la cola
                subs_request = await self.pending_subscription_queue.get()

                if not self.is_running:
                    break

                # Esperar un permiso del semáforo
                self._logger.debug(f"Esperando semáforo para firma {subs_request.signature} (cola: {self.pending_subscription_queue.qsize()})")
                await self.subscription_semaphore.acquire()

                # Verificar si la firma ya no está en la cola (puede haber sido removida)
                if subs_request.signature in self.subscriptions:
                    self.subscription_semaphore.release()
                    self._logger.debug(f"Firma {subs_request.signature} ya suscrita, liberando semáforo")
                    continue

                # Agregar a suscripciones activas
                self.pending_subscriptions.add(subs_request.signature)
                self.subscriptions[subs_request.signature] = subs_request

                self._logger.info(f"Firma {subs_request.signature} procesada desde cola (esperó {self.subscriptions[subs_request.signature].wait_time:.6f}s)")

                # Si estamos conectados, suscribir inmediatamente
                if self.is_connected:
                    await self._subscribe_signature_immediate(subs_request.signature)

                # Marcar la tarea como completada
                self.pending_subscription_queue.task_done()

            except asyncio.CancelledError:
                self._logger.debug("Worker de suscripciones cancelado")
                break
            except Exception as e:
                self._logger.error(f"Error en worker de suscripciones: {e}")
                # En caso de error, liberar el semáforo si se adquirió
                if subs_request.signature in self.subscriptions:
                    self.subscription_semaphore.release()
                    del self.subscriptions[subs_request.signature]
                    self.pending_subscriptions.discard(subs_request.signature)

        self._logger.debug("Worker de suscripciones detenido")

    async def _connection_worker(self):
        """Worker principal para manejar la conexión websocket"""
        consecutive_failures = 0

        while self.is_running:
            try:
                self._logger.debug(f"Conectando a {self.ws_url} (intento {consecutive_failures + 1}/{self.max_retries})")
                self.connection_attempts += 1

                async with websockets.connect(
                    self.ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=10,
                    max_size=2**20,  # 1MB
                    max_queue=2**10,  # 1024 mensajes
                    open_timeout=30  # 30 segundos para el handshake
                ) as websocket:
                    self.websocket = websocket
                    self.is_connected = True
                    consecutive_failures = 0

                    self._logger.info("Conexión websocket establecida")

                    # Iniciar heartbeat y lector de mensajes primero
                    self.heartbeat_task = asyncio.create_task(self._heartbeat_worker())
                    self.message_task = asyncio.create_task(self._process_messages())

                    # Suscribir firmas pendientes (ACKs serán gestionados por el lector)
                    await self._subscribe_pending_signatures()

                    # Mantener el contexto de conexión esperando al lector de mensajes
                    await self.message_task

            except websockets.exceptions.ConnectionClosed:
                self._logger.warning("Conexión websocket cerrada")
                consecutive_failures += 1
            except websockets.exceptions.InvalidURI:
                self._logger.error("URL de websocket inválida")
                consecutive_failures += 1
                if self.on_connection_error:
                    await self.on_connection_error(ValueError("Invalid websocket URL"))
            except asyncio.TimeoutError:
                self._logger.error("Timeout durante el handshake de conexión")
                consecutive_failures += 1
                if self.on_connection_error:
                    await self.on_connection_error(TimeoutError("Connection timeout during handshake"))
            except websockets.exceptions.WebSocketException as e:
                self._logger.error(f"Error específico de websocket: {e}")
                consecutive_failures += 1
                if self.on_connection_error:
                    await self.on_connection_error(e)
            except socket.gaierror as e:
                self._logger.error(f"Error de resolución DNS: {e}")
                consecutive_failures += 1
                if self.on_connection_error:
                    await self.on_connection_error(ConnectionError(f"DNS resolution failed: {e}"))
            except ConnectionRefusedError as e:
                self._logger.error(f"Conexión rechazada: {e}")
                consecutive_failures += 1
                if self.on_connection_error:
                    await self.on_connection_error(ConnectionError(f"Connection refused: {e}"))
            except Exception as e:
                self._logger.error(f"Error de conexión websocket: {e}")
                consecutive_failures += 1
                if self.on_connection_error:
                    await self.on_connection_error(e)

            finally:
                self.is_connected = False
                self.websocket = None

                if self.heartbeat_task:
                    self.heartbeat_task.cancel()
                    self.heartbeat_task = None

                if self.message_task:
                    self.message_task.cancel()
                    self.message_task = None

            # Verificar si se alcanzó el máximo de reintentos
            if consecutive_failures >= self.max_retries:
                self._logger.error(f"Máximo de reintentos alcanzado ({self.max_retries}). Deteniendo worker de conexión.")

                # Notificar error crítico
                if self.on_connection_error:
                    await self.on_connection_error(
                        TimeoutError(f"Maximum number of connection retries reached: {self.max_retries}")
                    )

                # Detener completamente
                self.is_running = False
                break

            # Reintento con backoff exponencial
            if self.is_running:
                delay = min(self.retry_delay * (2 ** consecutive_failures), 60)
                self._logger.debug(f"Reintentando conexión en {delay} segundos (fallos consecutivos: {consecutive_failures})")
                await asyncio.sleep(delay)

    async def _subscribe_pending_signatures(self):
        """Suscribe todas las firmas pendientes que ya tienen semáforo"""
        for signature in list(self.pending_subscriptions):
            if signature in self.subscriptions and self.subscriptions[signature].status == 'pending':
                await self._subscribe_signature_immediate(signature)

    async def _subscribe_signature_immediate(self, signature: str):
        """Suscribe una firma inmediatamente"""
        try:
            subscription_data = self.subscriptions[signature]
            timeout = subscription_data.timeout

            # Crear mensaje de suscripción
            # Preparar request con ID único
            request_id = self._get_next_request_id()

            sub_msg = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "signatureSubscribe",
                "params": [
                    signature,
                    {
                        "commitment": subscription_data.commitment,
                        "enableReceivedNotification": subscription_data.enable_received_notification
                    }
                ]
            }

            if self.websocket is None:
                raise RuntimeError("Websocket no está conectado")

            # Crear future para esperar la respuesta del mismo hilo lector
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending_requests[request_id] = future
            self._pending_request_context[request_id] = {"type": "subscribe", "signature": signature}

            await self.websocket.send(json.dumps(sub_msg))

            # Esperar ACK de suscripción sin llamar a recv directamente (evita concurrencia)
            try:
                ack: Dict[str, Any] = await asyncio.wait_for(future, timeout=self._request_response_timeout)
            finally:
                # Limpiar contexto del request
                self._pending_requests.pop(request_id, None)
                self._pending_request_context.pop(request_id, None)

            if isinstance(ack, dict) and "result" in ack:
                subscription_id = ack["result"]
                subscription_data.subscription_id = subscription_id
                subscription_data.status = 'subscribed'
                subscription_data.subscribed_at = datetime.now()
                try:
                    subscription_data.wait_time = (subscription_data.subscribed_at - subscription_data.queued_at).total_seconds()
                except Exception:
                    pass
                self.subscription_ids[subscription_id] = signature
                self.pending_subscriptions.discard(signature)

                self._logger.info(f"Firma {signature} suscrita con ID {subscription_id}")
                # Procesar notificaciones que hayan llegado antes del ACK
                await self._flush_pending_notifications(subscription_id)
            else:
                self._logger.error(f"Error suscribiendo firma {signature}: {ack}")
                # Rollback de estructuras para no perder semáforo ni dejar estado inconsistente
                try:
                    if signature in self.subscriptions:
                        del self.subscriptions[signature]
                    self.pending_subscriptions.discard(signature)
                    self.subscription_semaphore.release()
                except Exception:
                    pass

        except Exception as e:
            self._logger.error(f"Error en suscripción inmediata de {signature}: {e}")

    async def _unsubscribe_signature_immediate(self, signature: str, subscription_id: int):
        """Desuscribe una firma inmediatamente"""
        try:
            request_id = self._get_next_request_id()

            unsubscribe_msg = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "signatureUnsubscribe",
                "params": [subscription_id]
            }

            if self.websocket is None:
                raise RuntimeError("Websocket no está conectado")

            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending_requests[request_id] = future
            self._pending_request_context[request_id] = {"type": "unsubscribe", "signature": signature, "subscription_id": subscription_id}

            await self.websocket.send(json.dumps(unsubscribe_msg))

            try:
                ack: Dict[str, Any] = await asyncio.wait_for(future, timeout=self._request_response_timeout)
                self._logger.debug(f"Firma {signature} desuscrita ACK: {ack}")
            except asyncio.TimeoutError:
                self._logger.warning(f"Timeout esperando ACK de desuscripción para {signature} (sub_id={subscription_id})")
            finally:
                self._pending_requests.pop(request_id, None)
                self._pending_request_context.pop(request_id, None)

        except Exception as e:
            self._logger.error(f"Error desuscribiendo firma {signature}: {e}")

    async def _process_messages(self):
        """Procesa mensajes entrantes del websocket con timeout global"""
        try:
            while self.is_connected and self.is_running:
                if self.websocket is None:
                    break

                try:
                    # Usar timeout para esperar mensajes
                    async with asyncio.timeout(self.timeout_check_interval):
                        message = await self.websocket.recv()
                        await self._handle_message(message)

                except asyncio.TimeoutError:
                    # Verificar firmas expiradas cuando no hay mensajes
                    await self._check_expired_signatures()

        except websockets.exceptions.ConnectionClosed:
            self._logger.debug("Conexión cerrada durante procesamiento de mensajes")
        except Exception as e:
            self._logger.error(f"Error procesando mensajes: {e}")

    async def _handle_message(self, message: websockets.Data):
        """Maneja un mensaje individual"""
        try:
            # Parsear JSON primero
            json_data = json.loads(message)

            # Verificar si es un mensaje de notificación de firma
            if json_data.get("method") == "signatureNotification":
                try:
                    self._logger.debug(f"Signature notification: {json_data}")
                    data = SignatureNotification.from_dict(json_data)
                    await self._handle_signature_notification(data)
                except Exception as e:
                    self._logger.error(f"Error procesando notificación de firma: {e}")
                    self._logger.debug(f"Mensaje problemático: {json_data}")
            # Respuestas JSON-RPC a requests previos (suscribe/unsubscribe)
            elif "id" in json_data:
                request_id = json_data.get("id")
                fut = self._pending_requests.get(request_id)
                if fut and not fut.done():
                    fut.set_result(json_data)
                    self._logger.debug(f"Respuesta RPC recibida para id={request_id}: {json_data}")
                else:
                    self._logger.debug(f"Respuesta RPC sin future asociado o duplicada: {json_data}")
            else:
                # Loggear otros tipos de mensajes para debugging
                self._logger.debug(f"Mensaje recibido (no procesado): {json_data}")

        except json.JSONDecodeError as e:
            self._logger.error(f"Error decodificando mensaje JSON: {e}")
            self._logger.debug(f"Mensaje raw: {message}")
        except Exception as e:
            self._logger.error(f"Error manejando mensaje: {e}")
            self._logger.debug(f"Mensaje raw: {message}")

    async def _handle_signature_notification(self, data: SignatureNotification):
        """Maneja notificación de confirmación de firma"""
        try:
            # Obtener el subscription_id del mensaje
            subscription_id = data.params.subscription

            if not subscription_id or subscription_id not in self.subscription_ids:
                # Guardar notificación en buffer para procesarla cuando llegue el ACK
                if subscription_id is not None:
                    self._pending_notifications.setdefault(subscription_id, []).append(data)
                    self._logger.debug(f"Notificación para subscription {subscription_id} en buffer (sin ACK aún)")
                else:
                    self._logger.warning(f"Subscription ID {subscription_id} inválido en notificación")
                return

            # Obtener la firma usando el subscription_id
            signature = self.subscription_ids[subscription_id]

            if signature not in self.subscriptions:
                self._logger.warning(f"Firma {signature} no encontrada en suscripciones")
                return

            subscription_data = self.subscriptions[signature]

            # Si es solo notificación de recepción, no confirmar aún
            if data.is_received_signature:
                self._logger.debug(f"Firma {signature} recibida por red (receivedSignature)")
                return

            # Confirmar solo cuando no hay error
            if data.error is None:
                subscription_data.status = 'confirmed'
                subscription_data.confirmed_at = datetime.now()

                self.total_signatures_processed += 1

                self._logger.info(f"Firma {signature} confirmada")

                # Llamar callback
                if self.on_signature_confirmed:
                    await self.on_signature_confirmed(signature, data)

                # Limpiar datos de suscripción (Solana ya canceló automáticamente)
                await self._cleanup_confirmed_signature(signature)
            else:
                # En caso de error, limpiar y liberar semáforo igualmente
                self._logger.warning(f"Firma {signature} con error reportado en notificación: {data.error}")
                await self._cleanup_timeout_signature(signature)

        except Exception as e:
            self._logger.error(f"Error manejando notificación de firma: {e}")

    def _get_next_request_id(self) -> int:
        """Obtiene un ID incremental para requests JSON-RPC."""
        request_id = self.next_subscription_id
        self.next_subscription_id += 1
        # Evitar overflow absurdo, reiniciar si es muy grande (manteniendo > 0)
        if self.next_subscription_id > 2**31:
            self.next_subscription_id = 1
        return request_id

    async def _flush_pending_notifications(self, subscription_id: int):
        """Procesa notificaciones almacenadas que llegaron antes del ACK."""
        pending = self._pending_notifications.pop(subscription_id, None)
        if not pending:
            return
        for notif in pending:
            try:
                await self._handle_signature_notification(notif)
            except Exception as e:
                self._logger.error(f"Error procesando notificación en buffer para sub {subscription_id}: {e}")

    async def _cleanup_confirmed_signature(self, signature: str):
        """Limpia los datos de una firma confirmada sin desuscripción manual"""
        try:
            if signature not in self.subscriptions:
                return

            subscription_data = self.subscriptions[signature]

            # Limpiar datos de suscripción
            subscription_id = subscription_data.subscription_id
            if subscription_id in self.subscription_ids:
                del self.subscription_ids[subscription_id]

            del self.subscriptions[signature]
            self.pending_subscriptions.discard(signature)

            # Liberar el semáforo para permitir una nueva suscripción
            self.subscription_semaphore.release()

            self._logger.debug(f"Firma {signature} limpiada (Solana canceló automáticamente)")

        except Exception as e:
            self._logger.error(f"Error limpiando firma confirmada {signature}: {e}")

    async def _check_expired_signatures(self):
        """Verifica y procesa firmas expiradas usando timeout global"""
        try:
            current_time = datetime.now()
            expired_signatures = []

            # Verificar firmas que han expirado
            for signature, subscription_data in self.subscriptions.items():
                if subscription_data.status == 'subscribed':
                    elapsed_time = (current_time - subscription_data.subscribed_at).total_seconds()
                    if elapsed_time > subscription_data.timeout:
                        expired_signatures.append(signature)

            # Procesar firmas expiradas
            for signature in expired_signatures:
                await self._handle_signature_timeout(signature)

            # Actualizar último check
            self.last_timeout_check = current_time

            if expired_signatures:
                self._logger.debug(f"Procesadas {len(expired_signatures)} firmas expiradas")

        except Exception as e:
            self._logger.error(f"Error verificando firmas expiradas: {e}")

    async def _handle_signature_timeout(self, signature: str):
        """Maneja el timeout de una firma específica"""
        try:
            if signature not in self.subscriptions:
                return

            subscription_data = self.subscriptions[signature]

            if subscription_data.status == 'subscribed':
                subscription_data.status = 'timeout'

                elapsed_time = (datetime.now() - subscription_data.subscribed_at).total_seconds()
                self._logger.warning(f"Timeout para firma {signature} después de {elapsed_time:.1f}s")

                # Llamar callback de timeout
                if self.on_signature_timeout:
                    await self.on_signature_timeout(signature, int(elapsed_time))

                # Limpiar datos de suscripción
                await self._cleanup_timeout_signature(signature)

        except Exception as e:
            self._logger.error(f"Error manejando timeout de firma {signature}: {e}")

    async def _cleanup_timeout_signature(self, signature: str):
        """Limpia los datos de una firma que expiró por timeout"""
        try:
            if signature not in self.subscriptions:
                return

            subscription_data = self.subscriptions[signature]

            # Limpiar datos de suscripción
            subscription_id = subscription_data.subscription_id
            if subscription_id in self.subscription_ids:
                del self.subscription_ids[subscription_id]

            del self.subscriptions[signature]
            self.pending_subscriptions.discard(signature)

            # Liberar el semáforo para permitir una nueva suscripción
            self.subscription_semaphore.release()

            self._logger.debug(f"Firma {signature} limpiada por timeout")

        except Exception as e:
            self._logger.error(f"Error limpiando firma por timeout {signature}: {e}")

    async def _heartbeat_worker(self):
        """Worker para mantener la conexión activa"""
        try:
            while self.is_connected and self.is_running:
                await asyncio.sleep(self.heartbeat_interval)

                if self.is_connected and self.websocket is not None:
                    # Enviar ping para mantener conexión
                    try:
                        pong_waiter = await self.websocket.ping()
                        await pong_waiter
                        self._logger.debug("Heartbeat enviado")
                    except Exception as e:
                        self._logger.warning(f"Error en heartbeat: {e}")
                        break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._logger.error(f"Error en heartbeat worker: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Obtiene estadísticas del gestor"""
        return {
            'is_connected': self.is_connected,
            'is_running': self.is_running,
            'total_subscriptions': len(self.subscriptions),
            'pending_subscriptions': len(self.pending_subscriptions),
            'queue_size': self.pending_subscription_queue.qsize(),
            'semaphore_available': self.subscription_semaphore._value,
            'semaphore_locked': self.max_subscriptions - self.subscription_semaphore._value,
            'total_signatures_processed': self.total_signatures_processed,
            'connection_attempts': self.connection_attempts,
            'max_subscriptions': self.max_subscriptions,
            'max_queue_size': self.max_queue_size
        }

    async def get_active_signatures(self) -> Set[str]:
        """Obtiene las firmas activamente suscritas"""
        return set(self.subscriptions.keys())

    async def get_queued_signatures(self) -> List[Dict[str, Any]]:
        """Obtiene información sobre las firmas en cola de espera"""
        try:
            queued_info = []
            current_time = datetime.now()

            # Obtener elementos de la cola sin removerlos
            queue_items: List[WebsocketSubscription] = []
            temp_queue: asyncio.Queue[WebsocketSubscription] = asyncio.Queue()

            while not self.pending_subscription_queue.empty():
                item = await self.pending_subscription_queue.get()
                queue_items.append(item)
                await temp_queue.put(item)
                # Marcar como completada en la cola original
                self.pending_subscription_queue.task_done()

            # Restaurar la cola
            while not temp_queue.empty():
                item = await temp_queue.get()
                await self.pending_subscription_queue.put(item)
                # Marcar como completada en la cola temporal
                temp_queue.task_done()

            for item in queue_items:
                wait_time = (current_time - item.queued_at).total_seconds()
                queued_info.append({
                    'signature': item.signature,
                    'timeout': item.timeout,
                    'wait_time_seconds': wait_time,
                    'requested_at': item.queued_at.isoformat()
                })

            return queued_info

        except Exception as e:
            self._logger.error(f"Error obteniendo firmas en cola: {e}")
            return []

    async def clear_all_subscriptions(self):
        """Limpia todas las suscripciones"""
        try:
            signatures = list(self.subscriptions.keys())
            for signature in signatures:
                await self.unsubscribe_signature(signature)

            # Limpiar cola de espera
            while not self.pending_subscription_queue.empty():
                try:
                    self.pending_subscription_queue.get_nowait()
                    self.pending_subscription_queue.task_done()
                except asyncio.QueueEmpty:
                    break

            self._logger.info(f"Todas las suscripciones limpiadas ({len(signatures)} firmas)")
        except Exception as e:
            self._logger.error(f"Error limpiando suscripciones: {e}")

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Obtiene métricas detalladas de rendimiento del sistema de semáforos"""
        try:
            # Calcular tiempos de espera promedio
            wait_times = []
            for subscription_data in self.subscriptions.values():
                if subscription_data.wait_time:
                    wait_times.append(subscription_data.wait_time)

            avg_wait_time = sum(wait_times) / len(wait_times) if wait_times else 0

            # Obtener firmas en cola
            queued_signatures = await self.get_queued_signatures()
            queued_wait_times = [item['wait_time_seconds'] for item in queued_signatures]
            avg_queued_wait_time = sum(queued_wait_times) / len(queued_wait_times) if queued_wait_times else 0

            return {
                'active_subscriptions': len(self.subscriptions),
                'queued_subscriptions': len(queued_signatures),
                'semaphore_utilization': (self.max_subscriptions - self.subscription_semaphore._value) / self.max_subscriptions * 100,
                'average_wait_time_seconds': avg_wait_time,
                'average_queued_wait_time_seconds': avg_queued_wait_time,
                'max_wait_time_seconds': max(wait_times) if wait_times else 0,
                'max_queued_wait_time_seconds': max(queued_wait_times) if queued_wait_times else 0,
                'total_processed': self.total_signatures_processed,
                'queue_efficiency': len(self.subscriptions) / (len(self.subscriptions) + len(queued_signatures)) * 100 if (len(self.subscriptions) + len(queued_signatures)) > 0 else 100
            }
        except Exception as e:
            self._logger.error(f"Error obteniendo métricas de rendimiento: {e}")
            return {}
