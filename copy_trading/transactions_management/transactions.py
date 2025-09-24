# -*- coding: utf-8 -*-
"""
Ejecutor de transacciones para Copy Trading
"""
from typing import Dict, Any, Optional, Tuple

from pumpfun.transactions import PumpFunTransactions
from pumpfun.wallet_manager import WalletData
from logging_system import AppLogger

from ..config import CopyTradingConfig, TransactionType
from ..position_management.models import PositionTraderTradeData


class TransactionExecutor:
    """Ejecutor de transacciones para el sistema de copy trading"""

    def __init__(
        self,
        config: CopyTradingConfig,
        transactions_manager: PumpFunTransactions,
        wallet_data: WalletData
    ):
        """
        Inicializa el ejecutor de transacciones
        
        Args:
            config: Configuración del sistema
            transactions_manager: Manager de transacciones de PumpFun
            wallet_data: Datos de la wallet
        """
        self.config = config
        self.transactions_manager = transactions_manager
        self.wallet_data = wallet_data

        self._logger = AppLogger(self.__class__.__name__)
        self._logger.debug("TransactionExecutor inicializado")

    async def execute_trade(self, trade_data: PositionTraderTradeData) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Ejecuta un trade según el tipo de transacción configurado
        
        Args:
            trade_data: Datos del trade a ejecutar
            
        Returns:
            Tuple con (success, signature, error_message)
        """
        try:
            self._logger.info(f"Ejecutando trade: {trade_data.side} {trade_data.token_address}... por {trade_data.copy_amount_sol + " SOL" if trade_data.side == 'buy' else trade_data.copy_amount_tokens + " Tokens"}")

            # Ejecutar trade según el tipo configurado
            signature = await self._execute_transaction_by_type(trade_data)

            if signature:
                self._logger.info(f"Trade ejecutado exitosamente ({self.config.transaction_type.value}): {signature}")

                return True, signature, None
            else:
                error_msg = f"Error ejecutando trade ({self.config.transaction_type.value}): No se obtuvo signature"
                self._logger.error(error_msg)
                return False, None, error_msg

        except Exception as e:
            error_msg = f"Error inesperado ejecutando trade ({self.config.transaction_type.value}): {e}"
            self._logger.error(error_msg, exc_info=True)
            return False, None, error_msg

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
            amount=trade_data.copy_amount_sol if trade_data.denominate_in_sol else trade_data.copy_amount_tokens,
            denominated_in_sol=trade_data.denominate_in_sol,
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
            amount=trade_data.copy_amount_sol if trade_data.denominate_in_sol else trade_data.copy_amount_tokens,
            denominated_in_sol=trade_data.denominate_in_sol,
            slippage=str(self.config.slippage_tolerance),
            priority_fee=str(self.config.priority_fee_sol),
            pool=trade_data.pool,  # type: ignore
            rpc_endpoint=self.config.rpc_url
        )

        self._logger.debug(f"Local trade completado, signature: {signature}")

        return signature

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
