# -*- coding: utf-8 -*-
"""
Servicios de análisis y cálculo para posiciones de trading.
Separa la lógica de negocio de la estructura de datos.
"""
from typing import Dict, Optional, Any, Tuple, List, Union
from decimal import Decimal, getcontext
from icecream import ic

from ..models import OpenPosition, ClosePosition, PositionStatus, SubClosePosition

# Configurar precisión de Decimal para operaciones financieras
getcontext().prec = 26


class PositionAnalysisService:
    """
    Servicio para análisis y cálculos de posiciones de trading.
    Contiene toda la lógica de negocio separada de la estructura de datos.
    """

    @classmethod
    def _get_close_position_data(cls, close_item: Union[ClosePosition, SubClosePosition]) -> ClosePosition:
        """
        Obtiene los datos de ClosePosition de un item del historial
        
        Args:
            close_item: Item del historial (ClosePosition o ClosePositionPartial)
            
        Returns:
            ClosePosition con los datos del cierre
        """
        if isinstance(close_item, SubClosePosition):
            return close_item.close_position
        return close_item

    @classmethod
    def _is_close_position_partial(cls, close_item: Union[ClosePosition, SubClosePosition]) -> bool:
        """
        Verifica si un item del historial es ClosePositionPartial
        
        Args:
            close_item: Item del historial
            
        Returns:
            True si es ClosePositionPartial, False si es ClosePosition
        """
        return isinstance(close_item, SubClosePosition)

    @classmethod
    def _get_close_amounts(cls, close_item: Union[ClosePosition, SubClosePosition]) -> Tuple[str, str]:
        """
        Obtiene los montos de SOL y tokens de un item del historial
        
        Args:
            close_item: Item del historial
            
        Returns:
            Tuple de (amount_sol, amount_tokens)
        """
        return close_item.amount_sol, close_item.amount_tokens

    @classmethod
    def get_last_close_data(cls, position: OpenPosition) -> Dict[str, Any]:
        """
        Obtiene los datos del último cierre de una posición
        
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
        Calcula los totales acumulados de cierres
        
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
        Calcula la cantidad de tokens restantes
        
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
        Calcula la cantidad de tokens y SOL restantes
        
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
    def _get_cost_basis(cls, position: OpenPosition) -> Decimal:
        """
        Obtiene el costo base de la posición
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Costo base como Decimal
        """
        return Decimal(position.total_cost_sol) if position.total_cost_sol else Decimal(position.amount_sol)

    @classmethod
    def calculate_execution_slippage(cls, position: OpenPosition) -> str:
        """
        Calcula el slippage de la ejecución inicial
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Slippage como porcentaje en string
        """
        if not position.entry_price or not position.execution_price:
            return "0.0"

        expected = Decimal(position.entry_price)
        actual = Decimal(position.execution_price)

        if expected == 0:
            return "0.0"

        slippage_percentage = ((actual - expected) / expected) * 100
        return format(slippage_percentage, "f")

    @classmethod
    def calculate_total_slippage_impact(cls, position: OpenPosition, sol_price_usd: str = "150.0") -> Dict[str, str]:
        """
        Calcula el impacto total del slippage en la posición
        
        Args:
            position: Objeto OpenPosition
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Diccionario con diferentes métricas de slippage
        """
        results = {
            'execution_slippage_percentage': '0.0',
            'execution_slippage_value_sol': '0.0',
            'execution_slippage_value_usd': '0.0',
            'total_close_slippage_percentage': '0.0',
            'total_close_slippage_value_sol': '0.0',
            'total_close_slippage_value_usd': '0.0'
        }

        # Slippage de ejecución
        if position.entry_price and position.execution_price:
            exec_slippage_pct = cls.calculate_execution_slippage(position)
            results['execution_slippage_percentage'] = exec_slippage_pct

            # Valor del slippage de ejecución
            expected_value = Decimal(position.amount_sol)
            actual_value = expected_value * (1 + Decimal(exec_slippage_pct) / 100)
            slippage_value_sol = actual_value - expected_value
            results['execution_slippage_value_sol'] = format(slippage_value_sol, "f")
            results['execution_slippage_value_usd'] = format(slippage_value_sol * Decimal(sol_price_usd), "f")

        # Slippage de cierres
        if position.close_history:
            total_slippage_value_sol = Decimal('0')
            total_slippage_pct = Decimal('0')
            close_count = 0

            for close_item in position.close_history:
                close_data = cls._get_close_position_data(close_item)
                if close_data.execution_price and close_data.amount_sol:
                    # Calcular slippage vs precio de entrada
                    close_slippage_pct = cls._calculate_close_slippage_vs_entry(position, close_data)
                    if close_slippage_pct != "0.0":
                        total_slippage_pct += Decimal(close_slippage_pct)
                        close_count += 1

                        # Valor del slippage de este cierre
                        close_amount = Decimal(close_data.amount_sol)
                        slippage_impact = close_amount * (Decimal(close_slippage_pct) / 100)
                        total_slippage_value_sol += slippage_impact

            if close_count > 0:
                avg_slippage_pct = total_slippage_pct / close_count
                results['total_close_slippage_percentage'] = format(avg_slippage_pct, "f")
                results['total_close_slippage_value_sol'] = format(total_slippage_value_sol, "f")
                results['total_close_slippage_value_usd'] = format(total_slippage_value_sol * Decimal(sol_price_usd), "f")

        return results

    @classmethod
    def _calculate_close_slippage(cls, close_data: ClosePosition, expected_price: str) -> str:
        """
        Calcula el slippage de un cierre específico
        
        Args:
            close_data: Datos del cierre
            expected_price: Precio esperado para el cierre
            
        Returns:
            Slippage como porcentaje en string
        """
        if not close_data.execution_price or not expected_price:
            return "0.0"

        expected = Decimal(expected_price)
        actual = Decimal(close_data.execution_price)

        if expected == 0:
            return "0.0"

        slippage_percentage = ((actual - expected) / expected) * 100
        return format(slippage_percentage, "f")

    @classmethod
    def _calculate_close_slippage_vs_entry(cls, position: OpenPosition, close_data: ClosePosition) -> str:
        """
        Calcula slippage del cierre vs precio de entrada original
        
        Args:
            position: Objeto OpenPosition
            close_data: Datos del cierre
            
        Returns:
            Slippage como porcentaje en string
        """
        if not position.entry_price:
            return "0.0"
        return cls._calculate_close_slippage(close_data, position.entry_price)

    @classmethod
    def _calculate_close_slippage_vs_trader(cls, close_data: ClosePosition, trader_close_price: str) -> str:
        """
        Calcula slippage del cierre vs precio del trader original
        
        Args:
            close_data: Datos del cierre
            trader_close_price: Precio al que cerró el trader
            
        Returns:
            Slippage como porcentaje en string
        """
        return cls._calculate_close_slippage(close_data, trader_close_price)

    @classmethod
    def _calculate_close_slippage_vs_market(cls, close_data: ClosePosition, market_price: str) -> str:
        """
        Calcula slippage del cierre vs precio de mercado
        
        Args:
            close_data: Datos del cierre
            market_price: Precio de mercado en el momento del cierre
            
        Returns:
            Slippage como porcentaje en string
        """
        return cls._calculate_close_slippage(close_data, market_price)

    @classmethod
    def get_close_slippage_analysis(cls, position: OpenPosition, close_data: ClosePosition, 
                                    trader_price: Optional[str] = None,
                                    market_price: Optional[str] = None) -> Dict[str, str]:
        """
        Análisis completo de slippage para un cierre
        
        Args:
            position: Objeto OpenPosition
            close_data: Datos del cierre
            trader_price: Precio del trader (opcional)
            market_price: Precio de mercado (opcional)
            
        Returns:
            Diccionario con diferentes tipos de slippage
        """
        analysis = {
            'vs_entry_price': cls._calculate_close_slippage_vs_entry(position, close_data),
            'vs_trader_price': '0.0',
            'vs_market_price': '0.0',
            'entry_price': position.entry_price or '0.0',
            'execution_price': close_data.execution_price or '0.0',
            'trader_price': trader_price or '0.0',
            'market_price': market_price or '0.0'
        }

        if trader_price:
            analysis['vs_trader_price'] = cls._calculate_close_slippage_vs_trader(close_data, trader_price)

        if market_price:
            analysis['vs_market_price'] = cls._calculate_close_slippage_vs_market(close_data, market_price)

        return analysis

    @classmethod
    def get_all_closes_slippage_analysis(cls, position: OpenPosition,
                                        trader_prices: Optional[Dict[str, str]] = None,
                                        market_prices: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Análisis completo de slippage para todos los cierres
        
        Args:
            position: Objeto OpenPosition
            trader_prices: Diccionario {close_id: trader_price} (opcional)
            market_prices: Diccionario {close_id: market_price} (opcional)
            
        Returns:
            Lista de análisis de slippage por cada cierre
        """
        analysis_list = []

        for close_item in position.close_history:
            close_data = cls._get_close_position_data(close_item)

            # Obtener precios específicos para este cierre si están disponibles
            trader_price = trader_prices.get(close_data.id) if trader_prices else None
            market_price = market_prices.get(close_data.id) if market_prices else None

            # Análisis de slippage para este cierre
            slippage_analysis = cls.get_close_slippage_analysis(position, close_data, trader_price, market_price)

            # Agregar información adicional del cierre
            close_analysis = {
                'close_id': close_data.id,
                'close_timestamp': close_data.created_at.isoformat(),
                'close_type': close_data.status.value,
                'close_amount_sol': close_data.amount_sol,
                'close_amount_tokens': close_data.amount_tokens,
                'close_entry_price': close_data.entry_price,
                'close_execution_price': close_data.execution_price,
                'slippage_analysis': slippage_analysis
            }

            analysis_list.append(close_analysis)

        return analysis_list

    @classmethod
    def validate_trader_consistency(cls, position: OpenPosition) -> bool:
        """
        Valida que todos los trades y cierres pertenezcan al mismo trader
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            True si todos los datos son consistentes, False si hay inconsistencias
        """
        if not position.trader_wallet:
            return False

        # Verificar que el trader_trade_data sea del mismo trader
        if position.trader_trade_data:
            if position.trader_trade_data.trader_wallet != position.trader_wallet:
                return False

        return True

    @classmethod
    def validate_position_data(cls, position: OpenPosition) -> Dict[str, Any]:
        """
        Valida y reporta problemas en los datos de la posición
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Diccionario con problemas encontrados
        """
        issues = []
        
        # Verificar datos básicos
        if not position.amount_sol or Decimal(position.amount_sol) == 0:
            issues.append("amount_sol is zero or empty")
            
        if not position.amount_tokens or Decimal(position.amount_tokens) == 0:
            issues.append("amount_tokens is zero or empty")
            
        if not position.total_cost_sol and not position.amount_sol:
            issues.append("no cost basis available")
            
        # Verificar consistencia de cierres
        if position.close_history:
            for i, close_item in enumerate(position.close_history):
                close_data = cls._get_close_position_data(close_item)
                
                if not close_data.amount_sol or Decimal(close_data.amount_sol) == 0:
                    issues.append(f"close {i} has zero amount_sol")
                    
                if not close_data.amount_tokens or Decimal(close_data.amount_tokens) == 0:
                    issues.append(f"close {i} has zero amount_tokens")
                    
                # Verificar que el cierre no exceda la posición original
                if position.amount_tokens and close_data.amount_tokens:
                    if Decimal(close_data.amount_tokens) > Decimal(position.amount_tokens):
                        issues.append(f"close {i} amount_tokens exceeds position total")
        
        return {
            'has_issues': len(issues) > 0,
            'issues': issues,
            'position_id': position.id,
            'amount_sol': position.amount_sol,
            'amount_tokens': position.amount_tokens,
            'total_cost_sol': position.total_cost_sol,
            'close_count': len(position.close_history)
        }

    @classmethod
    def _calculate_pnl_from_amounts(cls, amount: Decimal, cost_basis: Decimal, sol_price_usd: Decimal) -> Tuple[Decimal, Decimal]:
        """
        Calcula P&L a partir de un monto y costo base
        
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
    def calculate_pnl(cls, position: OpenPosition, current_price: str, sol_price_usd: str = "150.0") -> Tuple[str, str]:
        """
        Calcula P&L actual basado en el estado de la posición
        
        Args:
            position: Objeto OpenPosition
            current_price: Precio actual del token
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        ic("Status: ", position.status)

        if position.status not in [PositionStatus.OPEN, PositionStatus.CLOSED, PositionStatus.PARTIALLY_CLOSED]:
            return "0.0", "0.0"

        if position.status == PositionStatus.OPEN:
            if not position.amount_tokens or Decimal(position.amount_tokens) == 0:
                return "0.0", "0.0"

            current_value = Decimal(position.amount_tokens) * Decimal(current_price)
            cost_basis = cls._get_cost_basis(position)
            pnl_sol, pnl_usd = cls._calculate_pnl_from_amounts(current_value, cost_basis, Decimal(sol_price_usd))

            return format(pnl_sol, "f"), format(pnl_usd, "f")

        elif position.status in [PositionStatus.CLOSED, PositionStatus.PARTIALLY_CLOSED]:
            if position.close_history:
                total_closed_sol, _ = cls.calculate_total_closed_amounts(position)
                if total_closed_sol == "0" or total_closed_sol == "":
                    return "0.0", "0.0"

                cost_basis = cls._get_cost_basis(position)
                pnl_sol, pnl_usd = cls._calculate_pnl_from_amounts(Decimal(total_closed_sol), cost_basis, Decimal(sol_price_usd))

                ic(f"Realized P&L (from history) - Cost: {cost_basis}, Total Closed: {total_closed_sol}, P&L: {pnl_sol}")
            else:
                return "0.0", "0.0"

            return format(pnl_sol, "f"), format(pnl_usd, "f")

        return "0.0", "0.0"

    @classmethod
    def calculate_simple_pnl(cls, position: OpenPosition, sol_price_usd: str = "150.0") -> Tuple[str, str]:
        """
        Calcula P&L de forma simplificada para posiciones cerradas
        
        Args:
            position: Objeto OpenPosition
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        if not position.close_history:
            return "0.0", "0.0"

        # Calcular total recibido en cierres
        total_received = Decimal('0')
        for close_item in position.close_history:
            close_data = cls._get_close_position_data(close_item)
            if close_data.amount_sol:
                total_received += Decimal(close_data.amount_sol)

        # Obtener costo total de la posición
        total_cost = cls._get_cost_basis(position)
        
        # Calcular P&L simple
        pnl_sol = total_received - total_cost
        pnl_usd = pnl_sol * Decimal(sol_price_usd)
        
        ic(f"Simple P&L - Total Received: {total_received}, Total Cost: {total_cost}, P&L: {pnl_sol}")
        
        return format(pnl_sol, "f"), format(pnl_usd, "f")

    @classmethod
    def calculate_robust_pnl(cls, position: OpenPosition, sol_price_usd: str = "150.0") -> Tuple[str, str]:
        """
        Calcula P&L de forma robusta manejando casos edge
        
        Args:
            position: Objeto OpenPosition
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        # Validar datos primero
        validation = cls.validate_position_data(position)
        if validation['has_issues']:
            ic(f"Position has data issues: {validation['issues']}")
            
        # Si hay problemas con los datos, usar cálculo simple
        if validation['has_issues']:
            return cls.calculate_simple_pnl(position, sol_price_usd)
            
        # Si no hay cierres, P&L es 0
        if not position.close_history:
            return "0.0", "0.0"
            
        # Intentar cálculo proporcional primero
        try:
            pnl_breakdown = cls.get_close_pnl_breakdown(position, sol_price_usd)
            total_pnl_sol = sum(Decimal(item['individual_pnl_sol']) for item in pnl_breakdown)
            total_pnl_usd = sum(Decimal(item['individual_pnl_usd']) for item in pnl_breakdown)
            
            ic(f"Robust P&L (proportional) - Total: {total_pnl_sol}")
            return format(total_pnl_sol, "f"), format(total_pnl_usd, "f")
            
        except Exception as e:
            ic(f"Proportional P&L calculation failed: {e}, falling back to simple")
            return cls.calculate_simple_pnl(position, sol_price_usd)

    @classmethod
    def _get_proportional_cost(cls, position: OpenPosition, close_tokens: Decimal) -> Decimal:
        """
        Calcula el costo proporcional para una cantidad de tokens
        
        Args:
            position: Objeto OpenPosition
            close_tokens: Cantidad de tokens a cerrar
            
        Returns:
            Costo proporcional en SOL
        """
        total_tokens = Decimal(position.amount_tokens) if position.amount_tokens else Decimal('0')
        if total_tokens == 0:
            ic(f"Warning: total_tokens is 0 for position {position.id}")
            return Decimal('0')

        proportion = close_tokens / total_tokens
        total_cost = cls._get_cost_basis(position)
        
        ic(f"Proportional Cost Debug - Close Tokens: {close_tokens}, Total Tokens: {total_tokens}, Proportion: {proportion}, Total Cost: {total_cost}")
        
        return total_cost * proportion

    @classmethod
    def calculate_individual_close_pnl(cls, position: OpenPosition, close_data: ClosePosition, sol_price_usd: str = "150.0") -> Tuple[str, str]:
        """
        Calcula el P&L de un cierre individual sin considerar otros cierres
        
        Args:
            position: Objeto OpenPosition
            close_data: Datos del cierre
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        if not close_data.amount_sol:
            ic(f"Warning: close_data.amount_sol is empty for close {close_data.id}")
            return "0.0", "0.0"

        close_tokens = Decimal(close_data.amount_tokens) if close_data.amount_tokens else Decimal('0')
        if close_tokens == 0:
            ic(f"Warning: close_tokens is 0 for close {close_data.id}")
            return "0.0", "0.0"

        # Verificar que tenemos datos válidos de la posición
        if not position.amount_tokens:
            ic(f"Warning: position.amount_tokens is empty for position {position.id}")
            return "0.0", "0.0"

        proportional_cost = cls._get_proportional_cost(position, close_tokens)
        close_amount = Decimal(close_data.amount_sol)
        pnl_sol, pnl_usd = cls._calculate_pnl_from_amounts(close_amount, proportional_cost, Decimal(sol_price_usd))

        ic(f"Individual Close P&L - Position: {position.id}, Close: {close_amount}, Prop Cost: {proportional_cost}, P&L: {pnl_sol}")

        return format(pnl_sol, "f"), format(pnl_usd, "f")

    @classmethod
    def calculate_accumulated_close_pnl(cls, position: OpenPosition, up_to_close_index: int = -1, sol_price_usd: str = "150.0") -> Tuple[str, str]:
        """
        Calcula el P&L acumulado hasta un cierre específico
        
        Args:
            position: Objeto OpenPosition
            up_to_close_index: Índice del cierre hasta donde calcular (por defecto -1 para el último)
            sol_price_usd: Precio de SOL en USD
            
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
            close_data = cls._get_close_position_data(close_item)
            close_tokens = Decimal(close_data.amount_tokens) if close_data.amount_tokens else Decimal('0')
            close_amount = Decimal(close_data.amount_sol) if close_data.amount_sol else Decimal('0')

            if close_tokens > 0:
                # Usar métodos auxiliares para calcular P&L
                proportional_cost = cls._get_proportional_cost(position, close_tokens)
                pnl_sol, _ = cls._calculate_pnl_from_amounts(close_amount, proportional_cost, Decimal(sol_price_usd))
                total_pnl_sol += pnl_sol

                ic(f"Accumulated P&L step {i}: Close {close_amount}, Cost {proportional_cost}, P&L {pnl_sol}, Total {total_pnl_sol}")

        total_pnl_usd = total_pnl_sol * Decimal(sol_price_usd)

        return format(total_pnl_sol, "f"), format(total_pnl_usd, "f")

    @classmethod
    def get_close_pnl_breakdown(cls, position: OpenPosition, sol_price_usd: str = "150.0") -> List[Dict[str, Any]]:
        """
        Obtiene el desglose completo del P&L por cada cierre
        
        Args:
            position: Objeto OpenPosition
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Lista de diccionarios con desglose de P&L por cierre
        """
        breakdown = []

        for i, close_item in enumerate(position.close_history):
            close_data = cls._get_close_position_data(close_item)

            # P&L individual de este cierre
            individual_pnl_sol, individual_pnl_usd = cls.calculate_individual_close_pnl(position, close_data, sol_price_usd)

            # P&L acumulado hasta este cierre
            accumulated_pnl_sol, accumulated_pnl_usd = cls.calculate_accumulated_close_pnl(position, i, sol_price_usd)

            breakdown.append({
                'close_index': i,
                'close_id': close_data.id,
                'close_timestamp': close_data.created_at.isoformat(),
                'close_status': close_data.status.value,
                'close_amount_sol': close_data.amount_sol,
                'close_amount_tokens': close_data.amount_tokens,
                'close_execution_price': close_data.execution_price,
                'individual_pnl_sol': individual_pnl_sol,
                'individual_pnl_usd': individual_pnl_usd,
                'accumulated_pnl_sol': accumulated_pnl_sol,
                'accumulated_pnl_usd': accumulated_pnl_usd
            })

        return breakdown

    @classmethod
    def get_calculated_data(cls, position: OpenPosition) -> Dict[str, Any]:
        """
        Obtiene datos calculados para compatibilidad con código existente
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Diccionario con datos calculados on-demand
        """
        slippage_data = cls.calculate_total_slippage_impact(position)
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

    # Métodos de clase para operaciones en lote
    @classmethod
    def batch_calculate_pnl(cls, positions: List[OpenPosition], 
                            current_prices: Dict[str, str], 
                            sol_price_usd: str = "150.0") -> Dict[str, Tuple[str, str]]:
        """
        Calcula P&L para múltiples posiciones de forma eficiente
        
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
    def batch_get_summary_stats(cls, positions: List[OpenPosition]) -> Dict[str, Any]:
        """
        Obtiene estadísticas resumidas de múltiples posiciones
        
        Args:
            positions: Lista de posiciones
            
        Returns:
            Diccionario con estadísticas agregadas
        """
        stats = {
            'total_positions': len(positions),
            'open_positions': 0,
            'closed_positions': 0,
            'partially_closed_positions': 0,
            'total_volume_sol': Decimal('0'),
            'total_fees_sol': Decimal('0'),
            'unique_traders': set(),
            'unique_tokens': set()
        }

        for position in positions:
            # Contar por estado
            if position.status == PositionStatus.OPEN:
                stats['open_positions'] += 1
            elif position.status == PositionStatus.CLOSED:
                stats['closed_positions'] += 1
            elif position.status == PositionStatus.PARTIALLY_CLOSED:
                stats['partially_closed_positions'] += 1

            # Acumular volúmenes
            if position.amount_sol:
                stats['total_volume_sol'] += Decimal(position.amount_sol)
            if position.fee_sol:
                stats['total_fees_sol'] += Decimal(position.fee_sol)

            # Contar únicos
            if position.trader_wallet:
                stats['unique_traders'].add(position.trader_wallet)
            if position.token_address:
                stats['unique_tokens'].add(position.token_address)

        # Convertir sets a conteos
        stats['unique_traders'] = len(stats['unique_traders'])
        stats['unique_tokens'] = len(stats['unique_tokens'])
        stats['total_volume_sol'] = format(stats['total_volume_sol'], "f")
        stats['total_fees_sol'] = format(stats['total_fees_sol'], "f")
        
        return stats

    @classmethod
    def filter_positions_by_criteria(cls, positions: List[OpenPosition], 
                                    criteria: Dict[str, Any]) -> List[OpenPosition]:
        """
        Filtra posiciones por criterios específicos de forma eficiente
        
        Args:
            positions: Lista de posiciones
            criteria: Diccionario con criterios de filtrado
                - status: Lista de estados válidos
                - trader_wallet: Wallet específico
                - token_address: Token específico
                - min_amount_sol: Monto mínimo en SOL
                - max_amount_sol: Monto máximo en SOL
                - created_after: Fecha mínima de creación
                - created_before: Fecha máxima de creación
                
        Returns:
            Lista de posiciones que cumplen los criterios
        """
        filtered = []

        for position in positions:
            # Filtro por estado
            if 'status' in criteria and position.status not in criteria['status']:
                continue

            # Filtro por trader
            if 'trader_wallet' in criteria and position.trader_wallet != criteria['trader_wallet']:
                continue

            # Filtro por token
            if 'token_address' in criteria and position.token_address != criteria['token_address']:
                continue

            # Filtro por monto mínimo
            if 'min_amount_sol' in criteria:
                min_amount = Decimal(criteria['min_amount_sol'])
                position_amount = Decimal(position.amount_sol) if position.amount_sol else Decimal('0')
                if position_amount < min_amount:
                    continue

            # Filtro por monto máximo
            if 'max_amount_sol' in criteria:
                max_amount = Decimal(criteria['max_amount_sol'])
                position_amount = Decimal(position.amount_sol) if position.amount_sol else Decimal('0')
                if position_amount > max_amount:
                    continue

            # Filtro por fecha mínima
            if 'created_after' in criteria and position.created_at < criteria['created_after']:
                continue

            # Filtro por fecha máxima
            if 'created_before' in criteria and position.created_at > criteria['created_before']:
                continue

            filtered.append(position)

        return filtered

    @classmethod
    def get_memory_usage_estimate(cls, position: OpenPosition) -> int:
        """
        Estima el uso de memoria de una posición en bytes
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Estimación de bytes utilizados
        """
        # Tamaño base de la posición
        base_size = (
            len(position.id) +
            len(position.trader_wallet) +
            len(position.token_address) +
            len(position.amount_sol) +
            len(position.amount_tokens) +
            len(position.entry_price) +
            len(position.fee_sol) +
            len(position.total_cost_sol) +
            (len(position.execution_signature) if position.execution_signature else 0) +
            len(position.execution_price)
        )

        # Tamaño del historial de cierres
        close_history_size = 0
        for close_item in position.close_history:
            close_data = cls._get_close_position_data(close_item)
            close_history_size += (
                len(close_data.id) + len(close_data.amount_sol) + len(close_data.amount_tokens) +
                len(close_data.entry_price) + len(close_data.fee_sol) + len(close_data.total_cost_sol) +
                (len(close_data.execution_signature) if close_data.execution_signature else 0) +
                len(close_data.execution_price)
            )

        # Tamaño del metadata
        metadata_size = sum(
            len(str(key)) + len(str(value)) 
            for key, value in position.metadata.items()
        )

        # Tamaño del trader_trade_data
        trader_data_size = 0
        if position.trader_trade_data:
            trader_data_size = sum(
                len(str(value)) for value in position.trader_trade_data
            )

        return base_size + close_history_size + metadata_size + trader_data_size

    @classmethod
    def optimize_position_for_storage(cls, position: OpenPosition) -> None:
        """
        Optimiza una posición para almacenamiento eliminando datos innecesarios
        
        Args:
            position: Objeto OpenPosition a optimizar
        """
        # Limpiar metadata si es muy grande
        if len(position.metadata) > 100:
            # Mantener solo las claves más importantes
            important_keys = {'last_analysis', 'performance_metrics', 'risk_score'}
            keys_to_remove = [k for k in position.metadata.keys() if k not in important_keys]
            for key in keys_to_remove[:50]:  # Remover, máximo 50 claves
                del position.metadata[key]

        # Limitar el historial de cierres si es muy largo
        if len(position.close_history) > 50:
            # Mantener solo los últimos 50 cierres
            position.close_history = position.close_history[-50:]
