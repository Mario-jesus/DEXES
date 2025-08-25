# -*- coding: utf-8 -*-
"""
Servicio especializado para validación de datos de posiciones de trading.
Separa la lógica de validación de otros análisis.
"""
from typing import Dict, Any
from decimal import Decimal

from ..models import OpenPosition, ClosePosition, SubClosePosition


class PositionValidationService:
    """
    Servicio especializado para validación de datos de posiciones de trading.
    Responsabilidad: Validar consistencia e integridad de los datos.
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
    def validate_trader_consistency(cls, position: OpenPosition) -> bool:
        """
        Valida que todos los trades y cierres pertenezcan al mismo trader.
        
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
        Valida y reporta problemas en los datos de la posición.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Diccionario con problemas encontrados
        """
        issues = []

        # Verificar datos básicos
        if not position.amount_sol_executed or Decimal(position.amount_sol_executed) == 0:
            issues.append("amount_sol is zero or empty")

        if not position.amount_tokens or Decimal(position.amount_tokens) == 0:
            issues.append("amount_tokens is zero or empty")

        if not position.total_cost_sol and not position.amount_sol_executed:
            issues.append("no cost basis available")

        # Verificar consistencia de cierres
        if position.close_history:
            for i, close_item in enumerate(position.close_history):
                if not close_item.amount_sol_executed or Decimal(close_item.amount_sol_executed) == 0:
                    issues.append(f"close {i} has zero amount_sol")

                if not close_item.amount_tokens_executed or Decimal(close_item.amount_tokens_executed) == 0:
                    issues.append(f"close {i} has zero amount_tokens")

                # Verificar que el cierre no exceda la posición original
                if position.amount_tokens_executed and close_item.amount_tokens_executed:
                    if Decimal(close_item.amount_tokens_executed) > Decimal(position.amount_tokens_executed):
                        issues.append(f"close {i} amount_tokens exceeds position total")

        return {
            'has_issues': len(issues) > 0,
            'issues': issues,
            'position_id': position.id,
            'amount_sol': position.amount_sol_executed,
            'amount_tokens': position.amount_tokens_executed,
            'total_cost_sol': position.total_cost_sol,
            'close_count': len(position.close_history)
        }

    @classmethod
    def validate_close_history_consistency(cls, position: OpenPosition) -> Dict[str, Any]:
        """
        Valida la consistencia del historial de cierres.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Diccionario con problemas de consistencia encontrados
        """
        issues = []
        warnings = []
        
        if not position.close_history:
            return {
                'has_issues': False,
                'has_warnings': False,
                'issues': [],
                'warnings': [],
                'total_closed_tokens': '0',
                'total_closed_sol': '0'
            }

        total_closed_tokens = Decimal('0')
        total_closed_sol = Decimal('0')

        for i, close_item in enumerate(position.close_history):
            close_data = cls._get_close_position_data(close_item)

            # Acumular totales
            if close_data.amount_tokens_executed:
                total_closed_tokens += Decimal(close_data.amount_tokens_executed)
            if close_data.amount_sol_executed:
                total_closed_sol += Decimal(close_data.amount_sol_executed)

            # Validar datos del cierre
            if not close_data.execution_price:
                warnings.append(f"close {i} has no execution_price")

            if not close_data.execution_signature:
                warnings.append(f"close {i} has no execution_signature")

        # Verificar que no se exceda la posición original
        if position.amount_tokens_executed:
            original_tokens = Decimal(position.amount_tokens_executed)
            if total_closed_tokens > original_tokens:
                issues.append(f"total closed tokens ({total_closed_tokens}) exceeds original ({original_tokens})")

        if position.amount_sol_executed:
            original_sol = Decimal(position.amount_sol_executed)
            if total_closed_sol > original_sol:
                issues.append(f"total closed SOL ({total_closed_sol}) exceeds original ({original_sol})")

        return {
            'has_issues': len(issues) > 0,
            'has_warnings': len(warnings) > 0,
            'issues': issues,
            'warnings': warnings,
            'total_closed_tokens': format(total_closed_tokens, "f"),
            'total_closed_sol': format(total_closed_sol, "f")
        }

    @classmethod
    def validate_price_data(cls, position: OpenPosition) -> Dict[str, Any]:
        """
        Valida la consistencia de los datos de precios.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Diccionario con problemas de precios encontrados
        """
        issues = []
        warnings = []

        # Validar precio de entrada
        if not position.entry_price:
            issues.append("no entry_price available")
        elif Decimal(position.entry_price) <= 0:
            issues.append("entry_price is zero or negative")

        # Validar precio de ejecución
        if not position.execution_price:
            warnings.append("no execution_price available")
        elif Decimal(position.execution_price) <= 0:
            issues.append("execution_price is zero or negative")

        # Validar precios de cierres
        if position.close_history:
            for i, close_item in enumerate(position.close_history):
                close_data = cls._get_close_position_data(close_item)

                if not close_data.execution_price:
                    warnings.append(f"close {i} has no execution_price")
                elif Decimal(close_data.execution_price) <= 0:
                    issues.append(f"close {i} execution_price is zero or negative")

        return {
            'has_issues': len(issues) > 0,
            'has_warnings': len(warnings) > 0,
            'issues': issues,
            'warnings': warnings
        }

    @classmethod
    def get_validation_summary(cls, position: OpenPosition) -> Dict[str, Any]:
        """
        Obtiene un resumen completo de todas las validaciones.
        
        Args:
            position: Objeto OpenPosition
            
        Returns:
            Diccionario con resumen de todas las validaciones
        """
        data_validation = cls.validate_position_data(position)
        consistency_validation = cls.validate_close_history_consistency(position)
        price_validation = cls.validate_price_data(position)
        trader_consistency = cls.validate_trader_consistency(position)

        total_issues = (
            len(data_validation['issues']) +
            len(consistency_validation['issues']) +
            len(price_validation['issues'])
        )

        total_warnings = (
            len(consistency_validation['warnings']) +
            len(price_validation['warnings'])
        )

        return {
            'position_id': position.id,
            'trader_consistent': trader_consistency,
            'has_issues': total_issues > 0,
            'has_warnings': total_warnings > 0,
            'total_issues': total_issues,
            'total_warnings': total_warnings,
            'data_validation': data_validation,
            'consistency_validation': consistency_validation,
            'price_validation': price_validation,
            'overall_status': 'VALID' if total_issues == 0 else 'INVALID'
        }
