# -*- coding: utf-8 -*-
"""
Servicio especializado para cálculos utilitarios de posiciones de trading.
Separa la lógica de cálculos básicos de otros análisis.
"""
from typing import Dict, Any, Tuple
from decimal import Decimal, getcontext

from ..models import OpenPosition, ClosePosition, SubClosePosition

# Configurar precisión de Decimal para operaciones financieras
getcontext().prec = 26


class PositionCalculationService:
    """
    Servicio especializado para cálculos utilitarios de posiciones de trading.
    Responsabilidad: Cálculos básicos y métodos auxiliares.
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
    def _is_close_position_partial(cls, close_item: SubClosePosition | ClosePosition) -> bool:
        """
        Verifica si un item del historial es ClosePositionPartial.
        
        Args:
            close_item: Item del historial
            
        Returns:
            True si es ClosePositionPartial, False si es ClosePosition
        """
        return isinstance(close_item, SubClosePosition)

    @classmethod
    def _get_close_amounts(cls, close_item: SubClosePosition | ClosePosition) -> Tuple[str, str]:
        """
        Obtiene los montos de SOL y tokens de un item del historial.
        
        Args:
            close_item: Item del historial
            
        Returns:
            Tuple de (amount_sol, amount_tokens)
        """
        return close_item.amount_sol, close_item.amount_tokens

    @classmethod
    def get_last_close_data(cls, position: OpenPosition) -> Dict[str, Any]:
        """
        Obtiene los datos del último cierre de una posición.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Diccionario con datos del último cierre
        """
        if not position.close_history:
            return {
                'amount_sol': '',
                'amount_tokens': '',
                'execution_price': '',
                'fee_sol': '',
                'signature': None
            }

        last_close = position.close_history[-1]
        close_position = cls._get_close_position_data(last_close)

        return {
            'amount_sol': close_position.amount_sol,
            'amount_tokens': close_position.amount_tokens,
            'execution_price': close_position.execution_price,
            'fee_sol': close_position.fee_sol,
            'signature': close_position.execution_signature
        }

    @classmethod
    def calculate_total_closed_amounts(cls, position: OpenPosition) -> Tuple[str, str]:
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
            amount_sol, amount_tokens = cls._get_close_amounts(close_item)
            if amount_sol:
                total_sol += Decimal(amount_sol)
            if amount_tokens:
                total_tokens += Decimal(amount_tokens)

        return format(total_sol, "f"), format(total_tokens, "f")

    @classmethod
    def calculate_remaining_tokens(cls, position: OpenPosition) -> str:
        """
        Calcula la cantidad de tokens restantes.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Cantidad de tokens restantes como string
        """
        _, total_closed_tokens = cls.calculate_total_closed_amounts(position)
        total_original = Decimal(position.amount_tokens) if position.amount_tokens else Decimal('0')
        remaining = max(Decimal('0'), total_original - Decimal(total_closed_tokens))
        return format(remaining, "f")

    @classmethod
    def calculate_remaining_amounts(cls, position: OpenPosition) -> Tuple[str, str]:
        """
        Calcula la cantidad de tokens y SOL restantes.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Tuple de (remaining_sol, remaining_tokens) como strings
        """
        total_closed_sol, total_closed_tokens = cls.calculate_total_closed_amounts(position)
        total_original_tokens = Decimal(position.amount_tokens) if position.amount_tokens else Decimal('0')
        total_original_sol = Decimal(position.amount_sol) if position.amount_sol else Decimal('0')
        remaining_sol = max(Decimal('0'), total_original_sol - Decimal(total_closed_sol))
        remaining_tokens = max(Decimal('0'), total_original_tokens - Decimal(total_closed_tokens))
        return format(remaining_sol, "f"), format(remaining_tokens, "f")

    @classmethod
    def get_calculated_data(cls, position: OpenPosition) -> Dict[str, Any]:
        """
        Obtiene datos calculados para compatibilidad con código existente.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Diccionario con datos calculados on-demand
        """
        # Importar servicios necesarios para evitar dependencias circulares
        from .slippage_analysis_service import SlippageAnalysisService
        
        slippage_data = SlippageAnalysisService.calculate_total_slippage_impact(position)
        last_close_data = cls.get_last_close_data(position)
        total_closed_sol, total_closed_tokens = cls.calculate_total_closed_amounts(position)
        remaining_tokens = cls.calculate_remaining_tokens(position)

        return {
            'close_amount_sol': last_close_data['amount_sol'],
            'close_amount_tokens': last_close_data['amount_tokens'],
            'close_entry_price': position.entry_price,
            'close_execution_price': last_close_data['execution_price'],
            'close_fee_sol': position.fee_sol,
            'close_total_cost_sol': total_closed_sol,
            'close_signature': last_close_data['signature'],
            'total_closed_amount_sol': total_closed_sol,
            'total_closed_tokens': total_closed_tokens,
            'remaining_tokens': remaining_tokens,
            'execution_slippage_percentage': slippage_data['execution_slippage_percentage'],
            'execution_slippage_value_sol': slippage_data['execution_slippage_value_sol'],
            'execution_slippage_value_usd': slippage_data['execution_slippage_value_usd'],
            'total_close_slippage_percentage': slippage_data['total_close_slippage_percentage'],
            'total_close_slippage_value_sol': slippage_data['total_close_slippage_value_sol'],
            'total_close_slippage_value_usd': slippage_data['total_close_slippage_value_usd'],
        }

    @classmethod
    def calculate_position_metrics(cls, position: OpenPosition) -> Dict[str, Any]:
        """
        Calcula métricas básicas de una posición.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Diccionario con métricas calculadas
        """
        total_closed_sol, total_closed_tokens = cls.calculate_total_closed_amounts(position)
        remaining_sol, remaining_tokens = cls.calculate_remaining_amounts(position)
        last_close_data = cls.get_last_close_data(position)

        return {
            'position_id': position.id,
            'status': position.status.value,
            'original_amount_sol': position.amount_sol,
            'original_amount_tokens': position.amount_tokens,
            'total_closed_sol': total_closed_sol,
            'total_closed_tokens': total_closed_tokens,
            'remaining_sol': remaining_sol,
            'remaining_tokens': remaining_tokens,
            'close_count': len(position.close_history),
            'last_close_amount_sol': last_close_data['amount_sol'],
            'last_close_amount_tokens': last_close_data['amount_tokens'],
            'last_close_execution_price': last_close_data['execution_price'],
            'entry_price': position.entry_price,
            'execution_price': position.execution_price,
            'fee_sol': position.fee_sol,
            'total_cost_sol': position.total_cost_sol
        }

    @classmethod
    def calculate_position_performance(cls, position: OpenPosition, current_price: str, sol_price_usd: str) -> Dict[str, Any]:
        """
        Calcula métricas de rendimiento de una posición.
        
        Args:
            position: Objeto OpenPosition
            current_price: Precio actual del token (opcional)
            
        Returns:
            Diccionario con métricas de rendimiento
        """
        # Importar servicios necesarios
        from .pnl_calculation_service import PnLCalculationService
        from .slippage_analysis_service import SlippageAnalysisService

        metrics = {
            'position_id': position.id,
            'status': position.status.value,
            'total_closed_sol': '0.0',
            'total_closed_tokens': '0.0',
            'remaining_tokens': '0.0',
            'realized_pnl_sol': '0.0',
            'realized_pnl_usd': '0.0',
            'unrealized_pnl_sol': '0.0',
            'unrealized_pnl_usd': '0.0',
            'total_slippage_impact_sol': '0.0',
            'total_slippage_impact_usd': '0.0'
        }

        # Cálculos básicos
        total_closed_sol, total_closed_tokens = cls.calculate_total_closed_amounts(position)
        remaining_tokens = cls.calculate_remaining_tokens(position)

        metrics.update({
            'total_closed_sol': total_closed_sol,
            'total_closed_tokens': total_closed_tokens,
            'remaining_tokens': remaining_tokens
        })

        # P&L realizado (si hay cierres)
        if position.close_history:
            realized_pnl_sol, realized_pnl_usd = PnLCalculationService.calculate_realized_pnl(position, sol_price_usd)
            metrics.update({
                'realized_pnl_sol': realized_pnl_sol,
                'realized_pnl_usd': realized_pnl_usd
            })

        # P&L no realizado (si la posición está abierta y hay precio actual)
        if position.status.value == 'OPEN' and current_price and remaining_tokens != '0.0':
            unrealized_pnl_sol, unrealized_pnl_usd = PnLCalculationService.calculate_pnl(position, current_price, sol_price_usd)
            metrics.update({
                'unrealized_pnl_sol': unrealized_pnl_sol,
                'unrealized_pnl_usd': unrealized_pnl_usd
            })

        # Impacto del slippage
        slippage_data = SlippageAnalysisService.calculate_total_slippage_impact(position)
        metrics.update({
            'total_slippage_impact_sol': format(
                Decimal(slippage_data['execution_slippage_value_sol']) + 
                Decimal(slippage_data['total_close_slippage_value_sol']), 
                "f"
            ),
            'total_slippage_impact_usd': format(
                Decimal(slippage_data['execution_slippage_value_usd']) + 
                Decimal(slippage_data['total_close_slippage_value_usd']), 
                "f"
            )
        })

        return metrics
