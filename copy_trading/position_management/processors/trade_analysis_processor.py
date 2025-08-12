# -*- coding: utf-8 -*-
"""
Procesador de análisis de trades para Copy Trading.
Maneja toda la lógica de análisis de transacciones y extracción de datos.
"""
import asyncio
from typing import List, Dict, Any
from decimal import Decimal, InvalidOperation, DivisionByZero

from pumpfun import PumpFunTradeAnalyzer, TradeAnalysisResult
from logging_system import AppLogger
from ...data_management import TokenTraderManager
from ..models import Position


class TradeAnalysisProcessor:
    """
    Procesador responsable de manejar la lógica de análisis de trades.
    Separa la lógica de análisis de la gestión de colas.
    """

    def __init__(self, 
                    trader_analyzer: PumpFunTradeAnalyzer,
                    token_trader_manager: TokenTraderManager):
        self.trade_analyzer = trader_analyzer
        self.token_trader_manager = token_trader_manager
        self._logger = AppLogger(self.__class__.__name__)
        self._lock = asyncio.Lock()

        self._logger.debug("TradeAnalysisProcessor inicializado")

    async def analyze_positions(self, positions: List[Position]) -> bool:
        """
        Analiza una lista de posiciones.
        
        Args:
            positions: Lista de posiciones a analizar
            
        Returns:
            True si el análisis fue exitoso, False en caso contrario
        """
        if not positions:
            self._logger.debug("No hay posiciones para analizar")
            return True

        try:
            self._logger.info(f"Iniciando análisis de {len(positions)} posiciones")

            async with self._lock:
                result = await self._analyze_positions_internal(positions)

                if result:
                    self._logger.info(f"Análisis completado exitosamente para {len(positions)} posiciones")
                else:
                    self._logger.error("Error en el análisis de posiciones")

                return result
        except Exception as e:
            self._logger.error(f"Error analizando posiciones: {e}", exc_info=True)
            return False

    async def _analyze_positions_internal(self, positions: List[Position]) -> bool:
        """
        Lógica interna de análisis de posiciones.
        """
        try:
            # Obtener firmas de transacciones
            signatures = [position.execution_signature for position in positions if position.execution_signature]
            if not signatures:
                self._logger.warning("No se encontraron firmas de transacción válidas")
                return True

            self._logger.debug(f"Analizando {len(signatures)} transacciones")

            # Analizar transacciones
            analysis_results = await self.trade_analyzer.analyze_multiple_transactions(signatures)

            if not analysis_results:
                self._logger.warning(f"No se encontró análisis para las transacciones")
                return False

            self._logger.debug(f"Obtenidos {len(analysis_results)} resultados de análisis")

            # Procesar resultados para cada posición
            processed_count = 0
            for position in positions:
                if not position.execution_signature:
                    continue

                analysis_result = analysis_results.get(position.execution_signature)
                if not analysis_result:
                    self._logger.warning(f"No se encontró análisis para la posición {position.execution_signature}")
                    continue

                # Aplicar análisis a la posición
                await self._apply_analysis_to_position(position, analysis_result)
                processed_count += 1

            self._logger.info(f"Procesadas {processed_count} posiciones exitosamente")
            return True

        except Exception as e:
            signatures_str = ", ".join(s for s in signatures if s)
            self._logger.error(f"Error analizando transacciones {signatures_str}: {e}")
            return False

    async def _apply_analysis_to_position(self, position: Position, analysis_result: TradeAnalysisResult) -> None:
        """
        Aplica el resultado del análisis a una posición específica.
        
        Args:
            position: Posición a actualizar
            analysis_result: Resultado del análisis
        """
        try:
            self._logger.debug(f"Aplicando análisis a posición {position.id}")

            # Actualizar datos básicos de la posición
            position.amount_tokens = format(analysis_result.token_amount, "f")
            position.fee_sol = format(analysis_result.fee_in_sol, "f")
            position.total_cost_sol = format(analysis_result.sol_amount, "f")

            # Calcular precio de ejecución con validación para evitar división por cero
            try:
                amount_tokens_dec = Decimal(position.amount_tokens)
                amount_sol_dec = Decimal(position.amount_sol)

                if amount_tokens_dec > 0:
                    position.execution_price = format(amount_sol_dec / amount_tokens_dec, "f")
                else:
                    self._logger.warning(f"Posición {position.id}: amount_tokens es 0, no se puede calcular precio de ejecución")
            except (InvalidOperation, ValueError, DivisionByZero) as e:
                self._logger.warning(f"Error calculando precio de ejecución para posición {position.id}: {e}")

            # Obtener información fresca del token
            token_info = None
            if self.token_trader_manager:
                # Primero intentar obtener información del cache
                token_info = await self.token_trader_manager.get_token_info(position.token_address)

                # Si la información es genérica, forzar un refresh
                if token_info:
                    has_valid_name = token_info.name and token_info.name.strip() not in ('Unknown', '')
                    has_valid_symbol = token_info.symbol and token_info.symbol.strip() not in ('UNK', '')

                    if not has_valid_name or not has_valid_symbol:
                        self._logger.debug(f"Token info genérico detectado para {position.token_address}, forzando refresh")
                        token_info = await self.token_trader_manager.get_token_info(position.token_address, force_refresh=True)

            # Actualizar metadata con información del análisis
            position.add_metadata('cost_breakdown', {k: format(Decimal(str(v)), "f") for k, v in analysis_result.total_cost_breakdown.items()})
            position.add_metadata('compute_units_consumed', analysis_result.compute_units_consumed)
            position.add_metadata('trade_type', analysis_result.trade_type)
            position.add_metadata('operation_description', analysis_result.operation_description)
            position.add_metadata('token_program', analysis_result.token_program)
            position.add_metadata('slot', analysis_result.slot)
            position.add_metadata('block_time', analysis_result.block_time)
            position.add_metadata('recent_blockhash', analysis_result.recent_blockhash)
            position.add_metadata('token_balances_summary', self._extract_token_balances_summary(analysis_result))

            # Agregar información fresca del token
            if token_info:
                has_valid_name = token_info.name and token_info.name.strip() not in ('Unknown', '')
                has_valid_symbol = token_info.symbol and token_info.symbol.strip() not in ('UNK', '')
                if has_valid_name and has_valid_symbol:
                    position.add_metadata('token_info', token_info)
                    self._logger.debug(f"Token info agregado a posición {position.id}: {token_info.name} ({token_info.symbol})")
                else:
                    self._logger.debug(f"Token info no válido para posición {position.id}")
            else:
                self._logger.debug(f"No se pudo obtener token_info para {position.token_address}")

            # Marcar como analizada
            position.is_analyzed = True
            self._logger.debug(f"Posición {position.id} marcada como analizada")

        except Exception as e:
            self._logger.error(f"Error aplicando análisis a posición {position.id}: {e}")

    def _extract_token_balances_summary(self, analysis_result: TradeAnalysisResult) -> Dict[str, Any]:
        """
        Extrae un resumen de los balances de tokens del resultado del análisis.
        
        Args:
            analysis_result: Resultado del análisis de la transacción
            
        Returns:
            Diccionario con el resumen de balances
        """
        try:
            summary = {
                'trader_pre': {},
                'trader_post': {},
                'pool_pre': {},
                'pool_post': {}
            }

            # Extraer balance del trader antes de la transacción
            for balance in analysis_result.token_balances_pre:
                if str(balance.owner) == analysis_result.trader:
                    summary['trader_pre'] = {
                        'amount': format(Decimal(str(balance.ui_amount)), "f"),
                        'mint': str(balance.mint)
                    }
                    break

            # Extraer balance del trader después de la transacción
            for balance in analysis_result.token_balances_post:
                if str(balance.owner) == analysis_result.trader:
                    summary['trader_post'] = {
                        'amount': format(Decimal(str(balance.ui_amount)), "f"),
                        'mint': str(balance.mint)
                    }
                    break

            # Extraer balance del pool antes de la transacción
            for balance in analysis_result.token_balances_pre:
                if balance.account_index == 5:
                    summary['pool_pre'] = {
                        'amount': format(Decimal(str(balance.ui_amount)), "f"),
                        'mint': str(balance.mint)
                    }
                    break

            # Extraer balance del pool después de la transacción
            for balance in analysis_result.token_balances_post:
                if balance.account_index == 5:
                    summary['pool_post'] = {
                        'amount': format(Decimal(str(balance.ui_amount)), "f"),
                        'mint': str(balance.mint)
                    }
                    break

            return summary
        except Exception as e:
            self._logger.warning(f"Error extrayendo resumen de balances: {e}")
            return {}
