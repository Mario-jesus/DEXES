# -*- coding: utf-8 -*-
"""
Ejecutor de transacciones para Copy Trading
"""
from typing import Dict, Any, Optional, Tuple
import asyncio

from pumpfun.transactions import PumpFunTransactions
from pumpfun.wallet_manager import WalletData
from logging_system import AppLogger

from ..config import CopyTradingConfig, TransactionType
from ..position_management.models import PositionTraderTradeData
from ..data_management import TradingDataFetcher


class TransactionExecutor:
    """Ejecutor de transacciones para el sistema de copy trading"""

    def __init__(
        self,
        config: CopyTradingConfig,
        transactions_manager: PumpFunTransactions,
        wallet_data: WalletData,
        trading_data_fetcher: TradingDataFetcher
    ):
        """
        Inicializa el ejecutor de transacciones
        
        Args:
            config: Configuración del sistema
            transactions_manager: Manager de transacciones de PumpFun
            wallet_data: Datos de la wallet
            trading_data_fetcher: Fetcher de datos de trading
        """
        self.config = config
        self.transactions_manager = transactions_manager
        self.wallet_data = wallet_data
        self.trading_data_fetcher = trading_data_fetcher

        self._logger = AppLogger(self.__class__.__name__)
        self._logger.debug("TransactionExecutor inicializado")

    async def execute_trade(self, trade_data: PositionTraderTradeData) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Ejecuta un trade según el tipo de transacción configurado
        
        Args:
            trade_data: Datos del trade a ejecutar
            
        Returns:
            Tuple con (success, signature, entry_price, error_message)
        """
        try:
            self._logger.info(f"Ejecutando trade: {trade_data.side} {trade_data.token_address[:8]}... por {trade_data.copy_amount_sol} SOL")

            # Iniciar tarea para obtener información del token en paralelo
            token_trading_info_task = asyncio.create_task(
                self.trading_data_fetcher.get_token_trading_info(trade_data.token_address)
            )

            # Ejecutar trade según el tipo configurado
            signature = await self._execute_transaction_by_type(trade_data)

            if signature:
                self._logger.info(f"Trade ejecutado exitosamente ({self.config.transaction_type.value}): {signature}")

                # Obtener precio de entrada
                entry_price = await self._get_entry_price(token_trading_info_task, trade_data.token_address)

                return True, signature, entry_price, None
            else:
                error_msg = f"Error ejecutando trade ({self.config.transaction_type.value}): No se obtuvo signature"
                self._logger.error(error_msg)
                return False, None, None, error_msg

        except Exception as e:
            error_msg = f"Error inesperado ejecutando trade ({self.config.transaction_type.value}): {e}"
            self._logger.error(error_msg, exc_info=True)
            return False, None, None, error_msg

    async def _execute_transaction_by_type(self, trade_data: PositionTraderTradeData) -> Optional[str]:
        """
        Ejecuta la transacción según el tipo configurado
        
        Args:
            trade_data: Datos del trade
            
        Returns:
            Signature de la transacción o None si falla
        """
        if self.config.transaction_type == TransactionType.LIGHTNING_TRADE:
            return await self._execute_lightning_trade(trade_data)
        elif self.config.transaction_type == TransactionType.LOCAL_TRADE:
            return await self._execute_local_trade(trade_data)
        else:
            error_msg = f"Tipo de transacción no soportado: {self.config.transaction_type}"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

    async def _execute_lightning_trade(self, trade_data: PositionTraderTradeData) -> Optional[str]:
        """
        Ejecuta un lightning trade
        
        Args:
            trade_data: Datos del trade
            
        Returns:
            Signature de la transacción o None si falla
        """
        if not self.transactions_manager:
            error_msg = "TransactionsManager no inicializado"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        self._logger.debug(f"Ejecutando lightning trade para {trade_data.token_address[:8]}...")

        result = await self.transactions_manager.execute_lightning_trade(
            action=trade_data.side,  # "buy" o "sell"
            mint=trade_data.token_address,
            amount=trade_data.copy_amount_sol,
            denominated_in_sol=True,
            slippage=str(self.config.slippage_tolerance),
            priority_fee=str(self.config.priority_fee_sol),
            pool=trade_data.pool,  # type: ignore
            skip_preflight=True
        )

        signature = result.get('signature')
        self._logger.debug(f"Resultado lightning trade: {result}")

        error = result.get('error')
        if error:
            self._logger.error(f"Error lightning trade: {error}")

        return signature

    async def _execute_local_trade(self, trade_data: PositionTraderTradeData) -> Optional[str]:
        """
        Ejecuta un local trade
        
        Args:
            trade_data: Datos del trade
            
        Returns:
            Signature de la transacción o None si falla
        """
        if not self.transactions_manager:
            error_msg = "TransactionsManager no inicializado"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        if not self.wallet_data:
            error_msg = "WalletData no inicializado"
            self._logger.error(error_msg)
            raise ValueError(error_msg)

        self._logger.debug(f"Ejecutando local trade para {trade_data.token_address[:8]}...")

        signature = await self.transactions_manager.create_and_send_local_trade(
            keypair=self.wallet_data.get_keypair(),
            action=trade_data.side,
            mint=trade_data.token_address,
            amount=trade_data.copy_amount_sol,
            denominated_in_sol=True,
            slippage=str(self.config.slippage_tolerance),
            priority_fee=str(self.config.priority_fee_sol),
            pool=trade_data.pool,  # type: ignore
            rpc_endpoint=self.config.rpc_url
        )

        self._logger.debug(f"Local trade completado, signature: {signature}")

        return signature

    async def _get_entry_price(self, token_trading_info_task: asyncio.Task, token_address: str) -> str:
        """
        Obtiene el precio de entrada del token
        
        Args:
            token_trading_info_task: Tarea asíncrona para obtener info del token
            token_address: Dirección del token
            
        Returns:
            Precio de entrada como string
        """
        try:
            token_trading_info = await token_trading_info_task
            if token_trading_info:
                entry_price = token_trading_info['sol_per_token']
                self._logger.debug(f"Precio de entrada obtenido: {entry_price}")
                return entry_price
            else:
                self._logger.warning(f"No se pudo obtener el token trading info para {token_address}")
                return ""
        except Exception as e:
            self._logger.error(f"Error obteniendo precio de entrada para {token_address}: {e}")
            return ""

    def get_transaction_type_info(self) -> Dict[str, Any]:
        """
        Obtiene información sobre el tipo de transacción configurado
        
        Returns:
            Información del tipo de transacción
        """
        return {
            'transaction_type': self.config.transaction_type.value,
            'slippage_tolerance': str(self.config.slippage_tolerance),
            'priority_fee_sol': str(self.config.priority_fee_sol),
            'rpc_url': self.config.rpc_url
        }
