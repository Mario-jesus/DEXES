# -*- coding: utf-8 -*-
"""
Módulo de Gestión de Wallets de PumpFun

Este módulo proporciona funcionalidades para:
- Crear wallets Lightning y API keys
- Gestionar datos de wallets (API key, public key, private key)
- Validar y almacenar información de wallets de forma segura
- Integración con el sistema DEXES
- Cargar wallets desde archivos en diferentes formatos
"""

import json
from typing import Optional, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
import aiofiles
from solders.keypair import Keypair

from .api_client import PumpFunHttpApiClient, ApiClientException


# ============================================================================
# EXCEPCIONES PERSONALIZADAS
# ============================================================================

class WalletException(Exception):
    """Excepción base para errores relacionados con wallets"""
    pass


class WalletValidationException(WalletException):
    """Excepción para errores de validación de wallet"""

    def __init__(self, message: str, field: str = None, value: str = None):
        self.field = field
        self.value = value
        super().__init__(message)


class WalletCreationException(WalletException):
    """Excepción para errores en la creación de wallets"""

    def __init__(self, message: str, api_response: dict = None):
        self.api_response = api_response
        super().__init__(message)


class WalletStorageException(WalletException):
    """Excepción para errores de almacenamiento de wallets"""

    def __init__(self, message: str, file_path: str = None, operation: str = None):
        self.file_path = file_path
        self.operation = operation
        super().__init__(message)


class WalletImportException(WalletException):
    """Excepción para errores en la importación de wallets"""

    def __init__(self, message: str, file_path: str = None, format_type: str = None):
        self.file_path = file_path
        self.format_type = format_type
        super().__init__(message)


class WalletExportException(WalletException):
    """Excepción para errores en la exportación de wallets"""

    def __init__(self, message: str, file_path: str = None, format_type: str = None):
        self.file_path = file_path
        self.format_type = format_type
        super().__init__(message)


class WalletKeypairException(WalletException):
    """Excepción para errores relacionados con Keypairs"""

    def __init__(self, message: str, public_key: str = None, private_key_short: str = None):
        self.public_key = public_key
        self.private_key_short = private_key_short[:20] + "..." if private_key_short and len(private_key_short) > 20 else private_key_short
        super().__init__(message)


class WalletNotFoundException(WalletException):
    """Excepción para cuando no se encuentra una wallet"""

    def __init__(self, message: str, search_criteria: str = None, search_value: str = None):
        self.search_criteria = search_criteria
        self.search_value = search_value
        super().__init__(message)


class WalletDuplicateException(WalletException):
    """Excepción para wallets duplicadas"""

    def __init__(self, message: str, existing_wallet_public_key: str = None):
        self.existing_wallet_public_key = existing_wallet_public_key
        super().__init__(message)


class WalletBackupException(WalletException):
    """Excepción para errores en backup de wallets"""

    def __init__(self, message: str, backup_path: str = None, wallet_count: int = None):
        self.backup_path = backup_path
        self.wallet_count = wallet_count
        super().__init__(message)


# ============================================================================
# CLASES DE DATOS
# ============================================================================

