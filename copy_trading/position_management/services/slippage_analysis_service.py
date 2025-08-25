# -*- coding: utf-8 -*-
"""
Servicio especializado para análisis de slippage de posiciones de trading.
Separa la lógica de análisis de slippage de otros cálculos.
"""
from typing import Dict, Optional, Any, List
from decimal import Decimal, getcontext

from ..models import OpenPosition, ClosePosition, SubClosePosition

# Configurar precisión de Decimal para operaciones financieras
getcontext().prec = 26


class SlippageAnalysisService:
    """
    Servicio especializado para análisis de slippage de posiciones de trading.
    Responsabilidad: Analizar diferencias entre precios esperados y ejecutados.
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
    def calculate_execution_slippage(cls, position: OpenPosition) -> str:
        """
        Calcula el slippage de la ejecución inicial.
        
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
    def _calculate_close_slippage(cls, close_data: ClosePosition, expected_price: str) -> str:
        """
        Calcula el slippage de un cierre específico.
        
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
        Calcula slippage del cierre vs precio de entrada original.
        
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
        Calcula slippage del cierre vs precio del trader original.
        
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
        Calcula slippage del cierre vs precio de mercado.
        
        Args:
            close_data: Datos del cierre
            market_price: Precio de mercado en el momento del cierre
            
        Returns:
            Slippage como porcentaje en string
        """
        return cls._calculate_close_slippage(close_data, market_price)

    @classmethod
    def calculate_total_slippage_impact(cls, position: OpenPosition, sol_price_usd: str = "150.0") -> Dict[str, str]:
        """
        Calcula el impacto total del slippage en la posición.
        
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
            expected_value = Decimal(position.amount_sol_executed)
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
                if close_data.execution_price and close_data.amount_sol_executed:
                    # Calcular slippage vs precio de entrada
                    close_slippage_pct = cls._calculate_close_slippage_vs_entry(position, close_data)
                    if close_slippage_pct != "0.0":
                        total_slippage_pct += Decimal(close_slippage_pct)
                        close_count += 1

                        # Valor del slippage de este cierre
                        close_amount = Decimal(close_data.amount_sol_executed)
                        slippage_impact = close_amount * (Decimal(close_slippage_pct) / 100)
                        total_slippage_value_sol += slippage_impact

            if close_count > 0:
                avg_slippage_pct = total_slippage_pct / close_count
                results['total_close_slippage_percentage'] = format(avg_slippage_pct, "f")
                results['total_close_slippage_value_sol'] = format(total_slippage_value_sol, "f")
                results['total_close_slippage_value_usd'] = format(total_slippage_value_sol * Decimal(sol_price_usd), "f")

        return results

    @classmethod
    def get_close_slippage_analysis(cls, position: OpenPosition, close_data: ClosePosition, 
                                    trader_price: Optional[str] = None,
                                    market_price: Optional[str] = None) -> Dict[str, str]:
        """
        Análisis completo de slippage para un cierre.
        
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
        Análisis completo de slippage para todos los cierres.
        
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
                'close_amount_sol': close_data.amount_sol_executed,
                'close_amount_tokens': close_data.amount_tokens_executed,
                'close_entry_price': close_data.entry_price,
                'close_execution_price': close_data.execution_price,
                'slippage_analysis': slippage_analysis
            }

            analysis_list.append(close_analysis)

        return analysis_list
