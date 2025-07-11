# -*- coding: utf-8 -*-
"""
PumpFun API Client - Cliente centralizado para todas las llamadas a APIs
Implementa patrón Singleton con soporte async/await, WebSocket y HTTP
"""
from typing import Dict, Any, Optional, Union, Callable, List, TYPE_CHECKING
from websockets.exceptions import ConnectionClosed
from enum import Enum
import asyncio
import json
import threading
import aiohttp
import websockets

if TYPE_CHECKING:
    from solders.transaction import VersionedTransaction
    from solders.commitment_config import CommitmentLevel
    from solders.rpc.requests import SendVersionedTransaction
    from solders.rpc.config import RpcSendTransactionConfig


class ApiType(Enum):
    """Tipos de API disponibles"""
    HTTP = "http"
    WEBSOCKET = "websocket"


class RequestMethod(Enum):
    """Métodos HTTP disponibles"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class ApiClientException(Exception):
    """Excepción base para el cliente API"""
    pass


class WebSocketConnectionError(ApiClientException):
    """Error de conexión WebSocket"""
    pass


class HttpRequestError(ApiClientException):
    """Error de petición HTTP"""
    pass


class SingletonMeta(type):
    """Metaclass para implementar patrón Singleton thread-safe"""
    _instances = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    instance = super().__call__(*args, **kwargs)
                    cls._instances[cls] = instance
        return cls._instances[cls]


class PumpFunApiClient(metaclass=SingletonMeta):
    """
    Cliente centralizado para todas las APIs de PumpFun
    Implementa patrón Singleton con soporte async/await
    """

    def __init__(self, 
                    websocket_url: str = "wss://pumpportal.fun/api/data",
                    http_base_url: str = "https://pumpportal.fun/api",
                    api_key: str = None,
                    enable_websocket: bool = True,
                    enable_http: bool = True,
                    max_connections: int = 10,
                    websocket_timeout: int = 60,
                    http_timeout: int = 30,
                    max_retries: int = 3,
                    retry_delay: float = 1.0):
        """
        Inicializa el cliente API
        
        Args:
            websocket_url: URL del WebSocket
            http_base_url: URL base para peticiones HTTP
            api_key: API key para autenticación
            enable_websocket: Habilitar conexiones WebSocket
            enable_http: Habilitar peticiones HTTP
            max_connections: Máximo número de conexiones HTTP
            websocket_timeout: Timeout para WebSocket (segundos)
            http_timeout: Timeout para HTTP (segundos)
            max_retries: Máximo número de reintentos
            retry_delay: Delay base entre reintentos
        """
        # Evitar reinicialización en singleton
        if hasattr(self, '_initialized'):
            return

        self.websocket_url = websocket_url
        self.http_base_url = http_base_url
        self.api_key = api_key
        self.enable_websocket = enable_websocket
        self.enable_http = enable_http
        self.max_connections = max_connections
        self.websocket_timeout = websocket_timeout
        self.http_timeout = http_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Estado interno
        self._websocket = None
        self._http_session = None
        self._websocket_lock = asyncio.Lock()
        self._http_lock = asyncio.Lock()
        self._is_websocket_connected = False
        self._websocket_callbacks = {}
        self._websocket_subscriptions = set()
        self._listener_task = None

        # Métricas y logging
        self._request_count = 0
        self._error_count = 0
        self._connection_attempts = 0
        self._websocket_message_count = 0

        self._initialized = True
        print(f"🌐 PumpFun API Client inicializado")
        print(f"   WebSocket: {'✅' if enable_websocket else '❌'} {websocket_url}")
        print(f"   HTTP: {'✅' if enable_http else '❌'} {http_base_url}")
        if api_key:
            print(f"   API Key: ✅ {api_key[:8]}...")
        else:
            print(f"   API Key: ❌ No proporcionada")

    async def __aenter__(self):
        """Context manager entry"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.disconnect()

    # ============================================================================
    # MÉTODOS DE CONEXIÓN
    # ============================================================================

    async def connect(self):
        """Conecta a las APIs habilitadas"""
        tasks = []

        if self.enable_websocket:
            tasks.append(self._connect_websocket())

        if self.enable_http:
            tasks.append(self._connect_http())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def disconnect(self):
        """Desconecta de todas las APIs"""
        tasks = []

        if self._websocket:
            # Desuscribir eventos antes de desconectar
            await self._unsubscribe_all_events()
            tasks.append(self._disconnect_websocket())

        if self._http_session:
            tasks.append(self._disconnect_http())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _connect_websocket(self, use_api_key: bool = False):
        """
        Conecta al WebSocket
        
        Args:
            use_api_key: Si True, incluye API key en la URL para PumpSwap data
        """
        if not self.enable_websocket:
            return

        async with self._websocket_lock:
            if self._is_websocket_connected:
                return

            try:
                self._connection_attempts += 1

                # Construir URL con o sin API key
                ws_url = self.websocket_url
                if use_api_key and self.api_key:
                    ws_url = f"{self.websocket_url}?api-key={self.api_key}"

                print(f"🔗 Conectando WebSocket... (intento {self._connection_attempts})")
                if use_api_key:
                    print(f"   🔑 Usando API key para PumpSwap data")

                self._websocket = await asyncio.wait_for(
                    websockets.connect(
                        ws_url,
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=10
                    ),
                    timeout=self.websocket_timeout
                )

                self._is_websocket_connected = True

                # Iniciar listener en background
                self._listener_task = asyncio.create_task(self._websocket_listener())

                print("✅ WebSocket conectado exitosamente")

            except Exception as e:
                print(f"❌ Error conectando WebSocket: {e}")
                raise WebSocketConnectionError(f"Error conectando WebSocket: {e}")

    async def _connect_http(self):
        """Conecta sesión HTTP"""
        if not self.enable_http:
            return

        async with self._http_lock:
            if self._http_session and not self._http_session.closed:
                return

            try:
                connector = aiohttp.TCPConnector(
                    limit=self.max_connections,
                    limit_per_host=self.max_connections,
                    ttl_dns_cache=300,
                    use_dns_cache=True
                )

                timeout = aiohttp.ClientTimeout(total=self.http_timeout)

                self._http_session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                    headers={
                        'User-Agent': 'PumpFun-API-Client/1.0',
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    }
                )

                print("✅ Sesión HTTP inicializada")

            except Exception as e:
                print(f"❌ Error inicializando HTTP: {e}")
                raise HttpRequestError(f"Error inicializando HTTP: {e}")

    async def _disconnect_websocket(self):
        """Desconecta WebSocket"""
        async with self._websocket_lock:
            try:
                self._is_websocket_connected = False

                if self._listener_task:
                    self._listener_task.cancel()
                    try:
                        await self._listener_task
                    except asyncio.CancelledError:
                        pass

                if self._websocket:
                    await self._websocket.close()
                    self._websocket = None

                print("🔌 WebSocket desconectado")

            except Exception as e:
                print(f"⚠️ Error desconectando WebSocket: {e}")

    async def _disconnect_http(self):
        """Desconecta sesión HTTP"""
        async with self._http_lock:
            try:
                if self._http_session and not self._http_session.closed:
                    await self._http_session.close()
                    self._http_session = None

                print("🔌 Sesión HTTP cerrada")

            except Exception as e:
                print(f"⚠️ Error cerrando HTTP: {e}")

    # ============================================================================
    # MÉTODOS GENÉRICOS DE PETICIÓN
    # ============================================================================

    async def request(self, 
                        api_type: ApiType,
                        method: Union[RequestMethod, str] = RequestMethod.POST,
                        endpoint: str = "",
                        data: Optional[Dict[str, Any]] = None,
                        params: Optional[Dict[str, Any]] = None,
                        headers: Optional[Dict[str, str]] = None,
                        callback: Optional[Callable] = None,
                        use_api_key: bool = False,
                        return_json: bool = True,
                        files: Optional[Dict] = None,
                        **kwargs) -> Optional[Any]:
        """
        Método genérico para enviar peticiones a cualquier API
        
        Args:
            api_type: Tipo de API (HTTP, WEBSOCKET)
            method: Método HTTP o acción WebSocket
            endpoint: Endpoint o comando
            data: Datos a enviar
            params: Parámetros de query (solo HTTP)
            headers: Headers adicionales (solo HTTP)
            callback: Callback para respuestas WebSocket
            use_api_key: Si True, incluye API key en la petición
            return_json: Si True, la respuesta HTTP será parseada como JSON
            **kwargs: Argumentos adicionales
            
        Returns:
            Respuesta de la API o None para WebSocket
        """
        self._request_count += 1

        try:
            if api_type == ApiType.HTTP:
                return await self._http_request(method, endpoint, data, params, headers, use_api_key, return_json, files, **kwargs)

            elif api_type == ApiType.WEBSOCKET:
                return await self._websocket_request(method, data, callback, use_api_key, **kwargs)

            else:
                raise ApiClientException(f"Tipo de API no soportado: {api_type}")

        except Exception as e:
            self._error_count += 1
            print(f"❌ Error en petición {api_type.value}: {e}")
            raise

    async def _http_request_files(self,
                                method: Union[RequestMethod, str],
                                endpoint: str,
                                data: Optional[Dict[str, Any]] = None,
                                files: Optional[Dict] = None,
                                params: Optional[Dict[str, Any]] = None,
                                headers: Optional[Dict[str, str]] = None,
                                use_api_key: bool = False,
                                url: Optional[str] = None,
                                **kwargs) -> Optional[Dict[str, Any]]:
        """
        Petición HTTP con archivos usando aiohttp.FormData
        """
        if not self._http_session or self._http_session.closed:
            raise HttpRequestError("Sesión HTTP no disponible")

        # Construir URL
        if url:
            request_url = url
        else:
            request_url = f"{self.http_base_url}/{endpoint.lstrip('/')}" if endpoint else self.http_base_url

        # Preparar headers
        request_headers = headers or {}
        if use_api_key and self.api_key:
            request_headers['Authorization'] = f'Bearer {self.api_key}'

        # Crear FormData
        form_data = aiohttp.FormData()
        
        # Añadir datos de formulario
        if data:
            for key, value in data.items():
                form_data.add_field(key, str(value))
        
        # Añadir archivos
        if files:
            for field_name, file_data in files.items():
                if isinstance(file_data, tuple) and len(file_data) >= 2:
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
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._http_session.post(
                    request_url,
                    data=form_data,
                    params=params,
                    headers=request_headers,
                    **kwargs
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        raise HttpRequestError(f"HTTP {response.status}: {error_text}")

            except Exception as e:
                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** (attempt - 1))
                    print(f"⚠️ Reintentando HTTP en {delay}s... (intento {attempt}/{self.max_retries})")
                    await asyncio.sleep(delay)
                else:
                    raise HttpRequestError(f"Error HTTP después de {self.max_retries} intentos: {e}")

    async def _http_request(self,
                            method: Union[RequestMethod, str],
                            endpoint: str,
                            data: Optional[Dict[str, Any]] = None,
                            params: Optional[Dict[str, Any]] = None,
                            headers: Optional[Dict[str, str]] = None,
                            use_api_key: bool = False,
                            return_json: bool = True,
                            files: Optional[Dict] = None,
                            url: Optional[str] = None,
                            **kwargs) -> Optional[Union[Dict[str, Any], bytes]]:
        """
        Petición HTTP genérica (GET, POST, etc.)
        """
        if not self._http_session or self._http_session.closed:
            raise HttpRequestError("Sesión HTTP no disponible")

        # Construir URL
        if url:
            request_url = url
        else:
            request_url = f"{self.http_base_url}/{endpoint.lstrip('/')}" if endpoint else self.http_base_url

        # Preparar parámetros, incluyendo la API key si es necesario
        request_params = params.copy() if params else {}
        if use_api_key and self.api_key:
            request_params['api-key'] = self.api_key

        # Preparar argumentos
        request_kwargs = {
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
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._http_session.request(method.value if isinstance(method, RequestMethod) else method,
                                                     **request_kwargs) as response:
                    if response.status == 200:
                        if return_json:
                            return await response.json()
                        else:
                            return await response.read()
                    else:
                        error_text = await response.text()
                        raise HttpRequestError(f"HTTP {response.status}: {error_text}")
            except Exception as e:
                if attempt < self.max_retries:
                    delay = self.retry_delay * (2 ** (attempt - 1))
                    print(f"⚠️ Reintentando HTTP en {delay}s... (intento {attempt}/{self.max_retries})")
                    await asyncio.sleep(delay)
                else:
                    raise HttpRequestError(f"Error HTTP después de {self.max_retries} intentos: {e}")

    async def _websocket_request(self,
                                command: str,
                                data: Optional[Dict[str, Any]] = None,
                                callback: Optional[Callable] = None,
                                use_api_key: bool = False,
                                **kwargs) -> None:
        """
        Ejecuta petición WebSocket
        
        Args:
            use_api_key: Si True, reconecta con API key si es necesario
        """
        if not self.enable_websocket:
            raise WebSocketConnectionError("WebSocket no habilitado")

        # Si necesitamos API key y no está en la URL actual, reconectar
        if use_api_key and self.api_key and self._websocket:
            current_url = str(self._websocket.remote_address)
            if 'api-key=' not in current_url:
                print("🔄 Reconectando WebSocket con API key...")
                await self._disconnect_websocket()
                await self._connect_websocket(use_api_key=True)

        if not self._is_websocket_connected:
            await self._connect_websocket(use_api_key=use_api_key)

        # Preparar mensaje
        message = {
            'method': command,
            **(data or {}),
            **kwargs
        }

        # Registrar callback si se proporciona
        if callback:
            self._websocket_callbacks[command] = callback

        try:
            await self._websocket.send(json.dumps(message))
            print(f"📤 Mensaje WebSocket enviado: {command}")

        except Exception as e:
            print(f"❌ Error enviando mensaje WebSocket: {e}")
            # Intentar reconectar
            await self._reconnect_websocket(use_api_key=use_api_key)
            raise WebSocketConnectionError(f"Error enviando mensaje: {e}")

    async def _websocket_listener(self):
        """
        Listener optimizado para mensajes WebSocket
        Escucha continuamente sin interrupciones, incluso durante períodos sin trades
        Usa dos tareas concurrentes: una para escuchar y otra para ping
        """
        # Crear tarea de ping en background
        ping_task = asyncio.create_task(self._ping_keepalive())

        try:
            while self._is_websocket_connected:
                try:
                    # Escuchar mensaje SIN timeout para no perder trades
                    message = await self._websocket.recv()

                    self._websocket_message_count += 1
                    # Procesar mensaje en background para no bloquear la escucha
                    asyncio.create_task(self._process_websocket_message(message))

                except ConnectionClosed:
                    print("🔌 WebSocket desconectado")
                    break

                except Exception as e:
                    print(f"❌ Error en listener WebSocket: {e}")
                    break

        finally:
            # Cancelar tarea de ping al salir
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass

            # Reconectar si es necesario
            if self._is_websocket_connected:
                await self._reconnect_websocket()

    async def _ping_keepalive(self):
        """
        Tarea independiente para mantener la conexión WebSocket viva
        Se ejecuta en paralelo al listener principal
        """
        ping_interval = 30  # Ping cada 30 segundos

        while self._is_websocket_connected:
            try:
                await asyncio.sleep(ping_interval)

                if self._websocket and self._is_websocket_connected:
                    await self._websocket.ping()
                    print("🏓 Keepalive ping enviado")

            except asyncio.CancelledError:
                # Tarea cancelada, salir limpiamente
                break
            except Exception as e:
                print(f"⚠️ Error en keepalive ping: {e}")
                # Continuar intentando, el listener principal manejará la reconexión si es necesario
                await asyncio.sleep(5)  # Esperar antes de reintentar

    async def _background_ping(self):
        """
        Envía ping en background sin bloquear la escucha de mensajes
        (Método legacy mantenido para compatibilidad)
        """
        try:
            if self._websocket and self._is_websocket_connected:
                await self._websocket.ping()
                print("🏓 Ping enviado (background)")
        except Exception as e:
            print(f"⚠️ Error en ping background: {e}")
            # No reconectar aquí, dejar que el listener principal lo maneje

    def _is_async_callback(self, callback) -> bool:
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

    async def _execute_callback(self, callback, data: Dict[str, Any], callback_type: str = "callback"):
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
                print(f"⚠️ {callback_type} no es callable: {type(callback)}")
        except Exception as e:
            print(f"❌ Error en {callback_type}: {e}")

    async def _process_websocket_message(self, message: str):
        """
        Procesa mensajes recibidos del WebSocket de forma optimizada
        Maneja callbacks síncronos y asíncronos eficientemente
        """
        try:
            data = json.loads(message)

            # Si el mensaje es de confirmación, solo lo mostramos y salimos
            if 'message' in data:
                print(f"ℹ️ Mensaje del servidor: {data['message']}")
                return

            event_type = data.get('txType')
            callback = None

            # Determinar callback según el tipo de evento
            if event_type == 'create':
                callback = self._websocket_callbacks.get('subscribeNewToken')
            elif event_type in ['buy', 'sell']:
                # Un trade puede venir de una suscripción a token o a cuenta
                callback = self._websocket_callbacks.get('subscribeTokenTrade') or self._websocket_callbacks.get('subscribeAccountTrade')
            elif event_type == 'migrate':
                callback = self._websocket_callbacks.get('subscribeMigration')

            # Ejecutar callback principal
            if callback:
                await self._execute_callback(callback, data, f"callback principal para {event_type}")
            else:
                # Usar callback por defecto si existe uno para eventos no manejados
                default_cb = self._websocket_callbacks.get('default')
                if default_cb:
                    await self._execute_callback(default_cb, data, "callback por defecto")
                else:
                    print(f"⚠️ Evento no manejado o sin callback para txType '{event_type}'")

            # Callback genérico para todos los mensajes (si existe)
            on_message_cb = self._websocket_callbacks.get('on_message')
            if on_message_cb:
                await self._execute_callback(on_message_cb, data, "callback genérico")

        except json.JSONDecodeError:
            print(f"❌ Error decodificando JSON del mensaje: {message[:200]}...")
        except Exception as e:
            print(f"❌ Error procesando mensaje WebSocket: {e}")

    async def _unsubscribe_all_events(self):
        """
        Desuscribe de todos los eventos activos antes de desconectar
        """
        if not self._websocket_subscriptions:
            return

        print(f"🔌 Desuscribiendo de {len(self._websocket_subscriptions)} eventos...")
        
        try:
            for subscription_json in self._websocket_subscriptions.copy():
                try:
                    subscription_data: Dict[str, Any] = json.loads(subscription_json)
                    method: str = subscription_data.get('method', '')

                    if method.startswith('subscribe'):
                        # Crear mensaje de desuscripción
                        unsubscribe_method = method.replace('subscribe', 'unsubscribe')
                        unsubscribe_data = {
                            'method': unsubscribe_method,
                            'keys': subscription_data.get('keys', [])
                        }

                        await self._websocket.send(json.dumps(unsubscribe_data))
                        print(f"   ✅ Desuscrito de: {method}")

                except json.JSONDecodeError:
                    print(f"   ⚠️ Error decodificando suscripción: {subscription_json}")
                except Exception as e:
                    print(f"   ❌ Error desuscribiendo {method}: {e}")

            # Limpiar suscripciones
            self._websocket_subscriptions.clear()
            print("✅ Todas las suscripciones desuscritas")

        except Exception as e:
            print(f"❌ Error en desuscripción masiva: {e}")

    async def _reconnect_websocket(self, use_api_key: bool = False):
        """
        Reconecta WebSocket automáticamente
        
        Args:
            use_api_key: Si True, reconecta con API key
        """
        if not self.enable_websocket:
            return

        print("🔄 Reconectando WebSocket...")

        try:
            await self._disconnect_websocket()
            await asyncio.sleep(self.retry_delay)
            await self._connect_websocket(use_api_key=use_api_key)

            # Reestablecer suscripciones
            for subscription in self._websocket_subscriptions:
                await self._websocket.send(json.dumps(subscription))

        except Exception as e:
            print(f"❌ Error reconectando WebSocket: {e}")

    # ============================================================================
    # MÉTODOS DE CONVENIENCIA
    # ============================================================================

    async def http_get(self, endpoint: str, params: Optional[Dict] = None, use_api_key: bool = False, **kwargs) -> Optional[Dict]:
        """Petición HTTP GET"""
        return await self.request(ApiType.HTTP, RequestMethod.GET, endpoint, params=params, use_api_key=use_api_key, **kwargs)

    async def http_post(self, endpoint: str, data: Optional[Dict] = None, use_api_key: bool = False, url: Optional[str] = None, **kwargs) -> Optional[Dict]:
        """Petición HTTP POST"""
        return await self._http_request(RequestMethod.POST, endpoint, data=data, use_api_key=use_api_key, url=url, **kwargs)

    async def http_post_files(self, endpoint: str, data: Optional[Dict] = None, files: Optional[Dict] = None, use_api_key: bool = False, **kwargs) -> Optional[Dict]:
        """Petición HTTP POST con archivos"""
        return await self._http_request_files(RequestMethod.POST, endpoint, data=data, files=files, use_api_key=use_api_key, **kwargs)

    async def http_post_raw(self, endpoint: str, data: Optional[Dict] = None, use_api_key: bool = False, **kwargs) -> Optional[bytes]:
        """Petición HTTP POST que devuelve bytes crudos"""
        return await self.request(ApiType.HTTP, RequestMethod.POST, endpoint, data=data, use_api_key=use_api_key, return_json=False, **kwargs)

    async def subscribe(self, method: str, keys: Optional[List[str]] = None, callback: Optional[Callable] = None, use_api_key: bool = False):
        """
        Suscribe a eventos WebSocket
        
        Args:
            method: Método de suscripción
            keys: Lista de claves (tokens/cuentas)
            callback: Función callback para procesar mensajes
            use_api_key: Si True, usa conexión con API key para PumpSwap data
        """
        subscription_data = {'method': method}
        if keys:
            subscription_data['keys'] = keys

        # Guardar suscripción para reconexiones
        self._websocket_subscriptions.add(json.dumps(subscription_data))

        # Registrar callback si se proporciona
        if callback:
            self._websocket_callbacks[method] = callback

        await self.request(ApiType.WEBSOCKET, method=method, data=subscription_data, callback=callback, use_api_key=use_api_key)

    async def unsubscribe(self, method: str, keys: Optional[List[str]] = None):
        """
        Desuscribe de eventos WebSocket
        
        Args:
            method: Método de suscripción a desuscribir
            keys: Lista de claves (tokens/cuentas) a desuscribir
        """
        unsubscribe_method = method.replace('subscribe', 'unsubscribe')
        unsubscribe_data = {'method': unsubscribe_method}
        if keys:
            unsubscribe_data['keys'] = keys

        # Remover de suscripciones
        subscription_json = json.dumps({'method': method, 'keys': keys})
        self._websocket_subscriptions.discard(subscription_json)

        # Enviar mensaje de desuscripción
        await self.request(ApiType.WEBSOCKET, method=unsubscribe_method, data=unsubscribe_data)

        print(f"✅ Desuscrito de: {method}")
        if keys:
            print(f"   📍 Claves: {keys}")

    def set_global_callback(self, callback: Callable):
        """Establece callback global para todos los mensajes WebSocket"""
        self._websocket_callbacks['on_message'] = callback

    def set_method_callback(self, method: str, callback: Callable):
        """Establece callback específico para un método WebSocket"""
        self._websocket_callbacks[method] = callback

    async def unsubscribe_all(self):
        """
        Desuscribe manualmente de todos los eventos activos
        Útil para limpiar suscripciones antes de cambiar de estrategia
        """
        if not self._is_websocket_connected:
            print("⚠️ WebSocket no conectado, no hay suscripciones activas")
            return

        await self._unsubscribe_all_events()

    # ============================================================================
    # MÉTODOS DE ESTADO Y MÉTRICAS
    # ============================================================================

    def get_status(self) -> Dict[str, Any]:
        """Obtiene estado actual del cliente"""
        # Obtener detalles de suscripciones activas
        subscription_details = []
        for subscription_json in self._websocket_subscriptions:
            try:
                subscription_data = json.loads(subscription_json)
                subscription_details.append({
                    'method': subscription_data.get('method', 'unknown'),
                    'keys': subscription_data.get('keys', [])
                })
            except json.JSONDecodeError:
                subscription_details.append({'method': 'invalid_json', 'keys': []})

        # Estado de la conexión WebSocket
        websocket_health = {
            'connected': self._is_websocket_connected,
            'listener_active': self._listener_task is not None and not self._listener_task.done(),
            'websocket_object_exists': self._websocket is not None
        }

        return {
            'websocket_connected': self._is_websocket_connected,
            'websocket_health': websocket_health,
            'http_session_active': self._http_session is not None and not self._http_session.closed,
            'api_key_configured': bool(self.api_key),
            'request_count': self._request_count,
            'error_count': self._error_count,
            'connection_attempts': self._connection_attempts,
            'websocket_messages_received': self._websocket_message_count,
            'active_subscriptions': len(self._websocket_subscriptions),
            'subscription_details': subscription_details,
            'registered_callbacks': len(self._websocket_callbacks),
            'estimated_cost_sol': self._websocket_message_count * 0.01 / 10000,  # Costo estimado en SOL
            'performance': {
                'messages_per_second': self._websocket_message_count / max(1, self._connection_attempts * 60),
                'error_rate': self._error_count / max(1, self._request_count),
                'uptime_estimate': 'continuous' if self._is_websocket_connected else 'disconnected'
            }
        }

    def reset_metrics(self):
        """Resetea métricas del cliente"""
        self._request_count = 0
        self._error_count = 0
        self._connection_attempts = 0
        self._websocket_message_count = 0

    @classmethod
    def reset_singleton(cls):
        """Resetea instancia singleton (útil para testing)"""
        if cls in cls._instances:
            del cls._instances[cls]

    async def send_signed_transaction(self, signed_tx: "VersionedTransaction", rpc_endpoint: str) -> str:
        """
        Envía una transacción firmada a un endpoint RPC de Solana
        
        Args:
            signed_tx: La transacción VersionedTransaction ya firmada
            rpc_endpoint: El endpoint RPC de Solana al que se enviará la transacción
            
        Returns:
            La firma de la transacción como string
        """
        # Importar solders solo cuando se necesite
        from solders.commitment_config import CommitmentLevel
        from solders.rpc.requests import SendVersionedTransaction
        from solders.rpc.config import RpcSendTransactionConfig

        if not self._http_session:
            await self._connect_http()

        commitment = CommitmentLevel.Confirmed
        config = RpcSendTransactionConfig(preflight_commitment=commitment)
        payload = SendVersionedTransaction(signed_tx, config).to_json()

        async with self._http_session.post(rpc_endpoint, data=payload, headers={"Content-Type": "application/json"}) as response:
            if response.status == 200:
                result = await response.json()
                return result.get('result')
            else:
                error_text = await response.text()
                raise HttpRequestError(f"Error enviando transacción a {rpc_endpoint}: HTTP {response.status} - {error_text}")
