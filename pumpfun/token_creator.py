# -*- coding: utf-8 -*-
"""
Módulo de Creación de Tokens y Wallets de PumpFun

Este módulo proporciona funcionalidades para:
- Crear wallets Lightning y API keys
- Crear tokens en múltiples plataformas (Pump.fun, Bonk, Moonshot)
- Gestionar metadatos y uploads a IPFS
- Soporte para transacciones Lightning, Local y Jito Bundle
"""

import asyncio
import json
import base64
from typing import Optional, Literal, Union, Dict, Any, List, BinaryIO
from pathlib import Path
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from .api_client import PumpFunApiClient, ApiClientException

# Tipos para validación estática
PoolType = Literal["pump", "bonk", "moonshot"]
TransactionType = Literal["lightning", "local", "bundle"]


class TokenMetadata:
    """Clase para gestionar metadatos de tokens"""
    
    def __init__(
        self,
        name: str,
        symbol: str,
        description: str = "",
        twitter: str = "",
        telegram: str = "",
        website: str = "",
        show_name: bool = True
    ):
        self.name = name
        self.symbol = symbol
        self.description = description
        self.twitter = twitter
        self.telegram = telegram
        self.website = website
        self.show_name = show_name

    def to_dict(self) -> Dict[str, Any]:
        """Convierte los metadatos a diccionario"""
        return {
            'name': self.name,
            'symbol': self.symbol,
            'description': self.description,
            'twitter': self.twitter,
            'telegram': self.telegram,
            'website': self.website,
            'showName': str(self.show_name).lower()
        }

    def with_uri(self, uri: str) -> Dict[str, Any]:
        """Añade URI a los metadatos"""
        return {
            'name': self.name,
            'symbol': self.symbol,
            'uri': uri
        }


