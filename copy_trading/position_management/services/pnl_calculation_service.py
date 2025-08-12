# -*- coding: utf-8 -*-
"""
Servicio especializado para cálculos de P&L (Profit & Loss) de posiciones de trading.
Separa la lógica de cálculos financieros de otros análisis.
"""
from typing import Dict, Any, Tuple, List
from decimal import Decimal, getcontext

from ..models import OpenPosition, ClosePosition, PositionStatus, SubClosePosition

# Configurar precisión de Decimal para operaciones financieras
getcontext().prec = 26


class PnLCalculationService:
    """
    Servicio especializado para cálculos de P&L de posiciones de trading.
    Responsabilidad: Calcular ganancias y pérdidas de diferentes maneras.
    """

    @classmethod
    def _get_close_position_data(cls, close_item: SubClosePosition | ClosePosition) -> ClosePosition:
        """
        Obtiene los datos de ClosePosition de un item del historial.
        
        Args:
            close_item: Item del historial (ClosePosition o SubClosePosition)
            
        Returns:
            ClosePosition con los datos del cierre
        """
        if isinstance(close_item, SubClosePosition):
            return close_item.close_position
        return close_item

    @classmethod
    def _get_cost_basis_or_total_cost(cls, position: OpenPosition, include_transaction_costs: bool = False) -> Decimal:
        """
        Obtiene el costo base de la posición o el costo total de la posición si se incluye los costos de transacción.
        
        Args:
            position: Objeto OpenPosition
            include_transaction_costs: Si incluir costos de transacción
            
        Returns:
            Costo base o costo total como Decimal
        """
        return Decimal(position.total_cost_sol) if include_transaction_costs else Decimal(position.amount_sol)

    @classmethod
    def _calculate_pnl_from_amounts(cls, amount: Decimal, cost_basis: Decimal, sol_price_usd: Decimal) -> Tuple[Decimal, Decimal]:
        """
        Calcula P&L a partir de un monto y costo base.
        
        Args:
            amount: Monto en SOL
            cost_basis: Costo base en SOL
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Tuple de (pnl_sol, pnl_usd)
        """
        pnl_sol = amount - cost_basis
        pnl_usd = pnl_sol * sol_price_usd
        return pnl_sol, pnl_usd

    @classmethod
    def calculate_pnl(cls, position: OpenPosition, current_price: str, sol_price_usd: str) -> Tuple[str, str]:
        """
        Calcula P&L actual basado en el estado de la posición.
        
        Args:
            position: Objeto OpenPosition
            current_price: Precio actual del token
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        if position.status not in [PositionStatus.OPEN, PositionStatus.CLOSED, PositionStatus.PARTIALLY_CLOSED]:
            return "0.0", "0.0"

        if position.status == PositionStatus.OPEN:
            if not position.amount_tokens or Decimal(position.amount_tokens) == 0:
                return "0.0", "0.0"

            current_value = Decimal(position.amount_tokens) * Decimal(current_price)
            cost_basis = cls._get_cost_basis_or_total_cost(position)
            pnl_sol, pnl_usd = cls._calculate_pnl_from_amounts(current_value, cost_basis, Decimal(sol_price_usd))

            return format(pnl_sol, "f"), format(pnl_usd, "f")

        elif position.status in [PositionStatus.CLOSED, PositionStatus.PARTIALLY_CLOSED]:
            # Para posiciones cerradas o parcialmente cerradas, usar el P&L realizado
            return cls.calculate_realized_pnl(position, sol_price_usd)

        return "0.0", "0.0"

    @classmethod
    def calculate_realized_pnl(cls, position: OpenPosition, sol_price_usd: str, include_transaction_costs: bool = False) -> Tuple[str, str]:
        """
        Calcula el P&L realizado basado en los cierres reales.
        Esta es la forma CORRECTA de calcular P&L para posiciones cerradas.
        
        Args:
            position: Objeto OpenPosition
            sol_price_usd: Precio de SOL en USD
            include_transaction_costs: Si incluir costos de transacción en el cálculo
            
        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        if not position.close_history:
            return "0.0", "0.0"

        # Valor de entrada (cuánto valían los tokens cuando se compraron)
        entry_value = Decimal(position.amount_tokens) * Decimal(position.execution_price if position.execution_price else position.entry_price)

        # Valor total de salida (cuánto se recibió por los tokens)
        total_exit_value = Decimal('0')

        for close_item in position.close_history:
            # Obtener datos del cierre
            if isinstance(close_item, SubClosePosition):
                close_amount_tokens = Decimal(close_item.amount_tokens) if close_item.amount_tokens else Decimal('0')
                close_price = Decimal(close_item.close_position.execution_price if close_item.close_position.execution_price else close_item.close_position.entry_price)
            else:
                close_amount_tokens = Decimal(close_item.amount_tokens) if close_item.amount_tokens else Decimal('0')
                close_price = Decimal(close_item.execution_price if close_item.execution_price else close_item.entry_price)

            # Calcular valor de salida para este cierre
            exit_value = close_amount_tokens * close_price
            total_exit_value += exit_value

        # Calcular P&L base (sin costos)
        pnl_sol = total_exit_value - entry_value

        # Si se incluyen costos de transacción, restar fees
        if include_transaction_costs and position.fee_sol:
            pnl_sol -= Decimal(position.fee_sol)

        # Convertir a USD
        pnl_usd = pnl_sol * Decimal(sol_price_usd)

        return format(pnl_sol, "f"), format(pnl_usd, "f")

    @classmethod
    def calculate_realized_pnl_with_costs_breakdown(cls, position: OpenPosition, sol_price_usd: str) -> Tuple[str, str, str, str]:
        """
        Calcula el P&L realizado tanto con costos de transacción como sin ellos.
        
        Args:
            position: Objeto OpenPosition
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Tuple de (pnl_sol_without_costs, pnl_usd_without_costs, pnl_sol_with_costs, pnl_usd_with_costs) como strings
        """
        # Calcular P&L sin costos de transacción
        pnl_sol_without_costs, pnl_usd_without_costs = cls.calculate_realized_pnl(position, sol_price_usd, include_transaction_costs=False)

        # Calcular P&L con costos de transacción
        pnl_sol_with_costs, pnl_usd_with_costs = cls.calculate_realized_pnl(position, sol_price_usd, include_transaction_costs=True)

        return pnl_sol_without_costs, pnl_usd_without_costs, pnl_sol_with_costs, pnl_usd_with_costs

    @classmethod
    def calculate_individual_close_pnl(cls, position: OpenPosition, close_item: SubClosePosition | ClosePosition, sol_price_usd: str, include_transaction_costs: bool = False) -> Tuple[str, str]:
        """
        Calcula el P&L de un cierre individual basado en los datos reales del cierre.
        
        Args:
            position: Objeto OpenPosition
            close_item: Item del historial (SubClosePosition o ClosePosition)
            sol_price_usd: Precio de SOL en USD
            include_transaction_costs: Si incluir costos de transacción en el cálculo
            
        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        # Obtener los datos reales del cierre
        if isinstance(close_item, SubClosePosition):
            # Para SubClosePosition, usar los datos del subcierre
            close_amount_sol = Decimal(close_item.amount_sol) if close_item.amount_sol else Decimal('0')
            close_amount_tokens = Decimal(close_item.amount_tokens) if close_item.amount_tokens else Decimal('0')
        else:
            # Para ClosePosition, usar los datos del cierre
            close_amount_sol = Decimal(close_item.amount_sol) if close_item.amount_sol else Decimal('0')
            close_amount_tokens = Decimal(close_item.amount_tokens) if close_item.amount_tokens else Decimal('0')

        if close_amount_sol == 0:
            return "0.0", "0.0"

        # Calcular el costo proporcional basado en los tokens cerrados
        total_original_tokens = Decimal(position.amount_tokens) if position.amount_tokens else Decimal('0')
        if total_original_tokens == 0:
            return "0.0", "0.0"

        # Calcular la proporción de tokens cerrados
        proportion = close_amount_tokens / total_original_tokens
        total_cost = cls._get_cost_basis_or_total_cost(position, include_transaction_costs)
        proportional_cost = total_cost * proportion

        # Calcular P&L del cierre individual
        pnl_sol, pnl_usd = cls._calculate_pnl_from_amounts(close_amount_sol, proportional_cost, Decimal(sol_price_usd))

        return format(pnl_sol, "f"), format(pnl_usd, "f")

    @classmethod
    def calculate_accumulated_close_pnl(cls, position: OpenPosition, sol_price_usd: str, up_to_close_index: int = -1, include_transaction_costs: bool = False) -> Tuple[str, str]:
        """
        Calcula el P&L acumulado hasta un cierre específico.
        
        Args:
            position: Objeto OpenPosition
            up_to_close_index: Índice del cierre hasta donde calcular (por defecto -1 para el último)
            sol_price_usd: Precio de SOL en USD
            include_transaction_costs: Si incluir costos de transacción en el cálculo
            
        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        if not position.close_history:
            return "0.0", "0.0"

        # Normalizar el índice
        if up_to_close_index < 0:
            up_to_close_index = len(position.close_history) + up_to_close_index

        if up_to_close_index >= len(position.close_history):
            up_to_close_index = len(position.close_history) - 1

        # Calcular P&L acumulado hasta ese cierre
        total_pnl_sol = Decimal('0')

        for i in range(up_to_close_index + 1):
            close_item = position.close_history[i]
            individual_pnl_sol, _ = cls.calculate_individual_close_pnl(position, close_item, sol_price_usd, include_transaction_costs)
            total_pnl_sol += Decimal(individual_pnl_sol)

        total_pnl_usd = total_pnl_sol * Decimal(sol_price_usd)

        return format(total_pnl_sol, "f"), format(total_pnl_usd, "f")

    @classmethod
    def get_close_pnl_breakdown(cls, position: OpenPosition, sol_price_usd: str, include_transaction_costs: bool = False) -> List[Dict[str, Any]]:
        """
        Obtiene el desglose completo del P&L por cada cierre.
        
        Args:
            position: Objeto OpenPosition
            sol_price_usd: Precio de SOL en USD
            include_transaction_costs: Si incluir costos de transacción en el cálculo
            
        Returns:
            Lista de diccionarios con desglose de P&L por cierre
        """
        breakdown = []

        for i, close_item in enumerate(position.close_history):
            # Obtener datos del cierre
            if isinstance(close_item, SubClosePosition):
                close_data = close_item.close_position
                close_amount_sol = close_item.amount_sol
                close_amount_tokens = close_item.amount_tokens
                close_type = "partial"
            else:
                close_data = close_item
                close_amount_sol = close_item.amount_sol
                close_amount_tokens = close_item.amount_tokens
                close_type = "full"

            # P&L individual de este cierre
            individual_pnl_sol, individual_pnl_usd = cls.calculate_individual_close_pnl(position, close_item, sol_price_usd, include_transaction_costs)

            # P&L acumulado hasta este cierre
            accumulated_pnl_sol, accumulated_pnl_usd = cls.calculate_accumulated_close_pnl(position, sol_price_usd, i, include_transaction_costs)

            breakdown.append({
                'close_index': i,
                'close_id': close_data.id,
                'close_type': close_type,
                'close_timestamp': close_data.created_at.isoformat(),
                'close_status': close_data.status.value,
                'close_amount_sol': close_amount_sol,
                'close_amount_tokens': close_amount_tokens,
                'close_execution_price': close_data.execution_price,
                'individual_pnl_sol': individual_pnl_sol,
                'individual_pnl_usd': individual_pnl_usd,
                'accumulated_pnl_sol': accumulated_pnl_sol,
                'accumulated_pnl_usd': accumulated_pnl_usd
            })

        return breakdown

    @classmethod
    def batch_calculate_pnl(cls, positions: List[OpenPosition], 
                            current_prices: Dict[str, str], 
                            sol_price_usd: str) -> Dict[str, Tuple[str, str]]:
        """
        Calcula P&L para múltiples posiciones de forma eficiente.
        
        Args:
            positions: Lista de posiciones
            current_prices: Diccionario {token_address: current_price}
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Diccionario {position_id: (pnl_sol, pnl_usd)}
        """
        results = {}
        for position in positions:
            if position.token_address in current_prices:
                current_price = current_prices[position.token_address]
                pnl_sol, pnl_usd = cls.calculate_pnl(position, current_price, sol_price_usd)
                results[position.id] = (pnl_sol, pnl_usd)
            else:
                results[position.id] = ("0.0", "0.0")

        return results

    @classmethod
    def get_complete_pnl_breakdown(cls, position: OpenPosition, sol_price_usd: str) -> List[Dict[str, Any]]:
        """
        Obtiene el desglose completo del P&L por cada cierre, incluyendo ambos cálculos (con y sin costos de transacción).
        
        Args:
            position: Objeto OpenPosition
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Lista de diccionarios con desglose completo de P&L por cierre
        """
        breakdown = []

        for i, close_item in enumerate(position.close_history):
            # Obtener datos del cierre
            if isinstance(close_item, SubClosePosition):
                close_data = close_item.close_position
                close_amount_sol = close_item.amount_sol
                close_amount_tokens = close_item.amount_tokens
                close_type = "partial"
            else:
                close_data = close_item
                close_amount_sol = close_item.amount_sol
                close_amount_tokens = close_item.amount_tokens
                close_type = "full"

            # P&L individual sin costos de transacción
            individual_pnl_sol_sin_costos, individual_pnl_usd_sin_costos = cls.calculate_individual_close_pnl(
                position, close_item, sol_price_usd, include_transaction_costs=False
            )

            # P&L individual con costos de transacción
            individual_pnl_sol_con_costos, individual_pnl_usd_con_costos = cls.calculate_individual_close_pnl(
                position, close_item, sol_price_usd, include_transaction_costs=True
            )

            # P&L acumulado sin costos de transacción
            accumulated_pnl_sol_sin_costos, accumulated_pnl_usd_sin_costos = cls.calculate_accumulated_close_pnl(
                position, sol_price_usd, i, include_transaction_costs=False
            )

            # P&L acumulado con costos de transacción
            accumulated_pnl_sol_con_costos, accumulated_pnl_usd_con_costos = cls.calculate_accumulated_close_pnl(
                position, sol_price_usd, i, include_transaction_costs=True
            )

            breakdown.append({
                'close_index': i,
                'close_id': close_data.id,
                'close_type': close_type,
                'close_timestamp': close_data.created_at.isoformat(),
                'close_status': close_data.status.value,
                'close_amount_sol': close_amount_sol,
                'close_amount_tokens': close_amount_tokens,
                'close_execution_price': close_data.execution_price,
                # P&L individual sin costos
                'individual_pnl_sol_sin_costos': individual_pnl_sol_sin_costos,
                'individual_pnl_usd_sin_costos': individual_pnl_usd_sin_costos,
                # P&L individual con costos
                'individual_pnl_sol_con_costos': individual_pnl_sol_con_costos,
                'individual_pnl_usd_con_costos': individual_pnl_usd_con_costos,
                # P&L acumulado sin costos
                'accumulated_pnl_sol_sin_costos': accumulated_pnl_sol_sin_costos,
                'accumulated_pnl_usd_sin_costos': accumulated_pnl_usd_sin_costos,
                # P&L acumulado con costos
                'accumulated_pnl_sol_con_costos': accumulated_pnl_sol_con_costos,
                'accumulated_pnl_usd_con_costos': accumulated_pnl_usd_con_costos
            })

        return breakdown

    @classmethod
    def _calculate_total_closed_amounts(cls, position: OpenPosition) -> Tuple[str, str]:
        """
        Calcula los totales acumulados de cierres.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Tuple de (total_sol, total_tokens) como strings
        """
        total_sol = Decimal('0')
        total_tokens = Decimal('0')

        for close_item in position.close_history:
            if isinstance(close_item, SubClosePosition):
                if close_item.amount_sol:
                    total_sol += Decimal(close_item.amount_sol)
                if close_item.amount_tokens:
                    total_tokens += Decimal(close_item.amount_tokens)
            else:
                if close_item.amount_sol:
                    total_sol += Decimal(close_item.amount_sol)
                if close_item.amount_tokens:
                    total_tokens += Decimal(close_item.amount_tokens)

        return format(total_sol, "f"), format(total_tokens, "f")
