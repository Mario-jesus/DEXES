# -*- coding: utf-8 -*-
"""
Módulo de Utilidades Asíncronas para Solana

Este módulo proporciona un conjunto completo de utilidades asíncronas para trabajar
con la blockchain de Solana, incluyendo validación de direcciones, conversiones
de unidades, obtención de precios y operaciones en lote.

Características principales:
- Validación asíncrona de direcciones de Solana
- Conversiones entre SOL y lamports de forma asíncrona
- Obtención de precios de SOL desde APIs externas
- Operaciones en lote para mejor rendimiento
- Conexión directa a la red Solana usando AsyncClient
- Manejo robusto de errores y timeouts
"""
from datetime import datetime
from typing import Dict, Any, Optional, List, Literal
import base58
import aiohttp
import asyncio
from solana.rpc.async_api import AsyncClient


class SolanaUtils:
    """
    Utilidades asíncronas para trabajar con Solana.
    
    Esta clase proporciona métodos asíncronos para validar direcciones,
    convertir unidades, obtener precios y realizar operaciones en lote
    relacionadas con la blockchain de Solana.
    """

    def __init__(self, network: Literal["mainnet-beta", "devnet", "testnet"] = "mainnet-beta",
                    rpc_url: str = None):
        """
        Inicializa las utilidades de Solana.
        
        Args:
            network (str): Red de Solana a conectar ("mainnet-beta", "devnet", "testnet")
            rpc_url (str, optional): URL personalizada del RPC. Si no se proporciona,
                se usa la URL por defecto de la red especificada.
        """
        self.network = network
        self.rpc_url = rpc_url
        self.client: Optional[AsyncClient] = None
        self._http_session: Optional[aiohttp.ClientSession] = None

        # URLs por defecto para cada red
        self.rpc_urls = {
            "devnet": "https://api.devnet.solana.com",
            "testnet": "https://api.testnet.solana.com", 
            "mainnet-beta": "https://api.mainnet-beta.solana.com"
        }

    async def __aenter__(self):
        """
        Inicializa la conexión a Solana y la sesión HTTP al entrar en el context manager.
        
        Returns:
            SolanaUtils: Instancia de la clase para uso en context manager.
        """
        await self._connect_to_solana()
        await self._get_http_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Cierra la conexión a Solana y la sesión HTTP al salir del context manager.
        
        Args:
            exc_type: Tipo de excepción (si ocurrió)
            exc_val: Valor de la excepción
            exc_tb: Traceback de la excepción
        """
        await self.close_http_session()
        await self._disconnect_from_solana()

    async def _connect_to_solana(self):
        """
        Conecta a la red Solana usando AsyncClient.
        
        Establece la conexión RPC con la red especificada en la inicialización.
        """
        if self.client:
            return

        rpc_url_to_use = self.rpc_url if self.rpc_url else self.rpc_urls.get(self.network)
        if not rpc_url_to_use:
            raise ValueError(f"No se encontró RPC URL para la red: {self.network}")

        self.client = AsyncClient(rpc_url_to_use)
        is_connected = await self.client.is_connected()
        if is_connected:
            print(f"🌐 Conectado a Solana {self.network} (RPC: {rpc_url_to_use})")
        else:
            print(f"🔌 No se pudo conectar a Solana {self.network}. Por favor, verifica la RPC URL.")
            self.client = None

    async def _disconnect_from_solana(self):
        """
        Cierra la conexión a Solana de forma segura.
        """
        if self.client:
            await self.client.close()
            self.client = None
            print("🔌 Conexión a Solana cerrada.")

    async def _get_http_session(self) -> aiohttp.ClientSession:
        """
        Obtiene o crea una sesión HTTP asíncrona.
        
        Crea una nueva sesión HTTP si no existe o si está cerrada.
        Esto permite reutilizar la conexión para múltiples requests.
        
        Returns:
            aiohttp.ClientSession: Sesión HTTP activa.
        """
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close_http_session(self):
        """
        Cierra la sesión HTTP de forma segura.
        
        Verifica si la sesión existe y no está cerrada antes de cerrarla,
        evitando errores por intentar cerrar una sesión ya cerrada.
        """
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    async def validate_address(self, address: str) -> bool:
        """
        Valida si una dirección de Solana es válida de forma asíncrona.
        
        Realiza las siguientes validaciones:
        1. Verifica que la dirección no esté vacía
        2. Comprueba que la longitud esté entre 32 y 44 caracteres
        3. Decodifica la dirección usando base58
        4. Verifica que el resultado tenga exactamente 32 bytes
        
        Args:
            address (str): Dirección de Solana a validar (formato base58).
            
        Returns:
            bool: True si la dirección es válida, False en caso contrario.
        """
        try:
            if not address or len(address) < 32 or len(address) > 44:
                return False

            # Usar asyncio para no bloquear el event loop
            loop = asyncio.get_event_loop()
            decoded = await loop.run_in_executor(None, base58.b58decode, address)
            return len(decoded) == 32
        except Exception:
            return False

    async def get_network_info(self) -> Dict[str, Any]:
        """
        Obtiene información detallada de la red Solana de forma asíncrona.
        
        Requiere que se haya establecido conexión a la red Solana.
        Obtiene información como el slot actual, red conectada y estado de conexión.
        
        Returns:
            Dict[str, Any]: Diccionario con información de la red:
                - network (str): Nombre de la red (mainnet-beta, devnet, etc.)
                - rpc_url (str): URL del endpoint RPC
                - current_slot (int): Slot actual de la blockchain
                - status (str): Estado de la conexión
                - timestamp (str): Timestamp de la consulta
                
        Raises:
            Exception: Si no hay conexión a la red o error en la consulta.
        """
        if not self.client:
            print("❌ No hay conexión a la red. Conecta a Solana primero.")
            return {}

        try:
            slot = await self.client.get_slot()
            info = {
                'network': self.network,
                'rpc_url': self.rpc_urls.get(self.network) if self.rpc_url is None else self.rpc_url,
                'current_slot': slot.value if slot.value else 0,
                'status': 'connected',
                'timestamp': datetime.now().isoformat()
            }
            print("🌐 Información de red:")
            print(f"   Red: {info['network']}")
            print(f"   Slot actual: {info['current_slot']:,}")
            print(f"   Estado: {info['status']}")
            return info
        except Exception as e:
            print(f"❌ Error obteniendo info de red: {e}")
            return {}

    async def convert_lamports_to_sol(self, lamports: int) -> float:
        """
        Convierte lamports a SOL de forma asíncrona.
        
        Un lamport es la unidad más pequeña de SOL (1 SOL = 1,000,000,000 lamports).
        Esta conversión se realiza de forma asíncrona para no bloquear el event loop.
        
        Args:
            lamports (int): Cantidad de lamports a convertir.
            
        Returns:
            float: Cantidad equivalente en SOL.
        """
        # Usar asyncio para operaciones matemáticas pesadas
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: lamports / 1_000_000_000)

    async def convert_sol_to_lamports(self, sol: float) -> int:
        """
        Convierte SOL a lamports de forma asíncrona.
        
        Convierte una cantidad de SOL a su equivalente en lamports.
        El resultado se redondea hacia abajo para evitar errores de precisión.
        
        Args:
            sol (float): Cantidad de SOL a convertir.
            
        Returns:
            int: Cantidad equivalente en lamports.
        """
        # Usar asyncio para operaciones matemáticas pesadas
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: int(sol * 1_000_000_000))

    async def format_balance(self, lamports: int) -> str:
        """
        Formatea el balance de lamports en un string legible de forma asíncrona.
        
        Convierte lamports a SOL y formatea el resultado mostrando tanto
        la cantidad en SOL como en lamports para mayor claridad.
        
        Args:
            lamports (int): Cantidad de lamports a formatear.
            
        Returns:
            str: String formateado con el balance (ej: "1.000000000 SOL (1000000000 lamports)").
        """
        sol = await self.convert_lamports_to_sol(lamports)
        return f"{sol:.9f} SOL ({lamports:,} lamports)"

    async def get_solana_price_usd(self) -> float:
        """
        Obtiene el precio actual de SOL en USD de forma asíncrona.
        
        Realiza una consulta HTTP a la API de CoinGecko para obtener
        el precio actual de SOL en dólares estadounidenses.
        
        Returns:
            float: Precio de SOL en USD, o 0.0 si hay error.
        """
        session = await self._get_http_session()
        url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    price = data.get('solana', {}).get('usd', 0.0)
                    print(f"💵 Precio SOL: ${price:.2f} USD")
                    return price
                else:
                    print("❌ No se pudo obtener el precio de SOL")
                    return 0.0
        except Exception as e:
            print(f"❌ Error obteniendo precio SOL: {e}")
            return 0.0

    async def calculate_sol_value_usd(self, sol_amount: float) -> float:
        """
        Calcula el valor en USD de una cantidad de SOL de forma asíncrona.
        
        Obtiene el precio actual de SOL y multiplica por la cantidad
        especificada para obtener el valor total en dólares.
        
        Args:
            sol_amount (float): Cantidad de SOL para calcular su valor.
            
        Returns:
            float: Valor en USD de la cantidad de SOL, o 0.0 si hay error.
        """
        try:
            price_usd = await self.get_solana_price_usd()
            if price_usd > 0:
                # Usar asyncio para operaciones matemáticas
                loop = asyncio.get_event_loop()
                value_usd = await loop.run_in_executor(None, lambda: sol_amount * price_usd)
                print(f"💰 {sol_amount} SOL = ${value_usd:.2f} USD")
                return value_usd
            return 0.0
        except Exception as e:
            print(f"❌ Error calculando valor USD: {e}")
            return 0.0

    async def get_multiple_addresses_info(self, addresses: List[str]) -> Dict[str, Any]:
        """
        Obtiene información de múltiples direcciones de forma asíncrona.
        
        Valida cada dirección de la lista y retorna un diccionario con
        el estado de validación de cada una. Útil para procesar grandes
        cantidades de direcciones de forma eficiente.
        
        Args:
            addresses (List[str]): Lista de direcciones de Solana a validar.
            
        Returns:
            Dict[str, Any]: Diccionario con información de cada dirección:
                - Para direcciones válidas: {'valid': True, 'checked_at': timestamp}
                - Para direcciones inválidas: {'valid': False, 'error': 'mensaje'}
        """
        try:
            results = {}
            for address in addresses:
                if await self.validate_address(address):
                    # Aquí podrías agregar más información de cada dirección
                    results[address] = {
                        'valid': True,
                        'checked_at': datetime.now().isoformat()
                    }
                else:
                    results[address] = {
                        'valid': False,
                        'error': 'Dirección inválida'
                    }

            print(f"✅ Validadas {len(addresses)} direcciones")
            return results
        except Exception as e:
            print(f"❌ Error validando direcciones: {e}")
            return {}

    async def batch_convert_lamports(self, lamports_list: List[int]) -> List[float]:
        """
        Convierte múltiples cantidades de lamports a SOL de forma asíncrona.
        
        Procesa todas las conversiones en paralelo usando asyncio.gather(),
        lo que proporciona mejor rendimiento que convertir una por una.
        
        Args:
            lamports_list (List[int]): Lista de cantidades en lamports a convertir.
            
        Returns:
            List[float]: Lista con las cantidades convertidas a SOL.
        """
        try:
            tasks = [self.convert_lamports_to_sol(lamports) for lamports in lamports_list]
            results = await asyncio.gather(*tasks)
            return results
        except Exception as e:
            print(f"❌ Error en conversión batch: {e}")
            return []

    async def get_network_status(self) -> Dict[str, Any]:
        """
        Obtiene el estado completo de la red de forma asíncrona.
        
        Realiza consultas paralelas para obtener información detallada
        del estado de la red Solana, incluyendo slot actual y conectividad.
        
        Returns:
            Dict[str, Any]: Diccionario con estado de la red:
                - connected (bool): True si hay conexión activa
                - current_slot (int): Slot actual de la blockchain
                - network (str): Nombre de la red conectada
                - timestamp (str): Timestamp de la consulta
                - status (str): 'disconnected' si no hay conexión
                - error (str): Mensaje de error si ocurre algún problema
        """
        if not self.client:
            return {'status': 'disconnected'}

        try:
            # Obtener múltiples informaciones en paralelo
            slot_task = self.client.get_slot()
            # Aquí podrías agregar más llamadas paralelas

            slot = await slot_task

            status = {
                'connected': True,
                'current_slot': slot.value if slot.value else 0,
                'network': self.network,
                'timestamp': datetime.now().isoformat()
            }

            return status
        except Exception as e:
            print(f"❌ Error obteniendo estado de red: {e}")
            return {'status': 'error', 'error': str(e)}
