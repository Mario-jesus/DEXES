# -*- coding: utf-8 -*-
"""
Factory para crear objetos de posición en el sistema de Copy Trading.
Separa la lógica de creación de objetos de la gestión de colas.
"""
from typing import Optional
from datetime import datetime

from logging_system import AppLogger
from ..models import PositionTraderTradeData, OpenPosition, ClosePosition


class PositionFactory:
    """
    Factory responsable de crear objetos de posición según el tipo de trade.
    Separa la lógica de creación de la gestión de colas.
    """

    def __init__(self):
        self._logger = AppLogger(self.__class__.__name__)
        self._logger.debug("PositionFactory inicializado")

    def create_position_from_trade_data(self, 
                                        position_trade_data: PositionTraderTradeData, 
                                        signature: str, 
                                        entry_price: str) -> Optional[OpenPosition | ClosePosition]:
        """
        Crea una posición (OpenPosition o ClosePosition) basada en los datos del trade.
        
        Args:
            position_trade_data: Datos del trade del trader
            signature: Firma de la transacción ejecutada
            entry_price: Precio de entrada
            
        Returns:
            OpenPosition o ClosePosition según el side del trade, None si hay error
        """
        try:
            self._logger.info(f"Creando posición desde trade data: {signature[:8]}...")
            self._logger.debug(f"Side: {position_trade_data.side}, Amount SOL: {position_trade_data.copy_amount_sol}")

            if position_trade_data.side == "buy":
                position = self.create_open_position(position_trade_data, signature, entry_price)
                self._logger.info(f"OpenPosition creada: {position.id}")
                return position
            elif position_trade_data.side == "sell":
                position = self.create_close_position(position_trade_data, signature, entry_price)
                self._logger.info(f"ClosePosition creada: {position.id}")
                return position
            else:
                self._logger.error(f"Side no válido en trade data: {position_trade_data.side}")
                return None

        except Exception as e:
            self._logger.error(f"Error creando posición desde trade data: {e}", exc_info=True)
            return None

    def create_open_position(self, 
                            position_trade_data: PositionTraderTradeData, 
                            signature: str, 
                            entry_price: str) -> OpenPosition:
        """
        Crea un objeto OpenPosition desde los datos del trade.
        
        Args:
            position_trade_data: Datos del trade del trader
            signature: Firma de la transacción ejecutada
            entry_price: Precio de entrada
            
        Returns:
            OpenPosition creado
        """
        try:
            self._logger.debug(f"Creando OpenPosition para signature: {signature[:8]}...")

            position = OpenPosition(
                amount_sol=position_trade_data.copy_amount_sol,
                amount_tokens=position_trade_data.copy_amount_tokens,
                entry_price=entry_price,
                execution_signature=signature,
                execution_price=position_trade_data.get_sol_per_token_price(),
                created_at=position_trade_data.created_at,
                executed_at=datetime.now(),
                trader_trade_data=position_trade_data.trader_trade_data,
            )

            self._logger.debug(f"OpenPosition creada exitosamente: {position.id}")
            return position

        except Exception as e:
            self._logger.error(f"Error creando OpenPosition: {e}")
            raise

    def create_close_position(self, 
                            position_trade_data: PositionTraderTradeData, 
                            signature: str, 
                            entry_price: str) -> ClosePosition:
        """
        Crea un objeto ClosePosition desde los datos del trade.
        
        Args:
            position_trade_data: Datos del trade del trader
            signature: Firma de la transacción ejecutada
            entry_price: Precio de entrada
            
        Returns:
            ClosePosition creado
        """
        try:
            self._logger.debug(f"Creando ClosePosition para signature: {signature[:8]}...")

            position = ClosePosition(
                amount_sol=position_trade_data.copy_amount_sol,
                amount_tokens=position_trade_data.copy_amount_tokens,
                entry_price=entry_price,
                execution_signature=signature,
                execution_price=position_trade_data.get_sol_per_token_price(),
                created_at=position_trade_data.created_at,
                executed_at=datetime.now(),
                trader_trade_data=position_trade_data.trader_trade_data,
            )

            self._logger.debug(f"ClosePosition creada exitosamente: {position.id}")
            return position

        except Exception as e:
            self._logger.error(f"Error creando ClosePosition: {e}")
            raise
