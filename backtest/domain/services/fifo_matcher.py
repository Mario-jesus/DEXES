# -*- coding: utf-8 -*-
"""
Servicio: Matching FIFO de transacciones.

Implementa la lógica de emparejamiento de compras y ventas usando
estrategia FIFO (First In First Out).
"""
import logging
from collections import defaultdict, deque
from typing import List, DefaultDict
from decimal import Decimal
from datetime import datetime

from ...domain.entities.transactions import SwapTransaction
from ...domain.entities.positions import Position, ClosedTrade

logger = logging.getLogger(__name__)


class FIFOMatcher:
    """
    Servicio de dominio: Matching FIFO de compras y ventas.
    
    Maneja el emparejamiento de transacciones de compra y venta usando
    estrategia FIFO, creando posiciones y trades cerrados.
    """

    def __init__(self):
        """
        Inicializa el matcher FIFO.
        
        Estado interno:
        - open_positions_by_token: Dict que mapea token_address -> deque de Position (cola FIFO)
        - closed_trades: Lista de trades cerrados
        """
        self.open_positions_by_token: DefaultDict[str, deque[Position]] = defaultdict(deque)
        self.closed_trades: List[ClosedTrade] = []

    def process_buy(self, transaction: SwapTransaction) -> None:
        """
        Procesa una transacción de compra, creando una nueva posición.
        
        Args:
            transaction: SwapTransaction de tipo 'buy'
        """
        token_address = transaction.base_token_address

        # Crear posición (los valores originales y remanentes son iguales al inicio)
        position = Position(
            token_address=token_address,
            token_symbol=transaction.base_token_symbol,
            buy_hash=transaction.signature,
            buy_timestamp=transaction.block_timestamp.isoformat(),
            buy_block=transaction.block_number,
            original_sol_invested=transaction.sol_amount,
            original_token_amount=transaction.token_amount,
            remaining_sol_invested=transaction.sol_amount,
            remaining_token_amount=transaction.token_amount,
            exchange_address=transaction.exchange_address,
            exchange_name=transaction.exchange_name
        )

        # Añadir a cola de posiciones abiertas (FIFO)
        self.open_positions_by_token[token_address].append(position)

        logger.debug(f"Posición abierta: {position}")

    def process_sell(self, transaction: SwapTransaction) -> None:
        """
        Procesa una transacción de venta, cerrando posiciones usando FIFO.
        
        Args:
            transaction: SwapTransaction de tipo 'sell'
        """
        token_address = transaction.base_token_address

        # Obtener cola de posiciones abiertas para este token
        open_positions = self.open_positions_by_token[token_address]

        if not open_positions:
            logger.warning(
                f"Venta sin posición abierta para token {transaction.base_token_symbol} "
                f"({token_address[:8]}...)"
            )
            return

        # Procesar venta: distribuir sobre posiciones usando FIFO
        remaining_tokens_to_sell = transaction.token_amount
        sell_timestamp = transaction.block_timestamp
        sell_hash = transaction.signature
        sell_block = transaction.block_number

        # Calcular precio promedio de venta por token
        avg_sell_price_per_token = (
            transaction.sol_amount / transaction.token_amount 
            if transaction.token_amount > 0 
            else Decimal('0')
        )

        logger.debug(
            f"Procesando venta tx={sell_hash[:10]} token={transaction.base_token_symbol} "
            f"tokens_vender={float(transaction.token_amount):.6f} "
            f"open_positions={len(open_positions)} "
            f"avg_sell_price={float(avg_sell_price_per_token):.8f}"
        )

        while remaining_tokens_to_sell > 0 and open_positions:
            position = open_positions[0]

            # Calcular cuántos tokens de esta posición se venden
            if remaining_tokens_to_sell >= position.remaining_token_amount:
                # Vender toda la posición restante
                tokens_sold_from_position = position.remaining_token_amount
                remaining_tokens_to_sell -= tokens_sold_from_position
                open_positions.popleft()  # Eliminar posición de la cola
            else:
                # Vender parcialmente la posición
                tokens_sold_from_position = remaining_tokens_to_sell
                remaining_tokens_to_sell = Decimal('0')
                # Actualizar posición parcial (remanentes)
                position.remaining_token_amount -= tokens_sold_from_position
                position.remaining_sol_invested = (
                    position.original_sol_invested * position.remaining_token_amount
                ) / position.original_token_amount

            # Calcular SOL recuperado proporcional a los tokens vendidos
            sol_recovered_from_position = avg_sell_price_per_token * tokens_sold_from_position

            # Calcular SOL invertido proporcional basado en los valores ORIGINALES de la posición
            sol_invested_from_position = (
                position.original_sol_invested * tokens_sold_from_position
            ) / position.original_token_amount

            # Calcular PnL
            profit_loss = sol_recovered_from_position - sol_invested_from_position
            profit_loss_pct = (
                (profit_loss / sol_invested_from_position * 100) 
                if sol_invested_from_position > 0 
                else Decimal('0')
            )

            # Calcular duración
            buy_timestamp_dt = datetime.fromisoformat(
                position.buy_timestamp.replace('Z', '+00:00')
            )
            duration = self._calculate_duration(buy_timestamp_dt, sell_timestamp)

            # Crear trade cerrado
            closed_trade = ClosedTrade(
                token_address=token_address,
                token_symbol=transaction.base_token_symbol,
                buy_hash=position.buy_hash,
                sell_hash=sell_hash,
                buy_timestamp=position.buy_timestamp,
                sell_timestamp=sell_timestamp.isoformat(),
                buy_block=position.buy_block,
                sell_block=sell_block,
                original_sol_invested=position.original_sol_invested,
                original_token_amount=position.original_token_amount,
                sol_invested=sol_invested_from_position,
                sol_recovered=sol_recovered_from_position,
                token_amount_sold=tokens_sold_from_position,
                profit_loss_sol=profit_loss,
                profit_loss_pct=profit_loss_pct,
                duration_seconds=duration,
                exchange_address=position.exchange_address,
                exchange_name=position.exchange_name
            )

            self.closed_trades.append(closed_trade)
            logger.debug(
                f"Trade cerrado: {closed_trade} vendido={float(tokens_sold_from_position):.6f} "
                f"rem_tokens_por_vender={float(remaining_tokens_to_sell):.6f}"
            )

        if remaining_tokens_to_sell > 0:
            logger.warning(
                f"Venta de {float(remaining_tokens_to_sell):.6f} tokens sin posición abierta "
                f"para {transaction.base_token_symbol}"
            )

    def _calculate_duration(
        self, 
        buy_timestamp: datetime, 
        sell_timestamp: datetime
    ) -> int | None:
        """
        Calcula la duración en segundos entre dos timestamps.
        
        Args:
            buy_timestamp: datetime de compra
            sell_timestamp: datetime de venta
        
        Returns:
            Duración en segundos o None si hay error
        """
        try:
            delta = sell_timestamp - buy_timestamp
            return int(delta.total_seconds())
        except (ValueError, TypeError, AttributeError):
            return None

    def get_closed_trades(self) -> List[ClosedTrade]:
        """
        Obtiene todas las trades cerrados.
        
        Returns:
            Lista de ClosedTrade
        """
        return self.closed_trades.copy()

    def get_open_positions(self) -> List[Position]:
        """
        Obtiene todas las posiciones abiertas.
        
        Returns:
            Lista de Position
        """
        result = []
        for positions_queue in self.open_positions_by_token.values():
            result.extend(list(positions_queue))
        return result

    def get_open_positions_count_by_token(self, token_address: str) -> int:
        """
        Obtiene el número de posiciones abiertas para un token específico.
        
        Esta es una operación O(1) que accede directamente al diccionario.
        Usar este método en lugar de filtrar get_open_positions() es mucho más eficiente.
        
        Args:
            token_address: Dirección del token
            
        Returns:
            Número de posiciones abiertas para el token
        """
        return len(self.open_positions_by_token[token_address])

    def reset(self) -> None:
        """
        Resetea el estado del matcher.
        
        Limpia todas las posiciones abiertas y trades cerrados.
        """
        self.open_positions_by_token.clear()
        self.closed_trades.clear()
        logger.debug("FIFOMatcher reseteado")
