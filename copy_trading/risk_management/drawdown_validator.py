# -*- coding: utf-8 -*-
"""
DrawdownValidator - Validador de drawdown para ValidationEngine
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..risk_management.drawdown_manager import DrawdownManager
    from ..validation import ValidationCheck


class DrawdownValidator:
    """
    Validador de drawdown que puede ser usado por ValidationEngine.
    """

    @staticmethod
    async def check_drawdown(
        drawdown_manager: "DrawdownManager",
        side: str
    ) -> "ValidationCheck":
        """
        Verifica si el drawdown permite ejecutar un trade.
        
        Args:
            drawdown_manager: Instancia de DrawdownManager
            side: 'buy' o 'sell'
            
        Returns:
            ValidationCheck con el resultado de la validación
        """
        from ..validation import ValidationCheck, ValidationResult

        check = ValidationCheck(name="DrawdownCheck")

        try:
            is_allowed, reason = await drawdown_manager.check_drawdown_allows_trade(side)

            if is_allowed:
                # Obtener métricas para detalles
                metrics = await drawdown_manager.get_drawdown_metrics()
                details = {
                    'drawdown_percent': format(metrics.drawdown_percent, "f"),
                    'drawdown_sol': format(metrics.drawdown_sol, "f"),
                    'peak_capital_sol': format(metrics.peak_capital_sol, "f"),
                    'current_capital_sol': format(metrics.current_capital_sol, "f"),
                    'side': side,
                    'reason': reason
                }
                check.passthrough(f"Drawdown válido: {reason}", details)
            else:
                # Obtener métricas para detalles
                metrics = await drawdown_manager.get_drawdown_metrics()
                details = {
                    'drawdown_percent': format(metrics.drawdown_percent, "f"),
                    'drawdown_sol': format(metrics.drawdown_sol, "f"),
                    'peak_capital_sol': format(metrics.peak_capital_sol, "f"),
                    'current_capital_sol': format(metrics.current_capital_sol, "f"),
                    'side': side,
                    'reason': reason
                }
                check.fail(f"Drawdown excedido: {reason}", details)

        except Exception as e:
            check.fail(f"Error verificando drawdown: {str(e)}", {'error': str(e), 'side': side})

        return check
