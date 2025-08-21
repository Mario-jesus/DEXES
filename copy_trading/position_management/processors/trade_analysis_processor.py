# -*- coding: utf-8 -*-
"""
Procesador de análisis de trades para Copy Trading.
Maneja toda la lógica de análisis de transacciones y extracción de datos.
"""
import asyncio
from decimal import Decimal
from typing import Union, cast, Tuple, Optional

from logging_system import AppLogger
from ...balance_management import BalanceManager
from ...data_management import TokenTraderManager, SolanaTxAnalyzer
from ...data_management.models import TransactionAnalysis
from ..models import Position, OpenPosition, ClosePosition


class TradeAnalysisProcessor:
    """
    Procesador responsable de manejar la lógica de análisis de trades.
    Separa la lógica de análisis de la gestión de colas.
    """

    def __init__(self, 
                    solana_analyzer: SolanaTxAnalyzer,
                    token_trader_manager: TokenTraderManager,
                    balance_manager: BalanceManager):
        self._logger = AppLogger(self.__class__.__name__)
        self._lock = asyncio.Lock()
        self.solana_analyzer = solana_analyzer
        self.token_trader_manager = token_trader_manager
        self.balance_manager = balance_manager
        self._logger.debug("TradeAnalysisProcessor inicializado")

    async def analyze_position(self, position: Position) -> Tuple[bool, Optional[TransactionAnalysis]]:
        """
        Analiza una posición de trading y retorna el resultado del análisis.

        Args:
            position (Position): La posición a analizar.

        Returns:
            Tuple[bool, Optional[TransactionAnalysis]]: 
                - Un booleano que indica si el análisis fue exitoso (True) o fallido (False).
                - Un objeto TransactionAnalysis con los detalles del análisis si fue exitoso, o None si no se pudo analizar.
        """
        if not position:
            self._logger.debug("No hay posiciones para analizar")
            return False, None

        try:
            self._logger.debug(f"Iniciando análisis de posición {position.id}")

            async with self._lock:
                result = await self._analyze_position_internal(position)

                if result:
                    self._logger.debug(f"Análisis completado exitosamente para posición {position.id}")
                else:
                    self._logger.error("Error en el análisis de posiciones")

                return result
        except Exception as e:
            self._logger.error(f"Error analizando posiciones: {e}", exc_info=True)
            return False, None

    async def _analyze_position_internal(self, position: Position) -> Tuple[bool, Optional[TransactionAnalysis]]:
        """
        Lógica interna de análisis de posiciones.
        """
        try:
            # Obtener firmas de transacciones
            signature = position.execution_signature
            if not signature:
                self._logger.warning("No se encontraron firmas de transacción válidas")
                return False, None

            self._logger.debug(f"Analizando transacción {signature}")

            # Analizar transacciones
            analysis_result = await self.solana_analyzer.analyze_transaction_by_signature(signature)

            if not analysis_result.success:
                self._logger.warning(f"No se encontró análisis para la transacción {signature}")
                return False, analysis_result

            # Aplicar análisis a la posición
            await self._apply_analysis_to_position(cast(Union[OpenPosition, ClosePosition], position), analysis_result)

            self._logger.info(f"Análisis completado exitosamente para la posición {position.id}")
            return True, analysis_result

        except Exception as e:
            self._logger.error(f"Error analizando posición {position.id}: {e}")
            return False, None

    async def _apply_analysis_to_position(self, position: Union[OpenPosition, ClosePosition], analysis_result: TransactionAnalysis) -> None:
        """
        Aplica el resultado del análisis a una posición específica.
        
        Args:
            position: Posición a actualizar
            analysis_result: Resultado del análisis
        """
        try:
            self._logger.debug(f"Aplicando análisis a posición {position.id}")

            # Actualizar datos básicos de la posición
            position.amount_tokens = format(abs(Decimal(analysis_result.token_ui_delta or "0.0")), "f")
            position.amount_sol = format(abs(Decimal(analysis_result.bonding_curve_sol_delta or "0.0")), "f")
            position.fee_sol = analysis_result.fee_sol or "0.0"
            position.total_cost_sol = analysis_result.total_cost_sol or "0.0"
            position.execution_price = analysis_result.price_sol_per_token or "0.0"

            # Agregar resultado del análisis a la posición
            position.add_metadata("analysis_result", analysis_result)

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

            # Actualizar balances locales por apertura o cierre de posición
            try:
                if self.balance_manager and isinstance(position, OpenPosition) and analysis_result.success:
                    await self.balance_manager.on_position_opened(analysis_result.signer_sol_delta or "0.0")
                    await self.balance_manager.on_token_received(position.token_address, analysis_result.token_ui_delta or "0.0")
                elif self.balance_manager and isinstance(position, ClosePosition) and analysis_result.success:
                    await self.balance_manager.on_position_closed(analysis_result.signer_sol_delta or "0.0")
                    await self.balance_manager.on_token_spent(position.token_address, analysis_result.token_ui_delta or "0.0")
            except Exception as e:
                self._logger.error(f"Error actualizando balances locales: {e}")

        except Exception as e:
            self._logger.error(f"Error aplicando análisis a posición {position.id}: {e}")