@dataclass
class WalletData:
    """Estructura de datos para información de wallet"""
    api_key: str
    wallet_public_key: str
    private_key: str
    created_at: str
    platform: str = "pump.fun"
    description: str = ""

    def __post_init__(self):
        """
        Valida la wallet después de la inicialización.
        Se ejecuta automáticamente después de crear la instancia.
        """
        self._validate_wallet()

    def _validate_wallet(self):
        """
        Valida que los datos de la wallet sean correctos.
        
        Raises:
            WalletValidationException: Si algún campo no es válido
        """
        # Validar que los campos requeridos no estén vacíos
        if not self.api_key or not self.api_key.strip():
            raise WalletValidationException(
                "API key no puede estar vacía",
                field="api_key",
                value=self.api_key
            )

        if not self.wallet_public_key or not self.wallet_public_key.strip():
            raise WalletValidationException(
                "Wallet public key no puede estar vacía",
                field="wallet_public_key",
                value=self.wallet_public_key
            )

        if not self.private_key or not self.private_key.strip():
            raise WalletValidationException(
                "Private key no puede estar vacía",
                field="private_key",
                value=self.private_key[:20] + "..." if self.private_key else None
            )

        if not self.created_at or not self.created_at.strip():
            raise WalletValidationException(
                "Created at no puede estar vacío",
                field="created_at",
                value=self.created_at
            )

        # Validar formato de private key (debe ser base58 válido)
        try:
            keypair = Keypair.from_base58_string(self.private_key)
            generated_public_key = str(keypair.pubkey())
            
            # Verificar que la public key generada coincida con la almacenada
            if generated_public_key != self.wallet_public_key:
                print(f"⚠️ ADVERTENCIA: Public key generada ({generated_public_key}) no coincide con la almacenada ({self.wallet_public_key})")
                # Actualizar la public key con la generada (más confiable)
                self.wallet_public_key = generated_public_key
                print(f"✅ Public key actualizada a: {generated_public_key}")
                
        except Exception as e:
            raise WalletKeypairException(
                f"Private key inválida: {e}",
                private_key_short=self.private_key
            )

        # Validar formato de API key (debe tener al menos 20 caracteres)
        if len(self.api_key) < 20:
            print(f"⚠️ ADVERTENCIA: API key parece muy corta ({len(self.api_key)} caracteres)")

        # Validar formato de created_at (debe ser ISO format)
        try:
            datetime.fromisoformat(self.created_at.replace('Z', '+00:00'))
        except ValueError:
            print(f"⚠️ ADVERTENCIA: Formato de fecha inválido: {self.created_at}")
            # Actualizar con fecha actual si es inválida
            self.created_at = datetime.now().isoformat()
            print(f"✅ Fecha actualizada a: {self.created_at}")

        print(f"✅ Wallet validada correctamente: {self.wallet_public_key[:8]}...")

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WalletData':
        """Crea instancia desde diccionario"""
        return cls(**data)

    @classmethod
    def create_without_validation(cls, **kwargs) -> 'WalletData':
        """
        Crea una instancia de WalletData sin validación automática.
        Útil para casos donde se quiere crear la wallet sin validar inmediatamente.
        
        Args:
            **kwargs: Argumentos para crear la wallet
            
        Returns:
            Instancia de WalletData sin validación
        """
        # Crear la instancia sin llamar __post_init__
        instance = cls.__new__(cls)
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    def validate_now(self) -> bool:
        """
        Valida la wallet manualmente.
        
        Returns:
            True si es válida, False si no
        """
        try:
            self._validate_wallet()
            return True
        except Exception as e:
            print(f"❌ Error validando wallet: {e}")
            return False

    def get_short_info(self) -> Dict[str, str]:
        """Obtiene información resumida de la wallet"""
        return {
            'api_key_short': f"{self.api_key[:20]}...",
            'public_key': self.wallet_public_key,
            'private_key_short': f"{self.private_key[:20]}...",
            'created_at': self.created_at,
            'platform': self.platform
        }

    def get_keypair(self) -> Keypair:
        """
        Obtiene el Keypair de Solana a partir de la private key.
        
        Returns:
            Keypair de Solana
            
        Raises:
            WalletKeypairException: Si la private key no es válida
        """
        try:
            return Keypair.from_base58_string(self.private_key)
        except Exception as e:
            raise WalletKeypairException(
                f"Error creando Keypair desde private key: {e}",
                private_key_short=self.private_key
            )