class PumpFunTokenCreator:
    """
    Gestiona la creación de wallets y tokens en Pump.fun
    Soporta múltiples plataformas y métodos de transacción
    """

    def __init__(self, api_client: Optional[PumpFunApiClient] = None, api_key: Optional[str] = None):
        """
        Inicializa el creador de tokens.

        Args:
            api_client: Una instancia existente de PumpFunApiClient
            api_key: La clave API para transacciones Lightning
        """
        self.client = api_client or PumpFunApiClient(api_key=api_key, enable_websocket=False)
        self._api_key = api_key or (self.client.api_key if self.client else None)

    async def __aenter__(self):
        """Context manager entry"""
        print("🔌 Iniciando sesión de creación de tokens...")
        # Solo conectar HTTP ya que no necesitamos WebSocket para creación de tokens
        if self.client.enable_http:
            await self.client._connect_http()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        print("🔌 Cerrando sesión de creación de tokens...")
        # Solo desconectar HTTP
        if self.client._http_session:
            await self.client._disconnect_http()
        print("✅ Sesión de creación de tokens cerrada correctamente")

    # ============================================================================
    # UPLOAD DE METADATOS
    # ============================================================================

    async def upload_image_to_ipfs(self, image_path: Union[str, Path], platform: PoolType = "pump") -> str:
        """
        Sube una imagen a IPFS según la plataforma.

        Args:
            image_path: Ruta al archivo de imagen
            platform: Plataforma destino (pump, bonk, moonshot)

        Returns:
            URI de la imagen en IPFS
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Imagen no encontrada: {image_path}")

        print(f"📤 Subiendo imagen a IPFS para {platform}...")

        try:
            if platform == "pump":
                # Usar IPFS de Pump.fun
                with open(image_path, 'rb') as f:
                    files = {'file': (image_path.name, f, 'image/png')}
                    response = await self.client.http_post_files(endpoint="ipfs", files=files)
                return response.get('metadataUri', '')
            
            elif platform in ["bonk", "moonshot"]:
                # Usar NFT Storage workers
                with open(image_path, 'rb') as f:
                    files = {'image': (image_path.name, f, 'image/png')}
                    response = await self.client.http_post_files(
                        endpoint="",  # URL completa se maneja en el método
                        files=files,
                        url="https://nft-storage.letsbonk22.workers.dev/upload/img"
                    )
                return response

        except Exception as e:
            print(f"❌ Error subiendo imagen: {e}")
            raise ApiClientException(f"Error subiendo imagen: {e}")

    async def create_token_metadata(
        self,
        metadata: TokenMetadata,
        image_uri: str,
        platform: PoolType = "pump"
    ) -> str:
        """
        Crea metadatos de token en IPFS.

        Args:
            metadata: Objeto TokenMetadata
            image_uri: URI de la imagen en IPFS
            platform: Plataforma destino

        Returns:
            URI de los metadatos en IPFS
        """
        print(f"📝 Creando metadatos para {platform}...")

        try:
            if platform == "pump":
                # Usar IPFS de Pump.fun
                form_data = metadata.to_dict()
                form_data['file'] = image_uri
                
                response = await self.client.http_post(endpoint="ipfs", data=form_data)
                return response.get('metadataUri', '')
            
            elif platform in ["bonk", "moonshot"]:
                # Usar NFT Storage workers
                meta_data = {
                    'description': metadata.description,
                    'image': image_uri,
                    'name': metadata.name,
                    'symbol': metadata.symbol,
                    'website': metadata.website
                }
                
                if platform == "bonk":
                    meta_data['createdOn'] = "https://bonk.fun"
                
                response = await self.client.http_post(
                    endpoint="",  # URL completa se maneja en el método
                    data=json.dumps(meta_data),
                    headers={'Content-Type': 'application/json'},
                    url="https://nft-storage.letsbonk22.workers.dev/upload/meta"
                )
                return response

        except Exception as e:
            print(f"❌ Error creando metadatos: {e}")
            raise ApiClientException(f"Error creando metadatos: {e}")

    # ============================================================================
    # CREACIÓN DE TOKENS
    # ============================================================================

    async def create_token_lightning(
        self,
        metadata: TokenMetadata,
        image_path: Union[str, Path],
        amount: float,
        platform: PoolType = "pump",
        slippage: float = 10,
        priority_fee: float = 0.00005
    ) -> Dict[str, Any]:
        """
        Crea un token usando transacción Lightning.

        Args:
            metadata: Metadatos del token
            image_path: Ruta a la imagen del token
            amount: Cantidad inicial (SOL/USDC)
            platform: Plataforma destino
            slippage: Porcentaje de deslizamiento
            priority_fee: Tarifa de prioridad

        Returns:
            Respuesta de la transacción
        """
        if not self._api_key:
            raise ApiClientException("Se requiere API key para transacciones Lightning")

        print(f"🚀 Creando token Lightning en {platform}...")

        try:
            # 1. Generar mint keypair
            mint_keypair = Keypair()
            print(f"🏦 Mint address: {mint_keypair.pubkey()}")

            # 2. Subir imagen
            image_uri = await self.upload_image_to_ipfs(image_path, platform)

            # 3. Crear metadatos
            token_uri = await self.create_token_metadata(metadata, image_uri, platform)
            token_metadata = metadata.with_uri(token_uri)

            # 4. Crear token
            payload = {
                'action': 'create',
                'tokenMetadata': token_metadata,
                'mint': str(mint_keypair.pubkey()),
                'denominatedInSol': 'true' if platform != "moonshot" else 'false',
                'amount': amount,
                'slippage': slippage,
                'priorityFee': priority_fee,
                'pool': platform
            }

            response = await self.client.http_post(endpoint="trade", data=payload, use_api_key=True)
            print(f"✅ Token creado: {response.get('signature', 'N/A')}")
            return response

        except Exception as e:
            print(f"❌ Error creando token Lightning: {e}")
            raise ApiClientException(f"Error creando token Lightning: {e}")

    async def create_token_local(
        self,
        keypair: Keypair,
        metadata: TokenMetadata,
        image_path: Union[str, Path],
        amount: float,
        platform: PoolType = "pump",
        slippage: float = 10,
        priority_fee: float = 0.00005,
        rpc_endpoint: str = "https://api.mainnet-beta.solana.com/"
    ) -> str:
        """
        Crea un token usando transacción local.

        Args:
            keypair: Keypair del usuario para firmar
            metadata: Metadatos del token
            image_path: Ruta a la imagen del token
            amount: Cantidad inicial (SOL/USDC)
            platform: Plataforma destino
            slippage: Porcentaje de deslizamiento
            priority_fee: Tarifa de prioridad
            rpc_endpoint: Endpoint RPC de Solana

        Returns:
            Firma de la transacción
        """
        print(f"🛠️ Creando token local en {platform}...")

        try:
            # 1. Generar mint keypair
            mint_keypair = Keypair()
            print(f"🏦 Mint address: {mint_keypair.pubkey()}")

            # 2. Subir imagen
            image_uri = await self.upload_image_to_ipfs(image_path, platform)

            # 3. Crear metadatos
            token_uri = await self.create_token_metadata(metadata, image_uri, platform)
            token_metadata = metadata.with_uri(token_uri)

            # 4. Crear transacción
            payload = {
                'publicKey': str(keypair.pubkey()),
                'action': 'create',
                'tokenMetadata': token_metadata,
                'mint': str(mint_keypair.pubkey()),
                'denominatedInSol': 'true' if platform != "moonshot" else 'false',
                'amount': amount,
                'slippage': slippage,
                'priorityFee': priority_fee,
                'pool': platform
            }

            # 5. Obtener transacción serializada
            tx_bytes = await self.client.http_post_raw(endpoint="trade-local", data=payload)
            if not tx_bytes:
                raise ApiClientException("No se recibieron datos de la transacción")

            # 6. Firmar transacción
            unsigned_tx = VersionedTransaction.from_bytes(tx_bytes)
            signed_tx = VersionedTransaction(unsigned_tx.message, [mint_keypair, keypair])

            # 7. Enviar transacción
            tx_signature = await self.client.send_signed_transaction(signed_tx, rpc_endpoint)
            print(f"✅ Token creado: {tx_signature}")
            return tx_signature

        except Exception as e:
            print(f"❌ Error creando token local: {e}")
            raise ApiClientException(f"Error creando token local: {e}")

    # ============================================================================
    # MÉTODOS DE CONVENIENCIA
    # ============================================================================

    async def create_token(
        self,
        keypair: Optional[Keypair],
        metadata: TokenMetadata,
        image_path: Union[str, Path],
        amount: float,
        platform: PoolType = "pump",
        transaction_type: TransactionType = "lightning",
        slippage: float = 10,
        priority_fee: float = 0.00005,
        rpc_endpoint: str = "https://api.mainnet-beta.solana.com/"
    ) -> Union[Dict[str, Any], str]:
        """
        Método de conveniencia para crear tokens.

        Args:
            keypair: Keypair del usuario (requerido para transacciones locales)
            metadata: Metadatos del token
            image_path: Ruta a la imagen
            amount: Cantidad inicial
            platform: Plataforma destino
            transaction_type: Tipo de transacción
            slippage: Porcentaje de deslizamiento
            priority_fee: Tarifa de prioridad
            rpc_endpoint: Endpoint RPC (solo para transacciones locales)

        Returns:
            Respuesta de la transacción
        """
        if transaction_type == "lightning":
            return await self.create_token_lightning(
                metadata, image_path, amount, platform, slippage, priority_fee
            )
        elif transaction_type == "local":
            if not keypair:
                raise ValueError("Keypair es requerido para transacciones locales")
            return await self.create_token_local(
                keypair, metadata, image_path, amount, platform, slippage, priority_fee, rpc_endpoint
            )
        else:
            raise ValueError(f"Tipo de transacción no soportado: {transaction_type}")

    def get_status(self) -> Dict[str, Any]:
        """Obtiene el estado actual del creador de tokens"""
        return {
            'api_key_configured': bool(self._api_key),
            'client_status': self.client.get_status() if self.client else None
        } 