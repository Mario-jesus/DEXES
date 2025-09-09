# -*- coding: utf-8 -*-
"""
Módulo de Transacciones de PumpFun - Implementa APIs de trading

Este módulo proporciona una clase `PumpFunTransactions` para interactuar con
las APIs de trading de PumpPortal, soportando tanto transacciones "Lightning"
(ejecutadas por el servidor) como "Local" (firmadas por el cliente).
"""

from typing import Optional, Literal, Dict, Any, Type, TYPE_CHECKING
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from logging_system import AppLogger
from .api_client import PumpFunHttpApiClient, ApiClientException

if TYPE_CHECKING:
    from types import TracebackType


# Tipos para validación estática
TradeAction = Literal["buy", "sell"]
PoolType = Literal["pump", "raydium", "pump-amm", "launchlab", "raydium-cpmm", "bonk", "auto"]


class PumpFunTransactions:
    """
    Gestiona las transacciones de compra y venta a través de las APIs de PumpPortal.
    Soporta context manager async para gestión automática de conexiones.
    """

    def __init__(self, api_client: Optional[PumpFunHttpApiClient] = None, api_key: Optional[str] = None):
        """
        Inicializa el gestor de transacciones.

        Args:
            api_client: Una instancia existente de PumpFunHttpApiClient. Si es None, se crea una nueva.
            api_key: La clave API para las transacciones Lightning.
        """
        self.client = api_client or PumpFunHttpApiClient(api_key=api_key)
        self._api_key = api_key
        self._logger = AppLogger(self.__class__.__name__)

    async def __aenter__(self):
        """
        Método de entrada para el context manager asíncrono.
        Conecta el cliente API automáticamente.
        """
        await self.start()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional["TracebackType"]):
        """
        Método de salida para el context manager asíncrono.
        Desconecta el cliente API automáticamente.
        """
        await self.stop()

    async def start(self):
        self._logger.debug("Iniciando sesión de transacciones PumpFun...")
        await self.client.connect()

    async def stop(self):
        self._logger.debug("Cerrando sesión de transacciones PumpFun...")
        await self.client.disconnect()
        self._logger.debug("Sesión de transacciones cerrada correctamente")

    async def execute_lightning_trade(
        self,
        action: TradeAction,
        mint: str,
        amount: str,
        denominated_in_sol: bool,
        slippage: str,
        priority_fee: str,
        pool: PoolType = "auto",
        skip_preflight: bool = True,
        jito_only: bool = False
    ) -> Dict[str, Any]:
        """
        Ejecuta una transacción "Lightning" donde el servidor se encarga de todo.

        Args:
            action: "buy" o "sell".
            mint: La dirección del contrato del token.
            amount: Cantidad de SOL o tokens. Puede ser "100%" para vender todo.
            denominated_in_sol: True si `amount` es en SOL, False si es en tokens.
            slippage: Porcentaje de deslizamiento permitido.
            priority_fee: Tarifa de prioridad en SOL.
            pool: El pool de liquidez a utilizar.
            skip_preflight: Si es True, omite la simulación de la transacción.
            jito_only: Si es True, envía la transacción solo a través de Jito.

        Returns:
            Un diccionario con la firma de la transacción o un mensaje de error.
        """
        if not self._api_key:
            raise ApiClientException("Se requiere una clave API para las transacciones Lightning.")

        payload = {
            "action": action,
            "mint": mint,
            "amount": amount,
            "denominatedInSol": "true" if denominated_in_sol else "false",
            "slippage": slippage,
            "priorityFee": priority_fee,
            "pool": pool,
            "skipPreflight": "true" if skip_preflight else "false",
            "jitoOnly": "true" if jito_only else "false",
        }

        self._logger.debug(f"Ejecutando trade Lightning: {action} {amount} de {mint}")
        response = await self.client.http_post(endpoint="trade", data=payload, use_api_key=True)
        self._logger.debug(f"Respuesta Lightning: {response}")
        return response or {}

    async def create_and_send_local_trade(
        self,
        keypair: Keypair,
        action: TradeAction,
        mint: str,
        amount: str,
        denominated_in_sol: bool,
        slippage: str,
        priority_fee: str,
        pool: PoolType = "auto",
        rpc_endpoint: str = "https://api.mainnet-beta.solana.com/"
    ) -> str:
        """
        Crea una transacción, la firma localmente y la envía a un RPC personalizado.

        Args:
            keypair: El Keypair del usuario para firmar la transacción.
            action: "buy" o "sell".
            mint: La dirección del contrato del token.
            amount: Cantidad de SOL o tokens. Puede ser "100%" para vender todo.
            denominated_in_sol: True si `amount` es en SOL, False si es en tokens.
            slippage: Porcentaje de deslizamiento permitido.
            priority_fee: Tarifa de prioridad en SOL.
            pool: El pool de liquidez a utilizar.
            rpc_endpoint: El endpoint RPC de Solana para enviar la transacción.

        Returns:
            La firma de la transacción como una cadena de texto.
        """
        payload = {
            "publicKey": str(keypair.pubkey()),
            "action": action,
            "mint": mint,
            "amount": amount,
            "denominatedInSol": "true" if denominated_in_sol else "false",
            "slippage": slippage,
            "priorityFee": priority_fee,
            "pool": pool,
        }

        # 1. Obtener la transacción serializada de la API
        self._logger.debug(f"Creando transacción local: {action} {amount} de {mint}")
        tx_bytes = await self.client.http_post_raw(endpoint="trade-local", data=payload)
        if not tx_bytes:
            raise ApiClientException("No se recibieron datos de la transacción de la API.")

        self._logger.debug("Transacción recibida, firmando localmente...")

        # 2. Firmar la transacción localmente
        unsigned_tx = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = VersionedTransaction(unsigned_tx.message, [keypair])

        self._logger.debug(f"Transacción firmada, enviando a {rpc_endpoint}...")

        # 3. Enviar la transacción a la red de Solana
        tx_signature = await self.client.send_signed_transaction(signed_tx, rpc_endpoint)
        self._logger.debug(f"Transacción enviada. Firma: {tx_signature}")

        return tx_signature
