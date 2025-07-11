# -*- coding: utf-8 -*-
from datetime import datetime
from typing import Optional, Dict
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
import json
import base58
import os
import aiofiles


class SolanaWalletManager:
    """Gestor de wallets para Solana - Crear, cargar y guardar wallets"""

    def __init__(self, network: str = "devnet", rpc_url: str = None):
        """
        Inicializa el gestor de wallets
        network: "devnet", "testnet", "mainnet-beta"
        rpc_url: URL personalizada del RPC (opcional)
        """
        self.network = network
        self.rpc_url = rpc_url
        self.rpc_urls = {
            "devnet": "https://api.devnet.solana.com",
            "testnet": "https://api.testnet.solana.com", 
            "mainnet-beta": "https://api.mainnet-beta.solana.com"
        }

        self.client: Optional[AsyncClient] = None
        self.keypair: Optional[Keypair] = None

    async def __aenter__(self):
        """Entra en el context manager asíncrono, conectando el cliente."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Sale del context manager asíncrono, cerrando la conexión."""
        await self.close()

    async def connect(self):
        """Conecta el cliente asíncrono a la red Solana."""
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

    async def close(self):
        """Cierra la conexión del cliente asíncrono."""
        if self.client:
            await self.client.close()
            self.client = None
            print("🔌 Conexión a Solana cerrada.")

    async def create_wallet_file(self, filename: str = None) -> str:
        """Crea una nueva wallet y la guarda en archivo"""
        try:
            # Crear nuevo keypair
            keypair = Keypair()
            secret_key_bytes = bytes(keypair)

            wallet_info = {
                'public_key': str(keypair.pubkey()),
                'private_key': base58.b58encode(secret_key_bytes).decode('utf-8'),
                'network': self.network,
                'created_at': datetime.now().isoformat()
            }

            # Generar nombre de archivo si no se proporciona
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"wallets/wallet_{timestamp}.json"
            else:
                # Si se proporciona un nombre sin ruta, ponerlo en wallets/
                if '/' not in filename and '\\' not in filename:
                    filename = f"wallets/{filename}"

            # Asegurar que el directorio wallets/ existe
            wallet_dir = os.path.dirname(filename) if '/' in filename or '\\' in filename else 'wallets'
            if wallet_dir and not os.path.exists(wallet_dir):
                os.makedirs(wallet_dir, exist_ok=True)

            # Guardar en archivo de forma asíncrona
            async with aiofiles.open(filename, 'w') as f:
                await f.write(json.dumps(wallet_info, indent=2))

            # Cargar el keypair en la instancia
            self.keypair = keypair

            print("✅ Nueva wallet creada exitosamente")
            print(f"📍 Dirección pública: {wallet_info['public_key']}")
            print(f"💾 Guardada en: {filename}")
            print("⚠️  GUARDA EL ARCHIVO EN UN LUGAR SEGURO")

            return filename

        except Exception as e:
            print(f"❌ Error creando wallet: {e}")
            return None

    async def load_wallet(self, filename: str) -> bool:
        """Carga una wallet desde archivo"""
        try:
            async with aiofiles.open(filename, 'r') as f:
                content = await f.read()
                wallet_info = json.loads(content)

            # Cargar keypair desde clave privada
            private_key = wallet_info['private_key']
            secret_key = base58.b58decode(private_key)
            self.keypair = Keypair.from_bytes(secret_key)

            print(f"📂 Wallet cargada desde {filename}")
            print(f"📍 Dirección: {self.keypair.pubkey()}")
            return True

        except Exception as e:
            print(f"❌ Error cargando wallet desde archivo: {e}")
            return False

    async def create_new_wallet(self) -> Dict[str, str]:
        """Crea una nueva wallet con par de claves (método legacy)"""
        try:
            keypair = Keypair()
            secret_key_bytes = bytes(keypair)

            wallet_info = {
                'public_key': str(keypair.pubkey()),
                'private_key': base58.b58encode(secret_key_bytes).decode('utf-8'),
                'network': self.network,
                'created_at': datetime.now().isoformat()
            }

            print("✅ Nueva wallet creada exitosamente")
            print(f"📍 Dirección pública: {wallet_info['public_key']}")
            print(f"🔐 Clave privada: {wallet_info['private_key'][:20]}...")
            print("⚠️  GUARDA LA CLAVE PRIVADA EN UN LUGAR SEGURO")

            return wallet_info

        except Exception as e:
            print(f"❌ Error creando wallet: {e}")
            return {}

    async def load_wallet_from_private_key(self, private_key: str) -> Optional[Keypair]:
        """Carga una wallet desde clave privada"""
        try:
            secret_key = base58.b58decode(private_key)
            keypair = Keypair.from_bytes(secret_key)

            # Cargar en la instancia
            self.keypair = keypair

            print("✅ Wallet cargada exitosamente")
            print(f"📍 Dirección: {keypair.pubkey()}")

            return keypair

        except Exception as e:
            print(f"❌ Error cargando wallet: {e}")
            return None

    async def save_wallet_to_file(self, wallet_info: Dict[str, str], filename: str = "wallets/wallet.json") -> None:
        """Guarda información de wallet en archivo"""
        try:
            # Asegurar que el directorio wallets/ existe
            wallet_dir = os.path.dirname(filename) if '/' in filename or '\\' in filename else 'wallets'
            if wallet_dir and not os.path.exists(wallet_dir):
                os.makedirs(wallet_dir, exist_ok=True)
                
            async with aiofiles.open(filename, 'w') as f:
                await f.write(json.dumps(wallet_info, indent=2))
            print(f"💾 Wallet guardada en {filename}")

        except Exception as e:
            print(f"❌ Error guardando wallet: {e}")

    async def load_wallet_from_file(self, filename: str = "wallets/wallet.json") -> Optional[Dict[str, str]]:
        """Carga wallet desde archivo"""
        try:
            async with aiofiles.open(filename, 'r') as f:
                content = await f.read()
                wallet_info = json.loads(content)
            print(f"📂 Wallet cargada desde {filename}")
            return wallet_info

        except Exception as e:
            print(f"❌ Error cargando wallet desde archivo: {e}")
            return None

    def get_address(self) -> Optional[str]:
        """Obtiene la dirección pública de la wallet activa"""
        if self.keypair:
            return str(self.keypair.pubkey())
        return None

    def is_wallet_loaded(self) -> bool:
        """Verifica si hay una wallet cargada"""
        return self.keypair is not None

    async def create_wallet(self) -> Optional[Keypair]:
        """Crea una nueva wallet y retorna el keypair"""
        try:
            keypair = Keypair()
            self.keypair = keypair
            print("✅ Nueva wallet creada")
            print(f"📍 Dirección: {str(keypair.pubkey())}")
            return keypair
        except Exception as e:
            print(f"❌ Error creando wallet: {e}")
            return None

    async def save_wallet(self, filename: str) -> bool:
        """Guarda la wallet actual en un archivo"""
        if not self.keypair:
            print("❌ No hay wallet cargada para guardar")
            return False

        try:
            # Asegurar que el directorio wallets/ existe si no se especifica ruta completa
            if '/' not in filename and '\\' not in filename:
                filename = f"wallets/{filename}"

            wallet_dir = os.path.dirname(filename)
            if wallet_dir and not os.path.exists(wallet_dir):
                os.makedirs(wallet_dir, exist_ok=True)

            secret_key_bytes = bytes(self.keypair)
            wallet_info = {
                'public_key': str(self.keypair.pubkey()),
                'private_key': base58.b58encode(secret_key_bytes).decode('utf-8'),
                'network': self.network,
                'created_at': datetime.now().isoformat()
            }

            async with aiofiles.open(filename, 'w') as f:
                await f.write(json.dumps(wallet_info, indent=2))

            print(f"💾 Wallet guardada en {filename}")
            return True
        except Exception as e:
            print(f"❌ Error guardando wallet: {e}")
            return False 