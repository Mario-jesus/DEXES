# -*- coding: utf-8 -*-
"""
PumpFun API Client - Cliente centralizado para todas las llamadas a APIs
con soporte async/await, WebSocket y HTTP
"""
import asyncio, aiohttp, json, websockets, time, random
from typing import Dict, Any, Optional, Union, Type, Tuple, Callable, List, TYPE_CHECKING
from solders.commitment_config import CommitmentLevel
from solders.rpc.requests import SendVersionedTransaction
from solders.rpc.config import RpcSendTransactionConfig
from enum import Enum
from logging_system import AppLogger


if TYPE_CHECKING:
    from io import BufferedReader
    from types import TracebackType
    from solders.transaction import VersionedTransaction


class RequestMethod(Enum):
    """Métodos HTTP disponibles"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"

class WebSocketMethod(Enum):
    """Métodos WebSocket disponibles"""
    SUBSCRIBE_NEW_TOKEN = "subscribeNewToken"
    SUBSCRIBE_MIGRATION = "subscribeMigration"
    SUBSCRIBE_ACCOUNT_TRADE = "subscribeAccountTrade"
    SUBSCRIBE_TOKEN_TRADE = "subscribeTokenTrade"


class ApiClientException(Exception):
    """Excepción base para el cliente API"""
    pass


class WebSocketConnectionError(ApiClientException):
    """Error de conexión WebSocket"""
    pass


class HttpRequestError(ApiClientException):
    """Error de petición HTTP"""
    pass


class PumpFunHttpApiClient():
    """
    Cliente centralizado para todas las APIs de PumpFun
    con soporte async/await
    """

    def __init__(
        self,
        http_base_url: str = "https://pumpportal.fun/api",
        api_key: Optional[str] = None,
        max_connections: int = 10,
        http_timeout: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        """
        Inicializa el cliente API
        
        Args:
            http_base_url: URL base para peticiones HTTP
            api_key: API key para autenticación
            max_connections: Máximo número de conexiones HTTP
            http_timeout: Timeout para HTTP (segundos)
            max_retries: Máximo número de reintentos
            retry_delay: Delay base entre reintentos
        """
        self._http_base_url = http_base_url
        self._api_key = api_key
        self._max_connections = max_connections
        self._http_timeout = http_timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._http_session = None

        self._lock = asyncio.Lock()
        self._is_running = False

        # Logging
        self._logger = AppLogger(self.__class__.__name__)

        # Métricas básicas
        self._metrics: Dict[str, Any] = {
            'request_count': 0,
            'error_count': 0,
            'success_count': 0,
            'total_response_time_ms': 0.0,
            'first_request_time': None,
            'last_request_time': None
        }

    async def __aenter__(self):
        """Context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional["TracebackType"]):
        """Context manager exit"""
        await self.disconnect()

    @property
    def is_running(self) -> bool:
        return self._is_running

    # ============================================================================
    # MÉTODOS DE CONEXIÓN
    # ============================================================================

    async def connect(self):
        if self._is_running and self._http_session and not self._http_session.closed:
            return

        async with self._lock:
            if self._http_session and not self._http_session.closed:
                self._is_running = True
                return

            try:
                connector = aiohttp.TCPConnector(
                    limit=self._max_connections,
                    limit_per_host=self._max_connections,
                    ttl_dns_cache=300,
                    use_dns_cache=True
                )

                timeout = aiohttp.ClientTimeout(total=self._http_timeout)

                self._http_session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                    headers={
                        'User-Agent': 'PumpFun-Http-Api-Client/1.0',
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    }
                )

                self._is_running = True

                self._logger.info("Sesión HTTP inicializada")

            except Exception as e:
                self._logger.error(f"Error inicializando HTTP: {e}")
                raise HttpRequestError(f"Error inicializando HTTP: {e}")

    async def disconnect(self):
        async with self._lock:
            try:
                if self._http_session and not self._http_session.closed:
                    await self._http_session.close()
                    self._http_session = None
                    self._is_running = False

                self._logger.info("Sesión HTTP cerrada")

            except Exception as e:
                self._logger.error(f"Error cerrando HTTP: {e}")

    # ============================================================================
    # MÉTODOS GENÉRICOS DE PETICIÓN
    # ============================================================================

    async def http_request(self,
        *,
        method: Union[RequestMethod, str],
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        use_api_key: bool = False,
        return_json: bool = True,
        files: Optional[Dict[str, Any]] = None,
        url: Optional[str] = None,
        **kwargs: Any
    ) -> Optional[Union[Dict[str, Any], bytes]]:
        """
        Petición HTTP genérica (GET, POST, etc.)
        """
        try:

            self._metrics['request_count'] += 1
            request_start_time = time.time()

            if self._metrics['first_request_time'] is None:
                self._metrics['first_request_time'] = request_start_time

            if not self._http_session or not self._is_running:
                raise HttpRequestError("Sesión HTTP no disponible")

            # Construir URL
            if url:
                request_url = url
            else:
                request_url = f"{self._http_base_url}/{endpoint.lstrip('/')}" if endpoint else self._http_base_url

            # Preparar parámetros, incluyendo la API key si es necesario
            request_params = params.copy() if params else {}
            if use_api_key and self._api_key:
                request_params['api-key'] = self._api_key

            # Preparar argumentos
            request_kwargs: Dict[str, Any] = {
                'url': request_url,
                'params': request_params,
                'headers': headers or {},
                **kwargs
            }

            # Manejar datos según tipo
            if files:
                # Upload de archivos
                request_kwargs['data'] = data
                request_kwargs['files'] = files
            else:
                # Datos JSON normales
                request_kwargs['json'] = data

            # Implementar reintentos con backoff exponencial
            for attempt in range(1, self._max_retries + 1):
                try:
                    async with self._http_session.request(
                        method.value if isinstance(method, RequestMethod) else method,
                        **request_kwargs
                    ) as response:
                        # Registrar tiempo de respuesta
                        response_time_ms = (time.time() - request_start_time) * 1000
                        self._metrics['total_response_time_ms'] += response_time_ms
                        self._metrics['last_request_time'] = time.time()

                        if response.status == 200:
                            self._metrics['success_count'] += 1
                            if return_json:
                                return await response.json()
                            else:
                                return await response.read()
                        else:
                            self._metrics['error_count'] += 1
                            error_text = await response.text()
                            raise HttpRequestError(f"HTTP {response.status}: {error_text}")
                except Exception as e:
                    if attempt < self._max_retries:
                        delay = self._retry_delay * (2 ** (attempt - 1))
                        self._logger.warning(f"Reintentando HTTP en {delay}s... (intento {attempt}/{self._max_retries})")
                        await asyncio.sleep(delay)
                    else:
                        raise HttpRequestError(f"Error HTTP después de {self._max_retries} intentos: {e}")
        except Exception as e:
            self._metrics['error_count'] += 1
            self._logger.error(f"Error en petición: {e}")
            raise

    async def _http_request_files(self,
        *,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Tuple[str, "BufferedReader", str]]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        use_api_key: bool = False,
        url: Optional[str] = None,
        **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Petición HTTP con archivos usando aiohttp.FormData
        """
        try:

            self._metrics['request_count'] += 1
            request_start_time = time.time()

            if self._metrics['first_request_time'] is None:
                self._metrics['first_request_time'] = request_start_time

            if not self._http_session or self._http_session.closed:
                raise HttpRequestError("Sesión HTTP no disponible")

            # Construir URL
            if url:
                request_url = url
            else:
                request_url = f"{self._http_base_url}/{endpoint.lstrip('/')}" if endpoint else self._http_base_url

            # Preparar headers
            request_headers = headers or {}
            if use_api_key and self._api_key:
                request_headers['Authorization'] = f'Bearer {self._api_key}'

            # Crear FormData
            form_data = aiohttp.FormData()

            # Añadir datos de formulario
            if data:
                for key, value in data.items():
                    form_data.add_field(key, str(value))

            # Añadir archivos
            if files:
                for field_name, file_data in files.items():
                    if len(file_data) >= 2:
                        filename, content = file_data[0], file_data[1]
                        content_type = file_data[2] if len(file_data) > 2 else 'application/octet-stream'

                        # Manejar tanto archivos abiertos como contenido binario
                        if hasattr(content, 'read'):
                            # Es un archivo abierto
                            form_data.add_field(field_name, content, filename=filename, content_type=content_type)
                        else:
                            # Es contenido binario
                            form_data.add_field(field_name, content, filename=filename, content_type=content_type)
                    else:
                        form_data.add_field(field_name, file_data)

            # Implementar reintentos con backoff exponencial
            for attempt in range(1, self._max_retries + 1):
                try:
                    async with self._http_session.post(
                        request_url,
                        data=form_data,
                        params=params,
                        headers=request_headers,
                        **kwargs
                    ) as response:
                        # Registrar tiempo de respuesta
                        response_time_ms = (time.time() - request_start_time) * 1000
                        self._metrics['total_response_time_ms'] += response_time_ms
                        self._metrics['last_request_time'] = time.time()

                        if response.status == 200:
                            self._metrics['success_count'] += 1
                            return await response.json()
                        else:
                            self._metrics['error_count'] += 1
                            error_text = await response.text()
                            raise HttpRequestError(f"HTTP {response.status}: {error_text}")

                except Exception as e:
                    if attempt < self._max_retries:
                        delay = self._retry_delay * (2 ** (attempt - 1))
                        self._logger.warning(f"Reintentando HTTP en {delay}s... (intento {attempt}/{self._max_retries})")
                        await asyncio.sleep(delay)
                    else:
                        raise HttpRequestError(f"Error HTTP después de {self._max_retries} intentos: {e}")
        except Exception as e:
            self._metrics['error_count'] += 1
            self._logger.error(f"Error en petición: {e}")
            raise

    # ============================================================================
    # MÉTODOS DE CONVENIENCIA
    # ============================================================================

    async def http_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, use_api_key: bool = False, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Petición HTTP GET"""
        result = await self.http_request(method=RequestMethod.GET, endpoint=endpoint, params=params, use_api_key=use_api_key, **kwargs)
        return result if isinstance(result, dict) else None

    async def http_post(self, endpoint: str, data: Optional[Dict[str, Any]] = None, use_api_key: bool = False, url: Optional[str] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Petición HTTP POST"""
        result = await self.http_request(method=RequestMethod.POST, endpoint=endpoint, data=data, use_api_key=use_api_key, url=url, **kwargs)
        return result if isinstance(result, dict) else None

    async def http_post_files(self, endpoint: str, data: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None, use_api_key: bool = False, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Petición HTTP POST con archivos"""
        return await self._http_request_files(endpoint=endpoint, data=data, files=files, use_api_key=use_api_key, **kwargs)

    async def http_post_raw(self, endpoint: str, data: Optional[Dict[str, Any]] = None, use_api_key: bool = False, **kwargs: Any) -> Optional[bytes]:
        """Petición HTTP POST que devuelve bytes crudos"""
        result = await self.http_request(method=RequestMethod.POST, endpoint=endpoint, data=data, use_api_key=use_api_key, return_json=False, **kwargs)
        return result if isinstance(result, bytes) else None

    async def send_signed_transaction(self, signed_tx: "VersionedTransaction", rpc_endpoint: str) -> str:
        """
        Envía una transacción firmada a un endpoint RPC de Solana
        
        Args:
            signed_tx: La transacción VersionedTransaction ya firmada
            rpc_endpoint: El endpoint RPC de Solana al que se enviará la transacción
            
        Returns:
            La firma de la transacción como string
        """
        if not self._http_session:
            await self.connect()

        commitment = CommitmentLevel.Confirmed
        config = RpcSendTransactionConfig(preflight_commitment=commitment)
        payload = SendVersionedTransaction(signed_tx, config).to_json()

        if not self._http_session:
            raise HttpRequestError("Sesión HTTP no disponible")

        async with self._http_session.post(rpc_endpoint, data=payload, headers={"Content-Type": "application/json"}) as response:
            if response.status == 200:
                result = await response.json()
                return result.get('result')
            else:
                error_text = await response.text()
                raise HttpRequestError(f"Error enviando transacción a {rpc_endpoint}: HTTP {response.status} - {error_text}")

    # ============================================================================
    # MÉTODOS DE ESTADO Y MÉTRICAS
    # ============================================================================

    def get_status(self) -> Dict[str, Any]:
        """Obtiene estado actual del cliente"""

        # Calcular métricas derivadas
        total_requests = self._metrics['request_count'] or 0
        success_count = self._metrics['success_count'] or 0
        total_response_time = self._metrics['total_response_time_ms'] or 0.0

        success_rate = (success_count / max(1, total_requests)) * 100
        avg_response_time = 0.0
        if total_requests > 0:
            avg_response_time = total_response_time / total_requests

        # Calcular uptime
        uptime_seconds = 0
        if self._metrics['first_request_time'] is not None:
            uptime_seconds = time.time() - self._metrics['first_request_time']

        return {
            'http_session_active': self._http_session is not None and not self._http_session.closed,
            'is_running': self._is_running,
            'api_key_configured': bool(self._api_key),
            'request_count': total_requests,
            'success_count': self._metrics['success_count'],
            'error_count': self._metrics['error_count'],
            'success_rate_percent': round(success_rate, 2),
            'avg_response_time_ms': round(avg_response_time, 2),
            'uptime_seconds': round(uptime_seconds, 2),
            'first_request_time': self._metrics['first_request_time'],
            'last_request_time': self._metrics['last_request_time']
        }

    def reset_metrics(self):
        """Resetea métricas del cliente"""
        self._metrics['request_count'] = 0
        self._metrics['error_count'] = 0
        self._metrics['success_count'] = 0
        self._metrics['total_response_time_ms'] = 0.0
        self._metrics['first_request_time'] = None
        self._metrics['last_request_time'] = None

        self._logger.info("Métricas del cliente reseteadas")


class PumpFunWebSocketApiClient():
    """
    Cliente centralizado para todas las APIs de PumpFun
    con soporte async/await
    """

    def __init__(self, 
        websocket_base_url: str = "wss://pumpportal.fun/api/data",
        api_key: Optional[str] = None,
        websocket_timeout: int = 60,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        inactivity_watch_seconds: int = 3600,
        # Parámetros para reconexión exponencial
        max_reconnect_attempts: int = 10,
        base_reconnect_delay: float = 15.0,
        max_reconnect_delay: float = 300.0,
        reconnect_jitter: bool = True
    ):
        """
        Inicializa el cliente API
        
        Args:
            websocket_base_url: URL del WebSocket
            api_key: API key para autenticación
            websocket_timeout: Timeout para WebSocket (segundos)
            max_retries: Máximo número de reintentos
            retry_delay: Delay base entre reintentos
            inactivity_watch_seconds: Segundos de inactividad antes de reconectar
            max_reconnect_attempts: Máximo número de intentos de reconexión exponencial
            base_reconnect_delay: Delay base para reconexión exponencial (segundos)
            max_reconnect_delay: Delay máximo para reconexión exponencial (segundos)
            reconnect_jitter: Si True, añade jitter aleatorio para evitar thundering herd
        """
        self._websocket_base_url = websocket_base_url
        self._api_key = api_key
        self._websocket_timeout = websocket_timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # Parámetros de reconexión exponencial
        self._max_reconnect_attempts = max_reconnect_attempts
        self._base_reconnect_delay = base_reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._reconnect_jitter = reconnect_jitter

        self._websocket = None
        self._websocket_callbacks: Dict[str, Callable[[Any], Any]] = {}
        self._websocket_subscriptions: set[str] = set()
        self._listener_task: Optional[asyncio.Task[Any]] = None
        self._inactivity_task: Optional[asyncio.Task[Any]] = None

        self._is_running = False
        self._is_reconnecting = False
        self._reconnect_attempts = 0

        self._logger = AppLogger(self.__class__.__name__)

        # Config watchdog
        self._inactivity_watch_seconds = inactivity_watch_seconds

        # Métricas básicas
        self._metrics: Dict[str, Any] = {
            'connection_attempts': 0,
            'error_count': 0,
            'message_count': 0,
            'subscription_count': 0,
            'callback_count': 0,
            'total_response_time_ms': 0.0,
            'first_connection_time': None,
            'last_message_time': None,
            'reconnect_count': 0,
            'reconnect_attempts': 0,
            'exponential_reconnect_count': 0,
            'ping_count': 0,
            'ping_failures': 0,
            'ping_reconnects': 0,
            'inactivity_reconnects': 0,
            'inactivity_last_check': None,
            'inactivity_triggered': False,
            'last_reconnect_reason': None,
            'last_reconnect_time': None,
            # Métricas de trades
            'trade_count': 0,
            'last_trade_time': None,
            'total_trade_intervals': 0.0,
            'min_trade_interval': float('inf'),
            'max_trade_interval': 0.0
        }

    async def __aenter__(self):
        """Context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional["TracebackType"]):
        """Context manager exit"""
        await self.disconnect()

    @property
    def is_running(self) -> bool:
        return self._is_running

    # ============================================================================
    # MÉTODOS DE CONEXIÓN
    # ============================================================================

    def _calculate_exponential_delay(self, attempt: int) -> float:
        """
        Calcula el delay exponencial con jitter para reconexión
        
        Args:
            attempt: Número de intento (0-based)
            
        Returns:
            Delay en segundos
        """
        # Calcular delay exponencial: base_delay * (2^attempt)
        exponential_delay = self._base_reconnect_delay * (2 ** attempt)

        # Limitar al máximo configurado
        delay = min(exponential_delay, self._max_reconnect_delay)

        # Añadir jitter si está habilitado (hasta 25% de variación)
        if self._reconnect_jitter:
            jitter_factor = random.uniform(0.75, 1.25)
            delay *= jitter_factor

        return delay

    async def connect(self):
        if self._is_running:
            return

        # Implementar reconexión exponencial
        for attempt in range(self._max_reconnect_attempts):
            try:
                self._metrics['connection_attempts'] += 1
                self._reconnect_attempts = attempt

                if self._metrics['first_connection_time'] is None:
                    self._metrics['first_connection_time'] = time.time()

                # Construir URL con o sin API key
                ws_url = self._websocket_base_url
                if self._api_key:
                    ws_url = f"{self._websocket_base_url}?api-key={self._api_key}"

                self._logger.debug(f"Conectando WebSocket... (intento {attempt + 1}/{self._max_reconnect_attempts})")
                if self._api_key:
                    self._logger.debug(f"Usando API key para PumpSwap data")

                async with asyncio.timeout(self._websocket_timeout):
                    self._websocket = await websockets.connect(
                            ws_url,
                            ping_interval=20,
                            ping_timeout=10,
                            close_timeout=10
                        )

                self._is_running = True
                self._reconnect_attempts = 0  # Resetear contador en conexión exitosa

                # Iniciar listener en background
                self._listener_task = asyncio.create_task(self._websocket_listener())
                # Iniciar watchdog de inactividad
                if self._inactivity_task and not self._inactivity_task.done():
                    try:
                        self._inactivity_task.cancel()
                        await self._inactivity_task
                    except Exception:
                        pass
                self._inactivity_task = asyncio.create_task(self._inactivity_watchdog())

                self._logger.info(f"WebSocket conectado exitosamente en intento {attempt + 1}")
                return  # Conexión exitosa, salir del bucle

            except Exception as e:
                self._metrics['error_count'] += 1
                self._metrics['exponential_reconnect_count'] += 1

                if attempt < self._max_reconnect_attempts - 1:
                    # Calcular delay exponencial con jitter
                    delay = self._calculate_exponential_delay(attempt)
                    self._logger.warning(f"Error conectando WebSocket (intento {attempt + 1}/{self._max_reconnect_attempts}): {e}")
                    self._logger.info(f"Reintentando en {delay:.2f} segundos...")
                    await asyncio.sleep(delay)
                else:
                    # Último intento fallido
                    self._logger.error(f"Error conectando WebSocket después de {self._max_reconnect_attempts} intentos: {e}")
                    raise WebSocketConnectionError(f"Error conectando WebSocket después de {self._max_reconnect_attempts} intentos: {e}")

    async def disconnect(self):
        try:
            if self._listener_task:
                self._listener_task.cancel()
                try:
                    await self._listener_task
                except asyncio.CancelledError:
                    pass
            if self._inactivity_task:
                self._inactivity_task.cancel()
                try:
                    await self._inactivity_task
                except asyncio.CancelledError:
                    pass

            await self._unsubscribe_all_events()

            if self._websocket:
                await self._websocket.close()
                self._websocket = None

            self._is_running = False

            # WebSocket desconectado
        except Exception as e:
            self._logger.error(f"Error desconectando WebSocket: {e}")

    # ============================================================================
    # MÉTODOS AUXILIARES DE MÉTRICAS
    # ============================================================================

    def _update_trade_metrics(self):
        """Actualiza métricas de trades"""
        current_time = time.time()

        # Incrementar contador de trades
        self._metrics['trade_count'] += 1

        # Calcular intervalo desde el último trade
        if self._metrics['last_trade_time'] is not None:
            interval = current_time - self._metrics['last_trade_time']
            self._metrics['total_trade_intervals'] += interval
            self._metrics['min_trade_interval'] = min(self._metrics['min_trade_interval'], interval)
            self._metrics['max_trade_interval'] = max(self._metrics['max_trade_interval'], interval)

        # Actualizar tiempo del último trade
        self._metrics['last_trade_time'] = current_time

    # ============================================================================
    # MÉTODOS GENÉRICOS DE PETICIÓN
    # ============================================================================

    async def websocket_request(
        self,
        method: str,
        data: Optional[Dict[str, Any]] = None,
        callback: Optional[Callable[[Any], Any]] = None,
        **kwargs: Any
    ) -> None:
        """
        Ejecuta petición WebSocket
        
        Args:
            method: Método WebSocket a ejecutar
            data: Datos a enviar
            callback: Función callback para procesar mensajes
            **kwargs: Argumentos adicionales
        """
        if not self._is_running or not self._websocket:
            raise WebSocketConnectionError("WebSocket no habilitado")

        # Preparar mensaje
        message = {
            'method': method,
            **(data or {}),
            **kwargs
        }

        # Registrar callback si se proporciona
        if callback:
            self._websocket_callbacks[method] = callback

        try:
            await self._websocket.send(json.dumps(message))
            # Mensaje WebSocket enviado: {method}

        except Exception as e:
            self._metrics['error_count'] += 1
            self._logger.error(f"Error enviando mensaje WebSocket: {e}")
            # Intentar reconectar
            await self._reconnect_websocket()
            raise WebSocketConnectionError(f"Error enviando mensaje: {e}")

    async def _websocket_listener(self):
        """
        Listener optimizado para mensajes WebSocket
        Escucha continuamente sin interrupciones, incluso durante períodos sin trades
        Usa dos tareas concurrentes: una para escuchar y otra para ping
        """
        # Crear tarea de ping en background
        ping_task = asyncio.create_task(self._ping_keepalive())

        was_cancelled = False
        try:
            while self._is_running:
                try:
                    if not self._websocket:
                        self._logger.warning("No se encontró el WebSocket")
                        break

                    # Escuchar mensaje SIN timeout para no perder trades
                    try:
                        async with asyncio.timeout(self._websocket_timeout):
                            message = await self._websocket.recv()
                    except asyncio.TimeoutError:
                        continue

                    self._metrics['message_count'] += 1
                    self._metrics['last_message_time'] = time.time()

                    # Procesar mensaje en background para no bloquear la escucha
                    task = asyncio.create_task(self._process_websocket_message(message if isinstance(message, str) else message.decode('utf-8')))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                except websockets.ConnectionClosed as e:
                    self._logger.warning(f"WebSocket desconectado: {e}")
                    break
                except asyncio.CancelledError:
                    was_cancelled = True
                    # Tarea de listener cancelada
                    break
                except Exception as e:
                    self._logger.error(f"Error en listener WebSocket: {e}")
                    break

        finally:
            # Cancelar tarea de ping al salir
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass

            # Reconectar si es necesario y no fue un cancel explícito ni hay reconexión en curso
            if self._is_running and not was_cancelled and not self._is_reconnecting:
                await self._reconnect_websocket(reason="listener_error_or_close")

    async def _ping_keepalive(self):
        """
        Tarea independiente para mantener la conexión WebSocket viva
        Se ejecuta en paralelo al listener principal
        Si el ping falla, intenta reconectar el websocket
        """
        ping_interval = 30  # Ping cada 30 segundos
        consecutive_ping_failures = 0
        max_consecutive_failures = 3  # Máximo 3 fallos consecutivos antes de reconectar

        while self._is_running:
            try:
                await asyncio.sleep(ping_interval)

                if self._websocket and self._is_running:
                    self._metrics['ping_count'] += 1
                    # Enviar ping y esperar pong
                    try:
                        async with asyncio.timeout(self._websocket_timeout):
                            pong_waiter = await self._websocket.ping()
                            latency = await pong_waiter
                            self._logger.debug(f"Keepalive ping enviado, latency: {latency:.9f} segundos")
                            # Resetear contador de fallos en ping exitoso
                            consecutive_ping_failures = 0

                    except asyncio.TimeoutError:
                        consecutive_ping_failures += 1
                        self._metrics['ping_failures'] += 1
                        self._logger.warning(f"Keepalive ping timeout - posible problema de conectividad (fallo {consecutive_ping_failures}/{max_consecutive_failures})")

                        if consecutive_ping_failures >= max_consecutive_failures:
                            self._logger.warning(f"Demasiados fallos de ping consecutivos ({consecutive_ping_failures}), iniciando reconexión...")
                            if not self._is_reconnecting:
                                self._metrics['ping_reconnects'] += 1
                                await self._reconnect_websocket(reason="ping_timeouts")
                            consecutive_ping_failures = 0  # Resetear después de reconectar

                    except websockets.ConnectionClosed as e:
                        self._logger.warning(f"WebSocket cerrado durante ping, iniciando reconexión...: {e}")
                        if not self._is_reconnecting:
                            self._metrics['ping_reconnects'] += 1
                            await self._reconnect_websocket(reason="ping_connection_closed")
                        consecutive_ping_failures = 0

                    except Exception as e:
                        consecutive_ping_failures += 1
                        self._metrics['ping_failures'] += 1
                        self._logger.warning(f"Error en keepalive ping: {e} (fallo {consecutive_ping_failures}/{max_consecutive_failures})")

                        if consecutive_ping_failures >= max_consecutive_failures:
                            self._logger.warning(f"Demasiados fallos de ping consecutivos ({consecutive_ping_failures}), iniciando reconexión...")
                            if not self._is_reconnecting:
                                self._metrics['ping_reconnects'] += 1
                                await self._reconnect_websocket(reason="ping_generic_errors")
                            consecutive_ping_failures = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error en keepalive ping: {e}")
                # Continuar intentando, el listener principal manejará la reconexión si es necesario
                await asyncio.sleep(5)  # Esperar antes de reintentar

    async def _inactivity_watchdog(self):
        """Reconecta solo si no hubo trades durante el período mínimo configurado"""
        while self._is_running:
            try:
                # Espera basada en configuración mínima (por ejemplo, 1 hora)
                wait_seconds = self._inactivity_watch_seconds
                self._logger.debug(f"Watchdog esperando {wait_seconds:.1f}s (basado en inactividad de trades)")
                await asyncio.sleep(wait_seconds)

                # Evaluar inactividad basada en trades
                last_time = self._metrics['last_trade_time'] or 0
                now = time.time()
                self._metrics['inactivity_last_check'] = now

                # Si nunca hubo trades y ya pasó el período, también actúa
                if last_time == 0:
                    last_time = self._metrics['first_connection_time'] or now

                gap = now - last_time
                if gap >= wait_seconds:
                    # Reconectar indefinidamente por inactividad
                    self._metrics['inactivity_reconnects'] += 1
                    self._metrics['inactivity_triggered'] = True
                    self._logger.info(
                        f"Inactividad detectada ({int(gap)}s sin trades, umbral: {wait_seconds:.1f}s). Reconectando WebSocket... (reconexión #{self._metrics['inactivity_reconnects']})"
                    )
                    await self._reconnect_websocket(reason="inactivity_no_trades")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error en watchdog de inactividad: {e}")
                # En caso de error, usar el tiempo mínimo configurado
                await asyncio.sleep(self._inactivity_watch_seconds)

    def _is_async_callback(self, callback: Callable[[Any], Any]) -> bool:
        """
        Determina si un callback es asíncrono
        
        Args:
            callback: Función o callable a verificar
            
        Returns:
            True si es async, False si es sync
        """
        if asyncio.iscoroutinefunction(callback):
            return True
        elif hasattr(callback, '__call__') and asyncio.iscoroutinefunction(callback.__call__):
            return True
        return False

    async def _execute_callback(self, callback: Callable[[Any], Any], data: Dict[str, Any], callback_type: str = "callback"):
        """
        Ejecuta un callback de forma segura, manejando tanto sync como async
        
        Args:
            callback: Función callback a ejecutar
            data: Datos a pasar al callback
            callback_type: Tipo de callback para logging
        """
        try:
            if self._is_async_callback(callback):
                # Ejecutar callback asíncrono en background para no bloquear
                asyncio.create_task(callback(data))
            elif callable(callback):
                # Ejecutar callback síncrono directamente
                callback(data)
            else:
                self._logger.warning(f"{callback_type} no es callable: {type(callback)}")
        except Exception as e:
            self._logger.error(f"Error en {callback_type}: {e}")

    async def _process_websocket_message(self, message: str):
        """
        Procesa mensajes recibidos del WebSocket de forma optimizada
        Maneja callbacks síncronos y asíncronos eficientemente
        Añade logs detallados para facilitar el diagnóstico.
        """
        self._logger.debug(f"[WS] Recibido mensaje crudo: {message}")
        try:
            data = json.loads(message)
            self._logger.debug(f"[WS] Mensaje decodificado correctamente (claves: {list(data.keys())})")

            # Si el mensaje es de confirmación, solo lo mostramos y salimos
            if 'message' in data:
                self._logger.info(f"[WS] Mensaje del servidor: {data['message']}")
                return

            # Determinar tipo de evento
            if 'txType' in data:
                event_type = data['txType']
                self._logger.debug(f"[WS] 'txType' detectado: {event_type}")
            elif 'errors' in data:
                event_type = 'error'
                self._logger.debug(f"[WS] 'errors' detectado en el mensaje: {data['errors']}")
            else:
                self._logger.error(f"[WS] Mensaje no válido o inesperado: {data}")
                return

            callback = None

            # Determinar callback según el tipo de evento y loggear detalles
            if event_type == 'create':
                callback = self._websocket_callbacks.get('subscribeNewToken')
                self._logger.debug(f"[WS] Callback asociado para 'create': {'encontrado' if callback else 'no encontrado'}")
            elif event_type in ['buy', 'sell']:
                callback = self._websocket_callbacks.get('subscribeTokenTrade') or self._websocket_callbacks.get('subscribeAccountTrade')
                self._logger.debug(f"[WS] Callback asociado para '{event_type}': {'encontrado' if callback else 'no encontrado'}")
                self._update_trade_metrics()
                self._logger.debug(f"[WS] Métricas de trade actualizadas (event_type: {event_type})")
            elif event_type == 'migrate':
                callback = self._websocket_callbacks.get('subscribeMigration')
                self._logger.debug(f"[WS] Callback asociado para 'migrate': {'encontrado' if callback else 'no encontrado'}")
            elif event_type == 'error':
                callback = self._websocket_callbacks.get('on_error')
                if callback:
                    self._logger.debug(f"[WS] Ejecutando callback de error para: {data}")
                else:
                    self._logger.error(f"[WS] No se encontró callback para errores. Data: {data}")

            # Ejecutar callback principal
            if callback:
                self._logger.info(f"[WS] Ejecutando callback principal para event_type='{event_type}'. Data resumida: {str(data)[:250]}")
                await self._execute_callback(callback, data, f"callback principal para {event_type}")
            else:
                # Usar callback por defecto si existe uno para eventos no manejados
                default_cb = self._websocket_callbacks.get('default')
                if default_cb:
                    self._logger.info(f"[WS] Ejecutando callback por defecto para evento no manejado: '{event_type}'.")
                    await self._execute_callback(default_cb, data, "callback por defecto")
                else:
                    if event_type != 'error':  # Ya logueamos los errores arriba
                        self._logger.warning(f"[WS] Evento no manejado o sin callback para txType '{event_type}'. Data: {str(data)[:250]}")

            # Callback genérico para todos los mensajes (si existe)
            on_message_cb = self._websocket_callbacks.get('on_message')
            if on_message_cb:
                self._logger.debug(f"[WS] Ejecutando callback genérico para mensaje recibido.")
                await self._execute_callback(on_message_cb, data, "callback genérico")
            else:
                self._logger.debug(f"[WS] No hay callback genérico configurado ('on_message').")

        except json.JSONDecodeError:
            self._logger.error(f"[WS] Error decodificando JSON del mensaje: {message[:200]}...")
        except Exception as e:
            self._logger.error(f"[WS] Error procesando mensaje WebSocket: {type(e).__name__}: {e} | Mensaje: {message[:200]}...")

    async def _unsubscribe_all_events(self):
        """
        Desuscribe de todos los eventos activos antes de desconectar
        """
        if not self._websocket or not self._websocket_subscriptions:
            return

        try:
            for subscription_data in self._websocket_subscriptions:
                subscription_json: Dict[str, Any] = json.loads(subscription_data)
                method: str = subscription_json.get('method', '')
                try:
                    if method.startswith('subscribe'):
                        # Crear mensaje de desuscripción
                        unsubscribe_method = method.replace('subscribe', 'unsubscribe')
                        unsubscribe_data: Dict[str, Any] = {
                            'method': unsubscribe_method,
                            'keys': subscription_json.get('keys', [])
                        }

                        await self._websocket.send(json.dumps(unsubscribe_data))
                        self._logger.debug(f"Desuscripción enviada para {method}")

                except websockets.ConnectionClosed as e:
                    self._logger.debug(f"WebSocket cerrado durante desuscripción de {method}: {e}")
                    break  # Salir del bucle si la conexión se cerró
                except Exception as e:
                    self._logger.warning(f"Error desuscribiendo {method}: {e}")

            # Limpiar suscripciones
            if not self._is_reconnecting:
                self._websocket_subscriptions.clear()
            self._logger.debug("Proceso de desuscripción completado")

        except Exception as e:
            self._logger.warning(f"Error en desuscripción masiva: {e}")

    async def _reconnect_websocket(self, reason: str = "unknown"):
        """
        Reconecta WebSocket automáticamente usando sistema de reconexión exponencial
        """
        if not self._is_running:
            return

        self._logger.debug(f"Reconectando WebSocket automáticamente... (motivo: {reason})")
        self._metrics['reconnect_count'] += 1
        self._metrics['last_reconnect_reason'] = reason
        self._metrics['last_reconnect_time'] = time.time()

        reconnect_start = time.time()
        try:
            self._is_reconnecting = True

            # Fase 1: Desconectar
            disconnect_start = time.time()
            await self.disconnect()
            disconnect_time = time.time() - disconnect_start
            self._logger.debug(f"Desconexión completada en {disconnect_time:.6f}s")

            await asyncio.sleep(1)

            # Fase 2: Reconectar usando sistema exponencial
            connect_start = time.time()
            await self.connect()  # Ya incluye el sistema de reconexión exponencial
            connect_time = time.time() - connect_start
            self._logger.debug(f"Conexión establecida en {connect_time:.6f}s")

            # Fase 3: Reestablecer suscripciones
            subscriptions_start = time.time()
            if self._websocket_subscriptions:
                self._logger.info(f"Reestableciendo {len(self._websocket_subscriptions)} suscripciones...")
                for i, subscription in enumerate(self._websocket_subscriptions):
                    if self._websocket:
                        try:
                            await self._websocket.send(subscription)
                            self._logger.debug(f"Suscripción {i+1}/{len(self._websocket_subscriptions)} reestablecida")
                        except Exception as e:
                            self._logger.error(f"Error reestableciendo suscripción {i+1}: {e}")
                self._logger.info("Suscripciones reestablecidas")
            else:
                self._logger.debug("No hay suscripciones que reestablecer")
            subscriptions_time = time.time() - subscriptions_start

            # Tiempo total de reconexión
            total_reconnect_time = time.time() - reconnect_start

            self._logger.info(f"Reconexión completada en {total_reconnect_time:.6f}s (desconectar: {disconnect_time:.6f}s, conectar: {connect_time:.6f}s, suscripciones: {subscriptions_time:.6f}s) - motivo: {reason}")

        except Exception as e:
            total_reconnect_time = time.time() - reconnect_start
            self._logger.error(f"Error reconectando WebSocket después de {total_reconnect_time:.6f}s: {e}")
        finally:
            self._logger.info("WebSocket reconectado exitosamente")
            self._is_reconnecting = False

    # ============================================================================
    # MÉTODOS DE CONVENIENCIA
    # ============================================================================

    async def subscribe(self, method: WebSocketMethod, keys: Optional[List[str]] = None, callback: Optional[Callable[[Any], Any]] = None):
        """
        Suscribe a eventos WebSocket
        
        Args:
            method: Método de suscripción
            keys: Lista de claves (tokens/cuentas)
            callback: Función callback para procesar mensajes
            use_api_key: Si True, usa conexión con API key para PumpSwap data
        """
        subscription_data: Dict[str, Any] = {'method': method.value}
        if keys:
            subscription_data['keys'] = keys

        # Guardar suscripción para reconexiones
        subscription_json = json.dumps(subscription_data)
        self._websocket_subscriptions.add(subscription_json)
        self._metrics['subscription_count'] += 1

        self._logger.info(f"Suscribiendo a {method.value} con {len(keys) if keys else 0} claves")

        # Registrar callback si se proporciona
        if callback:
            self._websocket_callbacks[method.value] = callback
            self._metrics['callback_count'] += 1

        await self.websocket_request(method=method.value, data=subscription_data, callback=callback)

    async def unsubscribe(self, method: WebSocketMethod, keys: Optional[List[str]] = None):
        """
        Desuscribe de eventos WebSocket
        
        Args:
            method: Método de suscripción a desuscribir
            keys: Lista de claves (tokens/cuentas) a desuscribir
        """
        unsubscribe_method = method.value.replace('subscribe', 'unsubscribe')
        unsubscribe_data: Dict[str, Any] = {'method': unsubscribe_method}
        if keys:
            unsubscribe_data['keys'] = keys

        # Remover de suscripciones
        subscription_json = json.dumps({'method': method.value, 'keys': keys})
        self._websocket_subscriptions.discard(subscription_json)

        # Enviar mensaje de desuscripción
        await self.websocket_request(method=unsubscribe_method, data=unsubscribe_data)

        self._logger.debug(f"Desuscrito de: {method}")
        if keys:
            self._logger.debug(f"Claves: {keys}")

    def set_global_callback(self, callback: Callable[[Any], Any]):
        """Establece callback global para todos los mensajes WebSocket"""
        self._websocket_callbacks['on_message'] = callback

    def set_method_callback(self, method: str, callback: Callable[[Any], Any]):
        """Establece callback específico para un método WebSocket"""
        self._websocket_callbacks[method] = callback

    def set_error_callback(self, callback: Callable[[Any], Any]):
        """
        Establece callback específico para mensajes de error del WebSocket.
        
        Este callback se ejecutará cuando se reciba un mensaje con el campo 'errors',
        por ejemplo: {'errors': 'Minimum balance not met for PumpSwap websocket data.'}
        
        Args:
            callback: Función callback que recibe el mensaje de error como dict.
                    Puede ser síncrona o asíncrona.
        
        Ejemplo:
            async def on_error(error_data: dict):
                if 'Minimum balance' in str(error_data.get('errors', '')):
                    await handle_minimum_balance_error(error_data)
            
            ws_client.set_error_callback(on_error)
        """
        self._websocket_callbacks['on_error'] = callback
        self._logger.info("Callback de errores registrado")

    async def unsubscribe_all(self):
        """
        Desuscribe manualmente de todos los eventos activos
        Útil para limpiar suscripciones antes de cambiar de estrategia
        """
        if not self._is_running:
            self._logger.warning("WebSocket no conectado, no hay suscripciones activas")
            return

        await self._unsubscribe_all_events()

    # ============================================================================
    # MÉTODOS DE ESTADO Y MÉTRICAS
    # ============================================================================

    def get_status(self) -> Dict[str, Any]:
        """Obtiene estado actual del cliente WebSocket"""

        # Calcular métricas derivadas
        message_count = self._metrics['message_count'] or 0
        error_count = self._metrics['error_count'] or 0
        connection_attempts = self._metrics['connection_attempts'] or 0

        # Calcular uptime
        uptime_seconds = 0
        if self._metrics['first_connection_time'] is not None:
            uptime_seconds = time.time() - self._metrics['first_connection_time']

        # Calcular mensajes por segundo
        messages_per_second = 0
        if uptime_seconds > 0:
            messages_per_second = message_count / uptime_seconds

        # Calcular métricas de trades
        trade_count = self._metrics['trade_count'] or 0
        avg_trade_interval = 0.0
        if trade_count > 1 and self._metrics['total_trade_intervals'] > 0:
            avg_trade_interval = self._metrics['total_trade_intervals'] / (trade_count - 1)

        min_trade_interval = self._metrics['min_trade_interval'] if self._metrics['min_trade_interval'] != float('inf') else 0
        max_trade_interval = self._metrics['max_trade_interval'] or 0

        return {
            'websocket_connected': self._is_running and self._websocket is not None,
            'is_running': self._is_running,
            'api_key_configured': bool(self._api_key),
            'connection_attempts': connection_attempts,
            'error_count': error_count,
            'message_count': message_count,
            'subscription_count': self._metrics['subscription_count'] or 0,
            'callback_count': self._metrics['callback_count'] or 0,
            'reconnect_count': self._metrics['reconnect_count'] or 0,
            'reconnect_attempts': self._reconnect_attempts,
            'exponential_reconnect_count': self._metrics['exponential_reconnect_count'] or 0,
            'ping_count': self._metrics['ping_count'] or 0,
            'ping_failures': self._metrics['ping_failures'] or 0,
            'ping_reconnects': self._metrics['ping_reconnects'] or 0,
            'inactivity_reconnects': self._metrics['inactivity_reconnects'] or 0,
            'inactivity_last_check': self._metrics['inactivity_last_check'],
            'inactivity_triggered': self._metrics['inactivity_triggered'],
            'last_reconnect_reason': self._metrics['last_reconnect_reason'],
            'last_reconnect_time': self._metrics['last_reconnect_time'],
            'active_subscriptions': len(self._websocket_subscriptions),
            'registered_callbacks': len(self._websocket_callbacks),
            'messages_per_second': round(messages_per_second, 2),
            'uptime_seconds': round(uptime_seconds, 2),
            'first_connection_time': self._metrics['first_connection_time'],
            'last_message_time': self._metrics['last_message_time'],
            'websocket_url': self._websocket_base_url,
            # Configuración de reconexión exponencial
            'max_reconnect_attempts': self._max_reconnect_attempts,
            'base_reconnect_delay': self._base_reconnect_delay,
            'max_reconnect_delay': self._max_reconnect_delay,
            'reconnect_jitter_enabled': self._reconnect_jitter,
            # Métricas de trades
            'trade_count': trade_count,
            'last_trade_time': self._metrics['last_trade_time'],
            'avg_trade_interval_seconds': round(avg_trade_interval, 2),
            'min_trade_interval_seconds': round(min_trade_interval, 2),
            'max_trade_interval_seconds': round(max_trade_interval, 2)
        }

    def reset_metrics(self):
        """Resetea métricas del cliente WebSocket"""
        self._metrics['connection_attempts'] = 0
        self._metrics['error_count'] = 0
        self._metrics['message_count'] = 0
        self._metrics['subscription_count'] = 0
        self._metrics['callback_count'] = 0
        self._metrics['total_response_time_ms'] = 0.0
        self._metrics['first_connection_time'] = None
        self._metrics['last_message_time'] = None
        self._metrics['reconnect_count'] = 0
        self._metrics['reconnect_attempts'] = 0
        self._metrics['exponential_reconnect_count'] = 0
        self._metrics['ping_count'] = 0
        self._metrics['ping_failures'] = 0
        self._metrics['ping_reconnects'] = 0
        self._metrics['inactivity_reconnects'] = 0
        self._metrics['inactivity_last_check'] = None
        self._metrics['inactivity_triggered'] = False
        self._metrics['last_reconnect_reason'] = None
        self._metrics['last_reconnect_time'] = None
        # Resetear métricas de trades
        self._metrics['trade_count'] = 0
        self._metrics['last_trade_time'] = None
        self._metrics['total_trade_intervals'] = 0.0
        self._metrics['min_trade_interval'] = float('inf')
        self._metrics['max_trade_interval'] = 0.0

        # Resetear contador de intentos de reconexión
        self._reconnect_attempts = 0

        self._logger.info("Métricas del cliente WebSocket reseteadas")