class PumpFunWalletCreator:
    """
    Clase responsable de crear wallets Lightning via API de PumpFun
    """

    def __init__(self, api_client: Optional[PumpFunHttpApiClient] = None):
        """
        Inicializa el creador de wallets.
        
        Args:
            api_client: Una instancia existente de PumpFunApiClient
        """
        self.client = api_client or PumpFunHttpApiClient()

    async def __aenter__(self):
        """Context manager entry"""
        print("🔌 Iniciando sesión de creación de wallets...")
        if not self.client.is_running:
            raise Exception("HTTP no está habilitado en el cliente")

        await self.client.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        print("🔌 Cerrando sesión de creación de wallets...")
        if self.client.is_running:
            await self.client.disconnect()
        print("✅ Sesión de creación de wallets cerrada correctamente")

    async def create_wallet(self, description: str = "") -> WalletData:
        """
        Crea una nueva wallet Lightning y API key vinculada.

        Args:
            description: Descripción opcional para la wallet

        Returns:
            Objeto WalletData con los datos de la wallet
        """
        print("🆕 Creando nueva wallet Lightning...")

        try:
            response = await self.client.http_get(endpoint="create-wallet")
            print("✅ Wallet creada exitosamente")

            # Validar respuesta esperada
            if not response or not isinstance(response, dict):
                raise WalletCreationException("Respuesta inválida del servidor", api_response=response)

            required_fields = ['apiKey', 'walletPublicKey', 'privateKey']
            missing_fields = [field for field in required_fields if field not in response]

            if missing_fields:
                raise WalletCreationException(f"Campos faltantes en la respuesta: {missing_fields}", api_response=response)

            # Crear objeto WalletData (la validación se ejecuta automáticamente)
            try:
                wallet_data = WalletData(
                    api_key=response['apiKey'],
                    wallet_public_key=response['walletPublicKey'],
                    private_key=response['privateKey'],
                    created_at=datetime.now().isoformat(),
                    description=description
                )
            except WalletValidationException as e:
                print(f"❌ Error de validación en wallet creada: {e}")
                raise WalletCreationException(f"Wallet creada pero no válida: {e}", api_response=response)
            except WalletKeypairException as e:
                print(f"❌ Error de Keypair en wallet creada: {e}")
                raise WalletCreationException(f"Wallet creada pero Keypair inválido: {e}", api_response=response)
            except Exception as e:
                print(f"❌ Error inesperado creando WalletData: {e}")
                raise WalletCreationException(f"Error procesando datos de wallet: {e}", api_response=response)

            # Mostrar información resumida
            short_info = wallet_data.get_short_info()
            print(f"   🔑 API Key: {short_info['api_key_short']}")
            print(f"   📍 Wallet: {short_info['public_key']}")
            print(f"   🔐 Private Key: {short_info['private_key_short']}")

            return wallet_data

        except Exception as e:
            print(f"❌ Error creando wallet: {e}")
            raise ApiClientException(f"Error creando wallet: {e}")

    async def create_multiple_wallets(self, count: int, description_prefix: str = "Wallet") -> List[WalletData]:
        """
        Crea múltiples wallets de una vez.

        Args:
            count: Número de wallets a crear
            description_prefix: Prefijo para las descripciones

        Returns:
            Lista de objetos WalletData
        """
        print(f"🆕 Creando {count} wallets Lightning...")

        wallets = []
        for i in range(count):
            description = f"{description_prefix} {i+1}"
            try:
                wallet = await self.create_wallet(description)
                wallets.append(wallet)
                print(f"   ✅ Wallet {i+1}/{count} creada")
            except Exception as e:
                print(f"   ❌ Error creando wallet {i+1}: {e}")

        print(f"✅ {len(wallets)}/{count} wallets creadas exitosamente")
        return wallets

    async def get_status(self) -> Dict[str, Any]:
        """Obtiene el estado del creador de wallets"""
        return {
            'client_status': self.client.get_status() if self.client else None
        }


