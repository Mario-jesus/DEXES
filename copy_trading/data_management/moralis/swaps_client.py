# -*- coding: utf-8 -*-
"""
Cliente Asíncrono para Moralis API - Obtención de Swaps de Wallets

Permite obtener swaps de una wallet de Solana usando la API de Moralis.
Incluye manejo de paginación y backoff para rate limiting.
Optimizado para uso en notebooks y aplicaciones asíncronas.
"""
import asyncio
import aiohttp
import aiofiles
import json
import logging
import os
import statistics
import math
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class MoralisSwapsClient:
    """Cliente HTTP asíncrono para obtener swaps de wallets desde Moralis API"""

    BASE_URL = "https://solana-gateway.moralis.io"

    def __init__(self, api_key: Optional[str] = None, network: str = "mainnet"):
        """
        Inicializa el cliente de Moralis para swaps.

        Args:
            api_key: API key de Moralis. Si no se proporciona, se obtiene de MORALIS_API_KEY env var
            network: Red de Solana (mainnet o devnet). Por defecto: mainnet
        """
        self.api_key = api_key or os.getenv("MORALIS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Se requiere una API key de Moralis. "
                "Proporciona api_key o configura la variable de entorno MORALIS_API_KEY"
            )

        self.network = network
        self.session: Optional[aiohttp.ClientSession] = None
        logger.debug(f"Cliente Moralis Swaps inicializado para red: {network}")

    async def __aenter__(self):
        """Context manager para sesión aiohttp"""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cierra la sesión aiohttp"""
        await self.stop()

    async def start(self):
        """Inicia la sesión aiohttp"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        elif self.session.closed:
            self.session = aiohttp.ClientSession()

    async def stop(self):
        """Cierra la sesión aiohttp"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    def _get_headers(self) -> Dict[str, str]:
        """Construye los headers necesarios para las peticiones"""
        if not self.api_key:
            raise ValueError("API key no configurada")
        return {
            "Accept": "application/json",
            "X-API-Key": self.api_key
        }

    def _validate_pagination_params(self, limit: int, order: str) -> int:
        """
        Valida los parámetros de paginación.

        Args:
            limit: Número máximo de resultados por página
            order: Orden de los resultados ("ASC" o "DESC")

        Returns:
            limit validado (ajustado a máximo 100)

        Raises:
            ValueError: Si los parámetros son inválidos
        """
        if limit > 100:
            limit = 100  # máximo recomendado por página
        if limit < 1:
            raise ValueError("limit debe ser mayor a 0")
        if order not in ["ASC", "DESC"]:
            raise ValueError("order debe ser 'ASC' o 'DESC'")
        return limit

    def _build_query_params(
        self,
        limit: int,
        token: Optional[str] = None,
        cursor: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        order: str = "DESC",
        transaction_types: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Construye los parámetros de query string para las peticiones.

        Args:
            limit: Número máximo de resultados por página
            token: Dirección del token para filtrar swaps (opcional)
            cursor: Cursor para paginación (opcional)
            from_date: Fecha de inicio para filtrar swaps (opcional)
            to_date: Fecha de fin para filtrar swaps (opcional)
            order: Orden de los resultados ("ASC" o "DESC")
            transaction_types: Tipos de transacción a filtrar. Valores posibles: 'buy', 'sell' o 'buy,sell' (opcional)

        Returns:
            Dict con los parámetros de query string
        """
        params: Dict[str, Any] = {"limit": limit}
        if token:
            params["tokenAddress"] = token
        if cursor:
            params["cursor"] = cursor
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        if order:
            params["order"] = order
        if transaction_types:
            params["transactionTypes"] = transaction_types
        return params

    async def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 5
    ) -> Dict[str, Any]:
        """
        Realiza una petición GET a la API de Moralis con retry y backoff exponencial.

        Args:
            endpoint: Endpoint relativo de la API
            params: Parámetros de query string (opcional)
            max_retries: Número máximo de intentos en caso de error 429 o 5xx

        Returns:
            Respuesta JSON de la API

        Raises:
            aiohttp.ClientError: Si la petición falla después de todos los intentos
        """
        url = f"{self.BASE_URL}{endpoint}"
        if params:
            url = f"{url}?{urlencode(params)}"

        headers = self._get_headers()

        # Backoff exponencial ante 429/5xx
        backoff = 1.0
        last_error: Optional[Exception] = None

        session = self.session
        use_temp_session = False

        # Si no hay sesión, crear una temporal
        if session is None or session.closed:
            session = aiohttp.ClientSession()
            use_temp_session = True

        try:
            for attempt in range(max_retries):
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        # Si es rate limit o error del servidor, hacer retry con backoff
                        if response.status == 429 or response.status >= 500:
                            wait_time = backoff
                            error_text = await response.text()
                            logger.warning(
                                f"Error {response.status} en intento {attempt + 1}/{max_retries}. "
                                f"Reintentando en {wait_time:.2f}s... Error: {error_text[:100]}"
                            )
                            await asyncio.sleep(wait_time)
                            backoff = min(backoff * 1.7, 10.0)
                            continue

                        # Para otros errores, lanzar excepción
                        if response.status >= 400:
                            error_text = await response.text()
                            logger.error(
                                f"Error HTTP {response.status} en petición a Moralis: {error_text}"
                            )
                            response.raise_for_status()

                        # Éxito
                        data = await response.json()
                        logger.debug(f"Petición exitosa a {endpoint}")
                        return data

                except asyncio.TimeoutError as e:
                    last_error = e
                    logger.warning(f"Timeout en intento {attempt + 1}/{max_retries}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 1.7, 10.0)
                        continue
                    else:
                        raise

                except aiohttp.ClientError as e:
                    last_error = e
                    logger.error(f"Error de cliente en intento {attempt + 1}/{max_retries}: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 1.7, 10.0)
                        continue
                    else:
                        raise

            # Si llegamos aquí, todos los intentos fallaron
            if last_error:
                raise last_error
            raise aiohttp.ClientError(
                f"No se pudo completar la petición a {endpoint} después de {max_retries} intentos"
            )

        finally:
            # Cerrar sesión temporal si fue creada
            if use_temp_session and not session.closed:
                await session.close()

    async def fetch_swaps_page(
        self,
        wallet: str,
        token: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        order: str = "DESC",
        transaction_types: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Obtiene una página de swaps de una wallet con parámetros opcionales.
        Devuelve el JSON de Moralis (campos 'result' y 'cursor' entre otros).

        Args:
            wallet: Dirección de la wallet de Solana
            token: Dirección del token para filtrar swaps (opcional)
            limit: Número máximo de resultados por página (máximo 100)
            cursor: Cursor para paginación (opcional)
            from_date: Fecha de inicio para filtrar swaps (opcional, formato ISO 8601)
            to_date: Fecha de fin para filtrar swaps (opcional, formato ISO 8601)
            order: Orden de los resultados ("ASC" o "DESC"). Por defecto: "DESC"
            transaction_types: Tipos de transacción a filtrar. Valores posibles: 'buy', 'sell' o 'buy,sell' (opcional)

        Returns:
            Dict con los datos de la respuesta de Moralis, incluyendo:
            - 'result': Lista de swaps
            - 'cursor': Cursor para la siguiente página (si existe)
            - Otros campos de metadatos

        Raises:
            aiohttp.ClientError: Si la petición falla
            ValueError: Si los parámetros son inválidos
        """
        limit = self._validate_pagination_params(limit, order)
        path = f"/account/{self.network}/{wallet}/swaps"
        params = self._build_query_params(limit, token, cursor, from_date, to_date, order, transaction_types)

        logger.debug(
            f"Obteniendo swaps para wallet {wallet[:8]}... "
            f"(limit={limit}, token={token[:8] + '...' if token else None}, "
            f"transaction_types={transaction_types})"
        )

        return await self._make_request(path, params)

    async def _iterate_pages(
        self,
        wallet: str,
        token: Optional[str] = None,
        limit_per_page: int = 100,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        order: str = "DESC",
        max_pages: Optional[int] = None,
        process_page: Optional[Callable[[Dict[str, Any], int], Any]] = None,
        transaction_types: Optional[str] = None
    ) -> tuple[List[Any], int]:
        """
        Itera sobre todas las páginas de swaps y procesa cada página con un callback.

        Args:
            wallet: Dirección de la wallet de Solana
            token: Dirección del token para filtrar swaps (opcional)
            limit_per_page: Número máximo de resultados por página (máximo 100)
            from_date: Fecha de inicio para filtrar swaps (opcional)
            to_date: Fecha de fin para filtrar swaps (opcional)
            order: Orden de los resultados ("ASC" o "DESC"). Por defecto: "DESC"
            max_pages: Número máximo de páginas a obtener (None para todas)
            process_page: Callback opcional que recibe (response, page_count) y retorna el dato a acumular
            transaction_types: Tipos de transacción a filtrar. Valores posibles: 'buy', 'sell' o 'buy,sell' (opcional)

        Returns:
            Tupla con (lista de datos acumulados, número de páginas procesadas)
        """
        accumulated = []
        cursor = None
        page_count = 0

        try:
            while True:
                # Verificar límite de páginas
                if max_pages is not None and page_count >= max_pages:
                    logger.info(f"Se alcanzó el límite de {max_pages} páginas")
                    break

                # Obtener página
                response = await self.fetch_swaps_page(
                    wallet=wallet,
                    token=token,
                    limit=limit_per_page,
                    cursor=cursor,
                    from_date=from_date,
                    to_date=to_date,
                    order=order,
                    transaction_types=transaction_types
                )

                # Procesar página con callback si existe, sino usar respuesta completa
                if process_page:
                    processed = process_page(response, page_count)
                    if processed is not None:
                        accumulated.append(processed)
                else:
                    accumulated.append(response)

                # Verificar si hay más páginas
                result = response.get("result", [])
                if not result:
                    logger.debug(f"Página {page_count + 1}: Sin resultados")
                    break

                cursor = response.get("cursor")
                if not cursor:
                    logger.debug("No hay más páginas disponibles")
                    break

                page_count += 1
        except Exception as e:
            logger.error(f"Error al iterar páginas: {e}")
            logger.debug(f"Ultimo cursor: {cursor!r}")
            raise

        return accumulated, page_count + 1

    async def fetch_all_swaps(
        self,
        wallet: str,
        token: Optional[str] = None,
        limit_per_page: int = 100,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        order: str = "DESC",
        max_pages: Optional[int] = None,
        transaction_types: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene todos los swaps de una wallet iterando sobre todas las páginas disponibles.

        Args:
            wallet: Dirección de la wallet de Solana
            token: Dirección del token para filtrar swaps (opcional)
            limit_per_page: Número máximo de resultados por página (máximo 100)
            from_date: Fecha de inicio para filtrar swaps (opcional)
            to_date: Fecha de fin para filtrar swaps (opcional)
            order: Orden de los resultados ("ASC" o "DESC"). Por defecto: "DESC"
            max_pages: Número máximo de páginas a obtener (None para todas)
            transaction_types: Tipos de transacción a filtrar. Valores posibles: 'buy', 'sell' o 'buy,sell' (opcional)

        Returns:
            Lista con todos los swaps encontrados
        """
        logger.info(f"Obteniendo todos los swaps para wallet {wallet[:8]}...")

        def extract_swaps(response: Dict[str, Any], page_count: int) -> List[Dict[str, Any]]:
            """Extrae los swaps de una respuesta"""
            result = response.get("result", [])
            if result:
                logger.debug(f"Página {page_count + 1}: {len(result)} swaps obtenidos")
            return result

        all_swaps_pages, num_pages = await self._iterate_pages(
            wallet=wallet,
            token=token,
            limit_per_page=limit_per_page,
            from_date=from_date,
            to_date=to_date,
            order=order,
            max_pages=max_pages,
            process_page=extract_swaps,
            transaction_types=transaction_types
        )

        # Aplanar lista de listas de swaps
        all_swaps = []
        for swaps in all_swaps_pages:
            all_swaps.extend(swaps)

        logger.info(f"Total de swaps obtenidos: {len(all_swaps)} (en {num_pages} páginas)")
        return all_swaps

    async def get_swaps_count(
        self,
        wallet: str,
        token: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        transaction_types: Optional[str] = None
    ) -> int:
        """
        Obtiene el número total de swaps de una wallet (requiere iterar todas las páginas).

        Args:
            wallet: Dirección de la wallet de Solana
            token: Dirección del token para filtrar swaps (opcional)
            from_date: Fecha de inicio para filtrar swaps (opcional)
            to_date: Fecha de fin para filtrar swaps (opcional)
            transaction_types: Tipos de transacción a filtrar. Valores posibles: 'buy', 'sell' o 'buy,sell' (opcional)

        Returns:
            Número total de swaps
        """
        all_swaps = await self.fetch_all_swaps(
            wallet=wallet,
            token=token,
            from_date=from_date,
            to_date=to_date,
            limit_per_page=100,  # Usar máximo para eficiencia
            transaction_types=transaction_types
        )
        return len(all_swaps)

    async def get_recent_swaps(
        self,
        wallet: str,
        token: Optional[str] = None,
        limit: int = 10,
        transaction_types: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene los swaps más recientes de una wallet.

        Args:
            wallet: Dirección de la wallet de Solana
            token: Dirección del token para filtrar swaps (opcional)
            limit: Número máximo de swaps a obtener (máximo 100)
            transaction_types: Tipos de transacción a filtrar. Valores posibles: 'buy', 'sell' o 'buy,sell' (opcional)

        Returns:
            Lista con los swaps más recientes
        """
        limit = self._validate_pagination_params(limit, "DESC")
        response = await self.fetch_swaps_page(
            wallet=wallet,
            token=token,
            limit=limit,
            order="DESC",
            transaction_types=transaction_types
        )
        return response.get("result", [])

    async def fetch_all_swaps_pages(
        self,
        wallet: str,
        token: Optional[str] = None,
        limit_per_page: int = 100,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        order: str = "DESC",
        max_pages: Optional[int] = None,
        transaction_types: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene todas las páginas de swaps de una wallet y retorna las respuestas completas.
        Útil cuando se necesita guardar las respuestas completas (incluyendo metadatos) en lugar de solo los swaps.

        Args:
            wallet: Dirección de la wallet de Solana
            token: Dirección del token para filtrar swaps (opcional)
            limit_per_page: Número máximo de resultados por página (máximo 100)
            from_date: Fecha de inicio para filtrar swaps (opcional)
            to_date: Fecha de fin para filtrar swaps (opcional)
            order: Orden de los resultados ("ASC" o "DESC"). Por defecto: "DESC"
            max_pages: Número máximo de páginas a obtener (None para todas)
            transaction_types: Tipos de transacción a filtrar. Valores posibles: 'buy', 'sell' o 'buy,sell' (opcional)

        Returns:
            Lista con todas las respuestas completas de Moralis (cada elemento es un Dict con 'result' y 'cursor')
        """
        logger.info(f"Obteniendo todas las páginas de swaps para wallet {wallet[:8]}...")

        def log_page(response: Dict[str, Any], page_count: int) -> Dict[str, Any]:
            """Callback que registra y retorna la respuesta completa"""
            logger.debug(f"Página {page_count + 1}: respuesta obtenida")
            return response

        all_pages, num_pages = await self._iterate_pages(
            wallet=wallet,
            token=token,
            limit_per_page=limit_per_page,
            from_date=from_date,
            to_date=to_date,
            order=order,
            max_pages=max_pages,
            process_page=log_page,
            transaction_types=transaction_types
        )

        logger.info(f"Total de páginas obtenidas: {len(all_pages)}")
        return all_pages

    async def save_swaps_to_file(
        self,
        wallet: str,
        file_path: str,
        token: Optional[str] = None,
        limit_per_page: int = 100,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        order: str = "DESC",
        max_pages: Optional[int] = None,
        single_page: bool = False,
        transaction_types: Optional[str] = None
    ) -> str:
        """
        Obtiene swaps de una wallet y los guarda en un archivo JSON usando aiofiles.
        Los datos siempre se guardan en una lista de páginas para mantener una estructura uniforme.
        Cada elemento de la lista es una respuesta completa de Moralis con 'result' y 'cursor'.

        Args:
            wallet: Dirección de la wallet de Solana
            file_path: Ruta del archivo donde guardar los datos (puede incluir directorios)
            token: Dirección del token para filtrar swaps (opcional)
            limit_per_page: Número máximo de resultados por página (máximo 100)
            from_date: Fecha de inicio para filtrar swaps (opcional)
            to_date: Fecha de fin para filtrar swaps (opcional)
            order: Orden de los resultados ("ASC" o "DESC"). Por defecto: "DESC"
            max_pages: Número máximo de páginas a obtener (None para todas, solo si single_page=False)
            single_page: Si True, solo obtiene y guarda una página. Si False, obtiene todas las páginas
            transaction_types: Tipos de transacción a filtrar. Valores posibles: 'buy', 'sell' o 'buy,sell' (opcional)

        Returns:
            Ruta del archivo donde se guardaron los datos

        Raises:
            OSError: Si no se puede crear el directorio o escribir el archivo
            aiohttp.ClientError: Si la petición falla

        Note:
            El archivo JSON siempre tendrá la estructura: [page1, page2, ...]
            Donde cada page es un Dict con 'result' (lista de swaps) y 'cursor' (opcional)
        """
        # Crear objeto Path para manejar la ruta
        path = Path(file_path)

        # Crear directorio padre si no existe (solo si hay un directorio en la ruta)
        parent_dir = path.parent
        if parent_dir and parent_dir != Path('.'):
            try:
                parent_dir.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Directorio verificado/creado: {parent_dir}")
            except OSError as e:
                logger.warning(f"No se pudo crear el directorio {parent_dir}: {e}")
                # Continuar de todas formas, puede que el directorio ya exista

        try:
            if single_page:
                # Obtener solo una página
                logger.info(f"Obteniendo una página de swaps para wallet {wallet[:8]}...")
                response = await self.fetch_swaps_page(
                    wallet=wallet,
                    token=token,
                    limit=limit_per_page,
                    from_date=from_date,
                    to_date=to_date,
                    order=order,
                    transaction_types=transaction_types
                )

                # Guardar en lista para mantener estructura uniforme
                data_to_save = [response]
                logger.debug(f"Una página obtenida: {len(response.get('result', []))} swaps")
            else:
                # Obtener todas las páginas
                logger.info(f"Obteniendo todas las páginas de swaps para wallet {wallet[:8]}...")
                all_pages = await self.fetch_all_swaps_pages(
                    wallet=wallet,
                    token=token,
                    limit_per_page=limit_per_page,
                    from_date=from_date,
                    to_date=to_date,
                    order=order,
                    max_pages=max_pages,
                    transaction_types=transaction_types
                )

                # Guardar lista de respuestas (siempre en lista para estructura uniforme)
                data_to_save = all_pages
                logger.debug(f"Páginas guardadas en lista: {len(all_pages)} página(s)")

            # Guardar en archivo JSON usando aiofiles
            async with aiofiles.open(path, 'w', encoding='utf-8') as f:
                json_content = json.dumps(data_to_save, indent=2, ensure_ascii=False)
                await f.write(json_content)

            # Calcular total de swaps guardados y número de páginas
            total_swaps, num_pages = self._calculate_swap_stats(data_to_save)

            logger.info(
                f"Swaps guardados exitosamente en {file_path}: "
                f"{total_swaps} swaps en {num_pages} página(s)"
            )

            return str(path)

        except Exception as e:
            logger.error(f"Error guardando swaps en {file_path}: {e}", exc_info=True)
            raise

    def _calculate_swap_stats(self, data: Any) -> tuple[int, int]:
        """
        Calcula estadísticas de swaps desde los datos guardados.
        Los datos siempre deben ser una lista de páginas (respuestas completas).

        Args:
            data: Lista de respuestas de Moralis (cada elemento es un Dict con 'result' y 'cursor')

        Returns:
            Tupla con (total_swaps, num_pages)
        """
        if isinstance(data, list) and len(data) > 0:
            # Verificar que sea una lista de páginas (respuestas completas)
            if isinstance(data[0], dict) and 'result' in data[0]:
                # Lista de páginas (respuestas completas)
                total_swaps = sum(len(page.get('result', [])) for page in data)
                num_pages = len(data)
            else:
                # Lista vacía o formato inesperado
                total_swaps = 0
                num_pages = 0
        else:
            # Datos vacíos o formato inesperado
            total_swaps = 0
            num_pages = 0
        return total_swaps, num_pages

    def get_api_key_masked(self) -> str:
        """Retorna la API key parcialmente oculta para logging seguro"""
        if not self.api_key:
            return "None"
        return f"{self.api_key[:8]}...{self.api_key[-4:]}"


class SolanaInvestmentStats:
    """
    Clase para calcular estadísticas de inversiones en Solana basadas en swaps de compra (buy).
    
    Puede trabajar con datos en memoria o cargarlos desde archivos JSON.
    Soporta filtrado por exchange(s) y cálculo de estadísticas generales o por exchange.
    """

    # Dirección del token SOL en Solana
    SOL_TOKEN_ADDRESS = "So11111111111111111111111111111111111111112"

    def __init__(self):
        """Inicializa el analizador de estadísticas"""
        self.buy_transactions: List[Dict[str, Any]] = []
        logger.debug("Analizador de estadísticas de inversiones inicializado")

    async def load_from_file(self, file_path: str) -> None:
        """
        Carga datos desde un archivo JSON.
        
        Args:
            file_path: Ruta del archivo JSON a cargar
            
        Raises:
            FileNotFoundError: Si el archivo no existe
            ValueError: Si el formato del archivo es inválido
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"El archivo {file_path} no existe")

        logger.info(f"Cargando datos desde {file_path}...")

        async with aiofiles.open(path, 'r', encoding='utf-8') as f:
            content = await f.read()
            data = json.loads(content)

        # El archivo debe ser una lista de páginas
        if not isinstance(data, list):
            raise ValueError("El archivo JSON debe contener una lista de páginas")

        # Extraer todas las transacciones de todas las páginas
        all_transactions = []
        for page in data:
            if isinstance(page, dict) and 'result' in page:
                all_transactions.extend(page.get('result', []))

        self.buy_transactions = [tx for tx in all_transactions if tx.get('transactionType') == 'buy']
        logger.info(f"Cargadas {len(self.buy_transactions)} transacciones de compra desde {file_path}")

    def load_from_data(self, data: List[Dict[str, Any]]) -> None:
        """
        Carga datos desde una estructura en memoria.
        
        Args:
            data: Puede ser:
                - Lista de páginas (cada página es un Dict con 'result')
                - Lista de transacciones directamente
        """
        logger.info("Cargando datos desde memoria...")

        if not data:
            self.buy_transactions = []
            logger.warning("No se proporcionaron datos")
            return

        all_transactions: List[Dict[str, Any]] = []

        # Si el primer elemento tiene 'result', es una lista de páginas
        first_item = data[0] if data else None
        if isinstance(first_item, dict) and 'result' in first_item:
            # Lista de páginas
            for page in data:
                if isinstance(page, dict) and 'result' in page:
                    page_result = page.get('result', [])
                    if isinstance(page_result, list):
                        all_transactions.extend(page_result)
        else:
            # Lista directa de transacciones
            for item in data:
                if isinstance(item, dict):
                    all_transactions.append(item)

        self.buy_transactions = [tx for tx in all_transactions if tx.get('transactionType') == 'buy']
        logger.info(f"Cargadas {len(self.buy_transactions)} transacciones de compra desde memoria")

    def _filter_by_exchanges(self, transactions: List[Dict[str, Any]], exchanges: Optional[List[str]]) -> List[Dict[str, Any]]:
        """
        Filtra transacciones por exchange(s).
        
        Args:
            transactions: Lista de transacciones
            exchanges: Lista de nombres de exchanges a filtrar (None para todos)
            
        Returns:
            Lista de transacciones filtradas
        """
        if not exchanges:
            return transactions

        exchanges_set = set(exchanges)
        filtered = [tx for tx in transactions if tx.get('exchangeName') in exchanges_set]
        logger.debug(f"Filtradas {len(filtered)} transacciones de {len(transactions)} por exchanges: {exchanges}")
        return filtered

    def _extract_sol_invested(self, transaction: Dict[str, Any]) -> Optional[float]:
        """
        Extrae la cantidad de SOL invertida de una transacción de compra.
        
        Args:
            transaction: Diccionario de transacción
            
        Returns:
            Cantidad de SOL invertida (None si no se puede extraer)
        """
        try:
            # Para transacciones 'buy', el SOL está en 'sold' (lo que se vendió para comprar)
            sold = transaction.get('sold')
            if not sold:
                return None

            # Verificar que sea SOL
            if sold.get('address') == self.SOL_TOKEN_ADDRESS:
                amount_str = sold.get('amount')
                if amount_str:
                    return float(amount_str)
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Error extrayendo SOL de transacción {transaction.get('transactionHash', 'unknown')}: {e}")

        return None

    def _extract_usd_invested(self, transaction: Dict[str, Any]) -> Optional[float]:
        """
        Extrae la cantidad en USD invertida de una transacción de compra.
        
        Args:
            transaction: Diccionario de transacción
            
        Returns:
            Cantidad en USD invertida (None si no se puede extraer)
        """
        try:
            sold = transaction.get('sold')
            if not sold:
                return None

            if sold.get('address') == self.SOL_TOKEN_ADDRESS:
                usd_amount = sold.get('usdAmount')
                if usd_amount is not None:
                    return float(usd_amount)
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Error extrayendo USD de transacción {transaction.get('transactionHash', 'unknown')}: {e}")

        return None

    def _calculate_percentile(self, values: List[float], percentile: float) -> float:
        """
        Calcula un percentil de una lista de valores usando interpolación lineal.
        
        Args:
            values: Lista de valores
            percentile: Percentil a calcular (0-100)
            
        Returns:
            Valor del percentil
        """
        if not values:
            return 0.0

        sorted_values = sorted(values)
        n = len(sorted_values)

        # Calcular la posición del percentil
        index = (percentile / 100) * (n - 1)
        lower_index = int(math.floor(index))
        upper_index = int(math.ceil(index))

        # Si el índice es exacto, retornar el valor
        if lower_index == upper_index:
            return sorted_values[lower_index]

        # Interpolación lineal
        weight = index - lower_index
        lower_value = sorted_values[lower_index]
        upper_value = sorted_values[upper_index]

        return lower_value + weight * (upper_value - lower_value)

    def calculate_stats(
        self,
        exchanges: Optional[List[str]] = None,
        include_percentiles: bool = True,
        percentiles: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Calcula estadísticas de inversiones en SOL.
        
        Args:
            exchanges: Lista de nombres de exchanges a filtrar (None para todos)
            include_percentiles: Si True, incluye cálculo de percentiles
            percentiles: Lista de percentiles a calcular (por defecto: [25, 50, 75, 90, 95, 99])
            
        Returns:
            Dict con estadísticas calculadas
        """
        if percentiles is None:
            percentiles = [25, 50, 75, 90, 95, 99]

        # Filtrar por exchanges
        filtered_transactions = self._filter_by_exchanges(self.buy_transactions, exchanges)

        if not filtered_transactions:
            logger.warning("No hay transacciones de compra para calcular estadísticas")
            return {
                'total_transactions': 0,
                'total_sol_invested': 0.0,
                'total_usd_invested': 0.0,
                'average_sol_invested': 0.0,
                'median_sol_invested': 0.0,
                'min_sol_invested': 0.0,
                'max_sol_invested': 0.0,
                'std_dev_sol_invested': 0.0,
                'exchanges': exchanges or 'all'
            }

        # Extraer cantidades de SOL y USD
        sol_amounts = []
        usd_amounts = []

        for tx in filtered_transactions:
            sol_amount = self._extract_sol_invested(tx)
            usd_amount = self._extract_usd_invested(tx)

            if sol_amount is not None:
                sol_amounts.append(sol_amount)
            if usd_amount is not None:
                usd_amounts.append(usd_amount)

        if not sol_amounts:
            logger.warning("No se pudieron extraer cantidades de SOL de las transacciones")
            return {
                'total_transactions': len(filtered_transactions),
                'total_sol_invested': 0.0,
                'total_usd_invested': 0.0,
                'average_sol_invested': 0.0,
                'median_sol_invested': 0.0,
                'min_sol_invested': 0.0,
                'max_sol_invested': 0.0,
                'std_dev_sol_invested': 0.0,
                'exchanges': exchanges or 'all'
            }

        # Calcular estadísticas básicas
        total_sol = sum(sol_amounts)
        total_usd = sum(usd_amounts) if usd_amounts else 0.0
        avg_sol = statistics.mean(sol_amounts)
        median_sol = statistics.median(sol_amounts)
        min_sol = min(sol_amounts)
        max_sol = max(sol_amounts)
        std_dev_sol = statistics.stdev(sol_amounts) if len(sol_amounts) > 1 else 0.0

        # Calcular percentiles
        percentile_stats = {}
        if include_percentiles:
            for p in percentiles:
                percentile_stats[f'percentile_{p}'] = self._calculate_percentile(sol_amounts, p)

        stats = {
            'total_transactions': len(filtered_transactions),
            'total_sol_invested': round(total_sol, 6),
            'total_usd_invested': round(total_usd, 2),
            'average_sol_invested': round(avg_sol, 6),
            'median_sol_invested': round(median_sol, 6),
            'min_sol_invested': round(min_sol, 6),
            'max_sol_invested': round(max_sol, 6),
            'std_dev_sol_invested': round(std_dev_sol, 6),
            'exchanges': exchanges or 'all'
        }

        if percentile_stats:
            stats.update(percentile_stats)

        return stats

    def calculate_stats_by_exchange(
        self,
        exchanges: Optional[List[str]] = None,
        include_percentiles: bool = True,
        percentiles: Optional[List[float]] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        Calcula estadísticas agrupadas por exchange.
        
        Args:
            exchanges: Lista de nombres de exchanges a incluir (None para todos)
            include_percentiles: Si True, incluye cálculo de percentiles
            percentiles: Lista de percentiles a calcular (por defecto: [25, 50, 75, 90, 95, 99])
            
        Returns:
            Dict con estadísticas por exchange {exchange_name: stats}
        """
        # Filtrar por exchanges si se especificaron
        filtered_transactions = self._filter_by_exchanges(self.buy_transactions, exchanges)

        # Agrupar por exchange
        by_exchange: Dict[str, List[Dict[str, Any]]] = {}
        for tx in filtered_transactions:
            exchange_name = tx.get('exchangeName', 'Unknown')
            if exchange_name not in by_exchange:
                by_exchange[exchange_name] = []
            by_exchange[exchange_name].append(tx)

        # Calcular estadísticas para cada exchange
        result = {}
        for exchange_name, transactions in by_exchange.items():
            # Crear instancia temporal para calcular stats
            temp_stats = SolanaInvestmentStats()
            temp_stats.buy_transactions = transactions
            result[exchange_name] = temp_stats.calculate_stats(
                exchanges=None,  # Ya están filtradas
                include_percentiles=include_percentiles,
                percentiles=percentiles
            )

        return result

    def get_exchange_list(self) -> List[str]:
        """
        Obtiene la lista de exchanges únicos en las transacciones de compra.
        
        Returns:
            Lista de nombres de exchanges
        """
        exchanges = set()
        for tx in self.buy_transactions:
            exchange_name = tx.get('exchangeName')
            if exchange_name:
                exchanges.add(exchange_name)
        return sorted(list(exchanges))

    def get_summary(self) -> Dict[str, Any]:
        """
        Obtiene un resumen general de las transacciones cargadas.
        
        Returns:
            Dict con resumen general
        """
        exchanges = self.get_exchange_list()
        total_stats = self.calculate_stats(exchanges=None, include_percentiles=False)

        return {
            'total_buy_transactions': len(self.buy_transactions),
            'exchanges_found': exchanges,
            'total_exchanges': len(exchanges),
            'total_sol_invested': total_stats.get('total_sol_invested', 0.0),
            'total_usd_invested': total_stats.get('total_usd_invested', 0.0),
            'average_sol_per_transaction': total_stats.get('average_sol_invested', 0.0)
        }