class PumpFunWalletStorage:
    """
    Clase responsable de operaciones I/O y gestión de datos de wallets
    """

    def __init__(self, storage_path: str = "wallets", filename: str = "wallets.json"):
        """
        Inicializa el almacenamiento de wallets.
        
        Args:
            storage_path: Ruta para almacenar datos de wallets (opcional)
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)

        # Archivo para almacenar wallets
        self.wallets_file = self.storage_path / filename
        self._wallets_cache: List[WalletData] = []

    async def initialize(self):
        """Inicializa el almacenamiento cargando las wallets"""
        await self._load_wallets()

    async def __aenter__(self):
        """Context manager entry"""
        print("📂 Iniciando sesión de almacenamiento de wallets...")
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        print("📂 Cerrando sesión de almacenamiento de wallets...")
        print("✅ Sesión de almacenamiento de wallets cerrada correctamente")

    # ============================================================================
    # OPERACIONES I/O BÁSICAS
    # ============================================================================

    async def _load_wallets(self):
        """Carga wallets desde archivo"""
        try:
            if self.wallets_file.exists():
                async with aiofiles.open(self.wallets_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    data = json.loads(content)
                    self._wallets_cache = [WalletData.from_dict(wallet) for wallet in data]
                print(f"📂 {len(self._wallets_cache)} wallets cargadas desde {self.wallets_file}")
            else:
                self._wallets_cache = []
                print("📂 No se encontraron wallets guardadas")
        except Exception as e:
            print(f"⚠️ Error cargando wallets: {e}")
            raise WalletStorageException(
                f"Error cargando wallets desde archivo: {e}",
                file_path=str(self.wallets_file),
                operation="load"
            )

    async def save_wallet(self, wallet_data: WalletData):
        """Guarda una wallet en el archivo"""
        try:
            # Añadir a cache
            self._wallets_cache.append(wallet_data)

            # Guardar en archivo de forma asíncrona
            async with aiofiles.open(self.wallets_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps([w.to_dict() for w in self._wallets_cache], indent=2, ensure_ascii=False))

            print(f"💾 Wallet guardada en {self.wallets_file}")

        except Exception as e:
            print(f"⚠️ Error guardando wallet: {e}")
            raise WalletStorageException(
                f"Error guardando wallet: {e}",
                file_path=str(self.wallets_file),
                operation="save"
            )

    async def save_multiple_wallets(self, wallets: List[WalletData]):
        """Guarda múltiples wallets de una vez"""
        try:
            # Añadir a cache
            self._wallets_cache.extend(wallets)

            # Guardar en archivo
            async with aiofiles.open(self.wallets_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps([w.to_dict() for w in self._wallets_cache], indent=2, ensure_ascii=False))

            print(f"💾 {len(wallets)} wallets guardadas en {self.wallets_file}")

        except Exception as e:
            print(f"⚠️ Error guardando wallets: {e}")
            raise WalletStorageException(
                f"Error guardando múltiples wallets: {e}",
                file_path=str(self.wallets_file),
                operation="save_multiple"
            )

    # ============================================================================
    # MÉTODOS PARA OBTENER DATOS DE WALLETS
    # ============================================================================

    async def get_wallets(self) -> List[WalletData]:
        """Obtiene todas las wallets guardadas"""
        return self._wallets_cache.copy()

    async def get_wallet_by_index(self, index: int) -> Optional[WalletData]:
        """Obtiene una wallet por índice"""
        if 0 <= index < len(self._wallets_cache):
            return self._wallets_cache[index]
        return None

    async def get_wallet_by_public_key(self, public_key: str) -> Optional[WalletData]:
        """Obtiene una wallet por public key"""
        for wallet in self._wallets_cache:
            if wallet.wallet_public_key == public_key:
                return wallet
        return None

    async def get_wallet_by_api_key(self, api_key: str) -> Optional[WalletData]:
        """Obtiene una wallet por API key"""
        for wallet in self._wallets_cache:
            if wallet.api_key == api_key:
                return wallet
        return None

    async def list_wallets(self) -> List[Dict[str, str]]:
        """Lista todas las wallets con información resumida"""
        return [wallet.get_short_info() for wallet in self._wallets_cache]

    async def get_wallet_count(self) -> int:
        """Obtiene el número total de wallets"""
        return len(self._wallets_cache)

    async def search_wallets_by_description(self, search_term: str) -> List[WalletData]:
        """Busca wallets por descripción"""
        search_term = search_term.lower()
        return [
            wallet for wallet in self._wallets_cache 
            if search_term in wallet.description.lower()
        ]

    # ============================================================================
    # OPERACIONES DE EXPORTACIÓN/IMPORTACIÓN
    # ============================================================================

    async def export_wallet(self, wallet_data: WalletData, export_path: Optional[str] = None) -> str:
        """
        Exporta una wallet a un archivo JSON separado
        
        Args:
            wallet_data: Datos de la wallet a exportar
            export_path: Ruta del archivo de exportación (opcional)
            
        Returns:
            Ruta del archivo exportado
        """
        if not export_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = self.storage_path / f"wallet_{wallet_data.wallet_public_key[:8]}_{timestamp}.json"

        try:
            async with aiofiles.open(export_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(wallet_data.to_dict(), indent=2, ensure_ascii=False))

            print(f"📤 Wallet exportada a {export_path}")
            return str(export_path)

        except Exception as e:
            print(f"❌ Error exportando wallet: {e}")
            raise WalletExportException(
                f"Error exportando wallet: {e}",
                file_path=str(export_path),
                format_type="json"
            )

    async def import_wallet(self, import_path: str) -> WalletData:
        """
        Importa una wallet desde un archivo JSON
        
        Args:
            import_path: Ruta del archivo a importar
            
        Returns:
            Objeto WalletData importado
        """
        try:
            async with aiofiles.open(import_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)

            # Crear WalletData (la validación se ejecuta automáticamente)
            try:
                wallet_data = WalletData.from_dict(data)
            except WalletValidationException as e:
                print(f"❌ Error de validación en wallet importada: {e}")
                raise WalletImportException(f"Wallet importada pero no válida: {e}", file_path=import_path, format_type="json")
            except WalletKeypairException as e:
                print(f"❌ Error de Keypair en wallet importada: {e}")
                raise WalletImportException(f"Wallet importada pero Keypair inválido: {e}", file_path=import_path, format_type="json")
            except Exception as e:
                print(f"❌ Error inesperado creando WalletData: {e}")
                raise WalletImportException(f"Error procesando datos de wallet importada: {e}", file_path=import_path, format_type="json")

            # Verificar si ya existe
            existing = await self.get_wallet_by_public_key(wallet_data.wallet_public_key)
            if existing:
                print(f"⚠️ Wallet ya existe: {wallet_data.wallet_public_key}")
                raise WalletDuplicateException(
                    f"Wallet ya existe: {wallet_data.wallet_public_key}",
                    existing_wallet_public_key=wallet_data.wallet_public_key
                )

            # Añadir a cache y guardar
            self._wallets_cache.append(wallet_data)
            async with aiofiles.open(self.wallets_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps([w.to_dict() for w in self._wallets_cache], indent=2, ensure_ascii=False))

            print(f"📥 Wallet importada desde {import_path}")
            return wallet_data

        except Exception as e:
            print(f"❌ Error importando wallet: {e}")
            raise

    # ============================================================================
    # CARGA DE WALLETS DESDE ARCHIVOS
    # ============================================================================

    async def load_keypair_from_file(self, wallet_file: str) -> Keypair:
        """
        Carga un Keypair desde un archivo, soportando múltiples formatos.
        
        Args:
            wallet_file: Ruta al archivo de wallet
            
        Returns:
            Keypair de Solana
            
        Raises:
            Exception: Si no se puede cargar la wallet
        """
        try:
            async with aiofiles.open(wallet_file, 'r', encoding='utf-8') as f:
                content = await f.read()

            # Intentar formato estándar de Solana (array de bytes JSON)
            try:
                secret_key_bytes = bytes(json.loads(content))
                if len(secret_key_bytes) == 64:
                    return Keypair.from_secret_key(secret_key_bytes)
            except (json.JSONDecodeError, TypeError, ValueError):
                # Si falla, no es el formato de array de bytes, continuar al siguiente
                pass

            # Intentar formato de exportación de pump.fun (objeto JSON con 'private_key' b58)
            try:
                wallet_data = json.loads(content)
                if 'private_key' in wallet_data:
                    return Keypair.from_base58_string(wallet_data['private_key'])
                # Intentar también 'privateKey' (formato API)
                elif 'privateKey' in wallet_data:
                    return Keypair.from_base58_string(wallet_data['privateKey'])
            except (json.JSONDecodeError, KeyError):
                pass

            # Si nada de lo anterior funciona, suponer que el archivo contiene solo la private key en base58
            return Keypair.from_base58_string(content.strip())

        except Exception as e:
            print(f"❌ No se pudo cargar la wallet desde '{wallet_file}'. Formato no reconocido.")
            raise WalletImportException(
                f"No se pudo cargar la wallet desde '{wallet_file}'. Formato no reconocido: {e}",
                file_path=wallet_file,
                format_type="unknown"
            )

    @staticmethod
    async def load_wallet_data_from_file(wallet_file: str) -> Optional[WalletData]:
        """
        Carga datos de wallet desde un archivo
        
        Args:
            wallet_file: Ruta al archivo de wallet
            
        Returns:
            WalletData o None si no se pudo cargar
            
        Raises:
            WalletImportException: Si hay error al importar
        """
        try:
            # Verificar que el archivo existe
            if not Path(wallet_file).exists():
                raise WalletImportException(
                    f"Archivo de wallet no encontrado: {wallet_file}",
                    file_path=wallet_file
                )

            # Leer archivo
            async with aiofiles.open(wallet_file, 'r') as f:
                data = json.loads(await f.read())

            # Intentar diferentes formatos

            # Formato 1: Campos estándar (api_key, public_key, private_key)
            if all(key in data for key in ['api_key', 'public_key', 'private_key']):
                return WalletData(
                    api_key=data['api_key'],
                    wallet_public_key=data['public_key'],  # Mapear public_key a wallet_public_key
                    private_key=data['private_key'],
                    created_at=data.get('created_at', datetime.now().isoformat()),
                    platform=data.get('platform', 'pump.fun'),
                    description=data.get('description', '')
                )

            # Formato 2: Campos con wallet_public_key
            if all(key in data for key in ['api_key', 'wallet_public_key', 'private_key']):
                return WalletData(
                    api_key=data['api_key'],
                    wallet_public_key=data['wallet_public_key'],
                    private_key=data['private_key'],
                    created_at=data.get('created_at', datetime.now().isoformat()),
                    platform=data.get('platform', 'pump.fun'),
                    description=data.get('description', '')
                )

            # Formato 3: Formato de API de pump.fun
            if all(key in data for key in ['apiKey', 'walletPublicKey', 'privateKey']):
                return WalletData(
                    api_key=data['apiKey'],
                    wallet_public_key=data['walletPublicKey'],
                    private_key=data['privateKey'],
                    created_at=data.get('created_at', datetime.now().isoformat()),
                    platform=data.get('platform', 'pump.fun'),
                    description=data.get('description', '')
                )

            # Si no coincide con ningún formato conocido
            raise WalletImportException(
                "Formato de wallet no reconocido. Se requiere: api_key, (public_key o wallet_public_key), private_key",
                file_path=wallet_file
            )

        except json.JSONDecodeError as e:
            raise WalletImportException(
                f"Error decodificando JSON: {e}",
                file_path=wallet_file
            )
        except Exception as e:
            if isinstance(e, WalletImportException):
                raise
            raise WalletImportException(
                f"Error cargando wallet: {e}",
                file_path=wallet_file
            )

    async def save_wallet_to_file(self, wallet_data: WalletData, file_path: str, format_type: str = "full") -> bool:
        """
        Guarda una wallet en un archivo en el formato especificado.
        
        Args:
            wallet_data: Datos de la wallet
            file_path: Ruta donde guardar
            format_type: Tipo de formato ("pumpfun", "solana", "full")
            
        Returns:
            True si se guardó correctamente
        """
        try:
            if format_type == "pumpfun":
                # Formato API de pump.fun
                data = {
                    'apiKey': wallet_data.api_key,
                    'walletPublicKey': wallet_data.wallet_public_key,
                    'privateKey': wallet_data.private_key
                }
            elif format_type == "solana":
                # Formato estándar de Solana (solo private key como array de bytes)
                keypair = Keypair.from_base58_string(wallet_data.private_key)
                data = list(keypair.secret_key)
            elif format_type == "full":
                # Formato completo con todos los datos
                data = wallet_data.to_dict()
            else:
                raise ValueError(f"Formato no soportado: {format_type}")

            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                if format_type == "solana":
                    await f.write(json.dumps(data))
                else:
                    await f.write(json.dumps(data, indent=2, ensure_ascii=False))

            print(f"💾 Wallet guardada en {file_path} (formato: {format_type})")
            return True

        except Exception as e:
            print(f"❌ Error guardando wallet: {e}")
            return False

    async def create_wallet_file_for_copy_trading(self, wallet_data: WalletData, 
                                                file_path: str = "wallet.json") -> str:
        """
        Crea un archivo de wallet específicamente para usar con copy trading.
        
        Args:
            wallet_data: Datos de la wallet
            file_path: Ruta del archivo a crear
            
        Returns:
            Ruta del archivo creado
        """
        # Crear formato compatible con copy trading (formato pump.fun)
        success = await self.save_wallet_to_file(wallet_data, file_path)

        if success:
            print(f"✅ Archivo de wallet para copy trading creado: {file_path}")
            return file_path
        else:
            raise Exception(f"No se pudo crear el archivo de wallet: {file_path}")

    async def get_keypair_from_wallet_data(self, wallet_data: WalletData) -> Keypair:
        """
        Obtiene un Keypair de Solana desde WalletData.
        
        Args:
            wallet_data: Datos de la wallet
            
        Returns:
            Keypair de Solana
        """
        return wallet_data.get_keypair()

    async def get_keypairs_from_wallets(self, wallets: List[WalletData]) -> List[Keypair]:
        """
        Obtiene Keypairs de múltiples wallets.
        
        Args:
            wallets: Lista de WalletData
            
        Returns:
            Lista de Keypairs de Solana
        """
        keypairs = []
        for wallet in wallets:
            try:
                keypair = wallet.get_keypair()
                keypairs.append(keypair)
            except Exception as e:
                print(f"⚠️ Error obteniendo Keypair para wallet {wallet.wallet_public_key}: {e}")

        return keypairs

    async def get_all_keypairs(self) -> List[Keypair]:
        """
        Obtiene Keypairs de todas las wallets almacenadas.
        
        Returns:
            Lista de Keypairs de Solana
        """
        return await self.get_keypairs_from_wallets(self._wallets_cache)

    async def validate_all_wallets(self) -> Dict[str, bool]:
        """
        Valida todas las wallets almacenadas.
        
        Returns:
            Diccionario con public_key como clave y True/False como valor
        """
        validation_results = {}
        for wallet in self._wallets_cache:
            validation_results[wallet.wallet_public_key] = wallet.validate_keypair()

        return validation_results

    # ============================================================================
    # UTILIDADES PARA COPY TRADING
    # ============================================================================

    async def setup_for_copy_trading(self, wallet_data: WalletData, 
                                    description: str = "Copy Trading Wallet") -> tuple[WalletData, str]:
        """
        Configura una wallet completa para copy trading.
        
        Args:
            wallet_data: Datos de la wallet a configurar
            description: Descripción de la wallet
            
        Returns:
            Tuple de (WalletData, ruta_archivo_wallet)
        """
        # Actualizar descripción si es necesario
        if wallet_data.description != description:
            wallet_data.description = description

        # Crear archivo compatible con copy trading
        wallet_file = await self.create_wallet_file_for_copy_trading(
            wallet_data, 
            f"copy_trading_wallet_{wallet_data.wallet_public_key[:8]}.json"
        )

        print(f"🎯 Wallet configurada para copy trading:")
        print(f"   📍 Public Key: {wallet_data.wallet_public_key}")
        print(f"   📄 Archivo: {wallet_file}")

        return wallet_data, wallet_file

    async def validate_wallet_for_copy_trading(self, wallet_file: str) -> bool:
        """
        Valida que un archivo de wallet sea compatible con copy trading.
        
        Args:
            wallet_file: Ruta al archivo de wallet
            
        Returns:
            True si es válido
        """
        try:
            # Intentar cargar el keypair
            keypair = await self.load_keypair_from_file(wallet_file)

            # Verificar que el keypair sea válido
            if keypair and keypair.pubkey():
                print(f"✅ Wallet válida para copy trading: {keypair.pubkey()}")
                return True
            else:
                print("❌ Wallet inválida: no se pudo obtener public key")
                return False

        except Exception as e:
            print(f"❌ Error validando wallet: {e}")
            return False

    async def get_wallet_info_for_copy_trading(self, wallet_file: str) -> Dict[str, Any]:
        """
        Obtiene información de una wallet para copy trading.
        
        Args:
            wallet_file: Ruta al archivo de wallet
            
        Returns:
            Diccionario con información de la wallet
        """
        try:
            keypair = await self.load_keypair_from_file(wallet_file)
            wallet_data = await self.load_wallet_data_from_file(wallet_file)

            info = {
                'public_key': str(keypair.pubkey()),
                'file_path': wallet_file,
                'valid': True
            }

            if wallet_data:
                info.update({
                    'api_key': wallet_data.api_key[:20] + "..." if wallet_data.api_key else None,
                    'created_at': wallet_data.created_at,
                    'description': wallet_data.description
                })

            return info

        except Exception as e:
            return {
                'public_key': None,
                'file_path': wallet_file,
                'valid': False,
                'error': str(e)
            }

    # ============================================================================
    # UTILIDADES
    # ============================================================================

    async def get_status(self) -> Dict[str, Any]:
        """Obtiene el estado del almacenamiento de wallets"""
        return {
            'total_wallets': len(self._wallets_cache),
            'storage_path': str(self.storage_path),
            'wallets_file': str(self.wallets_file)
        }

    async def backup_wallets(self, backup_path: Optional[str] = None) -> str:
        """
        Crea un backup de todas las wallets
        
        Args:
            backup_path: Ruta del backup (opcional)
            
        Returns:
            Ruta del archivo de backup
        """
        if not backup_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.storage_path / f"wallets_backup_{timestamp}.json"

        try:
            async with aiofiles.open(backup_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps([w.to_dict() for w in self._wallets_cache], indent=2, ensure_ascii=False))

            print(f"💾 Backup creado en {backup_path}")
            return str(backup_path)

        except Exception as e:
            print(f"❌ Error creando backup: {e}")
            raise WalletBackupException(
                f"Error creando backup: {e}",
                backup_path=str(backup_path),
                wallet_count=len(self._wallets_cache)
            )

    async def clear_wallets(self):
        """Limpia todas las wallets (¡CUIDADO!)"""
        print("⚠️ ADVERTENCIA: Esto eliminará todas las wallets guardadas")
        response = input("¿Estás seguro? (escribe 'SI' para confirmar): ")

        if response.upper() == 'SI':
            self._wallets_cache = []
            if self.wallets_file.exists():
                self.wallets_file.unlink()
            print("🗑️ Todas las wallets han sido eliminadas")
        else:
            print("❌ Operación cancelada")


# ============================================================================
# CLASE COMPATIBILIDAD (Mantiene la interfaz original)
# ============================================================================

class PumpFunWalletManager:
    """
    Clase de compatibilidad que combina PumpFunWalletCreator y PumpFunWalletStorage
    Mantiene la interfaz original para no romper código existente
    """

    def __init__(self, api_client: Optional[PumpFunHttpApiClient] = None, storage_path: Optional[str] = None):
        """
        Inicializa el gestor de wallets.
        
        Args:
            api_client: Una instancia existente de PumpFunHttpApiClient
            storage_path: Ruta para almacenar datos de wallets (opcional)
        """
        self.creator = PumpFunWalletCreator(api_client)
        self.storage = PumpFunWalletStorage(storage_path)

    async def initialize(self):
        """Inicializa el gestor cargando las wallets"""
        await self.storage.initialize()

    async def __aenter__(self):
        """Context manager entry"""
        print("🔌 Iniciando sesión de gestión de wallets...")
        await self.storage.initialize()
        if self.creator.client.is_running:
            await self.creator.client.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        print("🔌 Cerrando sesión de gestión de wallets...")
        if self.creator.client.is_running:
            await self.creator.client.disconnect()
        print("✅ Sesión de gestión de wallets cerrada correctamente")

    # Métodos de creación (delegados a creator)
    async def create_wallet(self, description: str = "") -> WalletData:
        """Crea una nueva wallet y la guarda automáticamente"""
        wallet_data = await self.creator.create_wallet(description)
        await self.storage.save_wallet(wallet_data)
        return wallet_data

    async def create_multiple_wallets(self, count: int, description_prefix: str = "Wallet") -> List[WalletData]:
        """Crea múltiples wallets y las guarda automáticamente"""
        wallets = await self.creator.create_multiple_wallets(count, description_prefix)
        await self.storage.save_multiple_wallets(wallets)
        return wallets

    # Métodos de almacenamiento (delegados a storage)
    async def _load_wallets(self):
        """Carga wallets desde archivo"""
        await self.storage._load_wallets()

    async def _save_wallet(self, wallet_data: WalletData):
        """Guarda una wallet en el archivo"""
        await self.storage.save_wallet(wallet_data)

    async def get_wallets(self) -> List[WalletData]:
        """Obtiene todas las wallets guardadas"""
        return await self.storage.get_wallets()

    async def get_wallet_by_index(self, index: int) -> Optional[WalletData]:
        """Obtiene una wallet por índice"""
        return await self.storage.get_wallet_by_index(index)

    async def get_wallet_by_public_key(self, public_key: str) -> Optional[WalletData]:
        """Obtiene una wallet por public key"""
        return await self.storage.get_wallet_by_public_key(public_key)

    async def get_wallet_by_api_key(self, api_key: str) -> Optional[WalletData]:
        """Obtiene una wallet por API key"""
        return await self.storage.get_wallet_by_api_key(api_key)

    async def list_wallets(self) -> List[Dict[str, str]]:
        """Lista todas las wallets con información resumida"""
        return await self.storage.list_wallets()

    async def export_wallet(self, wallet_data: WalletData, export_path: Optional[str] = None) -> str:
        """Exporta una wallet a un archivo JSON separado"""
        return await self.storage.export_wallet(wallet_data, export_path)

    async def import_wallet(self, import_path: str) -> WalletData:
        """Importa una wallet desde un archivo JSON"""
        return await self.storage.import_wallet(import_path)

    async def load_keypair_from_file(self, wallet_file: str) -> Keypair:
        """Carga un Keypair desde un archivo"""
        return await self.storage.load_keypair_from_file(wallet_file)

    async def load_wallet_data_from_file(self, wallet_file: str) -> Optional[WalletData]:
        """Carga datos completos de wallet desde un archivo"""
        return await self.storage.load_wallet_data_from_file(wallet_file)

    async def save_wallet_to_file(self, wallet_data: WalletData, file_path: str, format_type: str = "full") -> bool:
        """Guarda una wallet en un archivo en el formato especificado"""
        return await self.storage.save_wallet_to_file(wallet_data, file_path, format_type)

    async def create_wallet_file_for_copy_trading(self, wallet_data: WalletData, file_path: str = "wallet.json") -> str:
        """Crea un archivo de wallet específicamente para usar con copy trading"""
        return await self.storage.create_wallet_file_for_copy_trading(wallet_data, file_path)

    async def get_keypair_from_wallet_data(self, wallet_data: WalletData) -> Keypair:
        """Obtiene un Keypair de Solana desde WalletData"""
        return await self.storage.get_keypair_from_wallet_data(wallet_data)

    async def get_keypairs_from_wallets(self, wallets: List[WalletData]) -> List[Keypair]:
        """Obtiene Keypairs de múltiples wallets"""
        return await self.storage.get_keypairs_from_wallets(wallets)

    async def get_all_keypairs(self) -> List[Keypair]:
        """Obtiene Keypairs de todas las wallets almacenadas"""
        return await self.storage.get_all_keypairs()

    async def validate_all_wallets(self) -> Dict[str, bool]:
        """Valida todas las wallets almacenadas"""
        return await self.storage.validate_all_wallets()

    async def setup_for_copy_trading(self, description: str = "Copy Trading Wallet") -> tuple[WalletData, str]:
        """Configura una wallet completa para copy trading"""
        # Crear nueva wallet
        wallet_data = await self.create_wallet(description)
        # Configurar para copy trading
        return await self.storage.setup_for_copy_trading(wallet_data, description)

    async def validate_wallet_for_copy_trading(self, wallet_file: str) -> bool:
        """Valida que un archivo de wallet sea compatible con copy trading"""
        return await self.storage.validate_wallet_for_copy_trading(wallet_file)

    async def get_wallet_info_for_copy_trading(self, wallet_file: str) -> Dict[str, Any]:
        """Obtiene información de una wallet para copy trading"""
        return await self.storage.get_wallet_info_for_copy_trading(wallet_file)

    async def get_status(self) -> Dict[str, Any]:
        """Obtiene el estado del gestor de wallets"""
        creator_status = await self.creator.get_status()
        storage_status = await self.storage.get_status()
        return {**creator_status, **storage_status}

    async def backup_wallets(self, backup_path: Optional[str] = None) -> str:
        """Crea un backup de todas las wallets"""
        return await self.storage.backup_wallets(backup_path)

    async def clear_wallets(self):
        """Limpia todas las wallets (¡CUIDADO!)"""
        await self.storage.clear_wallets()
