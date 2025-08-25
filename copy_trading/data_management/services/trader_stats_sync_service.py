# -*- coding: utf-8 -*-
"""
Servicio para sincronización entre TraderStats y TraderTokenStats.
"""
from typing import Tuple, List, Literal, TypedDict, NotRequired, Optional
from decimal import Decimal
import logging

from ..models import TraderStats, TraderTokenStats

logger = logging.getLogger(__name__)

class SyncOperation(TypedDict):
    previous_volume_sol: NotRequired[str]
    volume_sol_open: NotRequired[str]
    volume_sol_closed: NotRequired[str]
    volume_sol_failed: NotRequired[str]
    pnl_sol: NotRequired[str]
    pnl_sol_with_costs: NotRequired[str]
    timestamp: NotRequired[Optional[str]]


class TraderStatsSyncService:
    """
    Servicio dedicado para sincronizar estadísticas entre modelos.
    Mantiene la lógica de sincronización separada de los modelos de datos.
    """

    @staticmethod
    def sync_models(trader_stats: TraderStats, trader_token_stats: TraderTokenStats, 
                    operation: Literal['open_position', 'closed_position', 'update_open_position', 'update_closed_position', 'failed_position', 'pnl'], sync_operation: SyncOperation) -> Tuple[TraderStats, TraderTokenStats]:
        """
        Actualiza simultáneamente TraderStats y TraderTokenStats sin iteraciones innecesarias.
        
        Args:
            trader_stats: Instancia de TraderStats a actualizar
            trader_token_stats: Instancia de TraderTokenStats a actualizar
            operation: Tipo de operación ('open_position', 'closed_position', 'update_open_position', 'update_closed_position', 'failed_position', 'pnl')
            **kwargs: Parámetros adicionales (volume_sol, pnl_sol, pnl_sol_with_costs, timestamp)
            
        Returns:
            Tuple con (TraderStats actualizado, TraderTokenStats actualizado)
        """
        # Crear copias para evitar modificar las instancias originales
        updated_trader_stats = TraderStats(
            nickname=trader_stats.nickname,
            open_positions=trader_stats.open_positions,
            closed_positions=trader_stats.closed_positions,
            total_volume_sol_open=trader_stats.total_volume_sol_open,
            total_volume_sol_closed=trader_stats.total_volume_sol_closed,
            total_pnl_sol=trader_stats.total_pnl_sol,
            total_pnl_sol_with_costs=trader_stats.total_pnl_sol_with_costs
        )

        updated_trader_token_stats = TraderTokenStats(
            trader_wallet=trader_token_stats.trader_wallet,
            token_address=trader_token_stats.token_address,
            token_symbol=trader_token_stats.token_symbol,
            open_positions=trader_token_stats.open_positions,
            closed_positions=trader_token_stats.closed_positions,
            total_volume_sol_open=trader_token_stats.total_volume_sol_open,
            total_volume_sol_closed=trader_token_stats.total_volume_sol_closed,
            total_pnl_sol=trader_token_stats.total_pnl_sol,
            total_pnl_sol_with_costs=trader_token_stats.total_pnl_sol_with_costs,
            last_trade_timestamp=trader_token_stats.last_trade_timestamp
        )

        if operation == 'open_position':
            volume_sol_open = sync_operation.get('volume_sol_open', '0')
            timestamp = sync_operation.get('timestamp')

            # Actualizar TraderTokenStats
            updated_trader_token_stats.register_open_position(volume_sol_open, timestamp)

            # Actualizar TraderStats
            updated_trader_stats.register_open_position(volume_sol_open)

        elif operation == 'closed_position':
            volume_sol_closed = sync_operation.get('volume_sol_closed', '0')
            timestamp = sync_operation.get('timestamp')

            # Actualizar TraderTokenStats
            updated_trader_token_stats.register_closed_position(volume_sol_closed, timestamp)

            # Actualizar TraderStats
            updated_trader_stats.register_closed_position(volume_sol_closed)

        elif operation == 'update_open_position':
            previous_volume_sol = sync_operation.get('previous_volume_sol', '0')
            volume_sol_open = sync_operation.get('volume_sol_open', '0')
            timestamp = sync_operation.get('timestamp')

            # Actualizar TraderTokenStats
            updated_trader_token_stats.update_open_position(previous_volume_sol, volume_sol_open, timestamp)

            # Actualizar TraderStats
            updated_trader_stats.update_open_position(previous_volume_sol, volume_sol_open)

        elif operation == 'update_closed_position':
            previous_volume_sol = sync_operation.get('previous_volume_sol', '0')
            volume_sol_closed = sync_operation.get('volume_sol_closed', '0')
            timestamp = sync_operation.get('timestamp')

            # Actualizar TraderTokenStats
            updated_trader_token_stats.update_closed_position(previous_volume_sol, volume_sol_closed, timestamp)
            
            # Actualizar TraderStats
            updated_trader_stats.update_closed_position(previous_volume_sol, volume_sol_closed)

        elif operation == 'failed_position':
            volume_sol_failed = sync_operation.get('volume_sol_failed', '0')
            timestamp = sync_operation.get('timestamp')

            # Actualizar TraderTokenStats
            updated_trader_token_stats.register_failed_position(volume_sol_failed, timestamp)

            # Actualizar TraderStats
            updated_trader_stats.register_failed_position(volume_sol_failed)

        elif operation == 'pnl':
            pnl_sol = sync_operation.get('pnl_sol', '0')
            pnl_sol_with_costs = sync_operation.get('pnl_sol_with_costs', '0')

            # Actualizar ambos modelos
            updated_trader_token_stats.register_pnl(pnl_sol, pnl_sol_with_costs)
            updated_trader_stats.register_pnl(pnl_sol, pnl_sol_with_costs)

        logger.debug(f"Modelos sincronizados para operación: {operation}")
        return updated_trader_stats, updated_trader_token_stats

    @staticmethod
    def create_trader_stats_from_token_stats(trader_token_stats: TraderTokenStats, 
                                                trader_name: str = "UNKNOWN") -> TraderStats:
        """
        Crea TraderStats desde un TraderTokenStats específico.
        
        Args:
            trader_token_stats: Estadísticas del trader para un token específico
            trader_name: Nombre del trader (opcional)
            
        Returns:
            TraderStats con los datos del TraderTokenStats
        """
        return TraderStats(
            nickname=trader_name,
            open_positions=trader_token_stats.open_positions,
            closed_positions=trader_token_stats.closed_positions,
            total_volume_sol_open=trader_token_stats.total_volume_sol_open,
            total_volume_sol_closed=trader_token_stats.total_volume_sol_closed,
            total_pnl_sol=trader_token_stats.total_pnl_sol,
            total_pnl_sol_with_costs=trader_token_stats.total_pnl_sol_with_costs
        )

    @staticmethod
    def aggregate_trader_stats_from_token_stats(trader_token_stats_list: List[TraderTokenStats], 
                                                    trader_name: str = "UNKNOWN") -> TraderStats:
        """
        Crea TraderStats agregando múltiples TraderTokenStats.
        
        Args:
            trader_token_stats_list: Lista de estadísticas del trader por token
            trader_name: Nombre del trader (opcional)
            
        Returns:
            TraderStats con datos agregados de todos los tokens
        """
        if not trader_token_stats_list:
            return TraderStats(nickname=trader_name)

        # Agregar todos los valores
        total_open_positions = sum(stats.open_positions for stats in trader_token_stats_list)
        total_closed_positions = sum(stats.closed_positions for stats in trader_token_stats_list)

        total_volume_sol_open = sum(Decimal(stats.total_volume_sol_open) for stats in trader_token_stats_list)
        total_volume_sol_closed = sum(Decimal(stats.total_volume_sol_closed) for stats in trader_token_stats_list)
        total_pnl = sum(Decimal(stats.total_pnl_sol) for stats in trader_token_stats_list)
        total_pnl_with_costs = sum(Decimal(stats.total_pnl_sol_with_costs) for stats in trader_token_stats_list)

        return TraderStats(
            nickname=trader_name,
            open_positions=total_open_positions,
            closed_positions=total_closed_positions,
            total_volume_sol_open=format(total_volume_sol_open, "f"),
            total_volume_sol_closed=format(total_volume_sol_closed, "f"),
            total_pnl_sol=format(total_pnl, "f"),
            total_pnl_sol_with_costs=format(total_pnl_with_costs, "f")
        )

    @staticmethod
    def update_trader_stats_from_token_stats(trader_stats: TraderStats, 
                                                trader_token_stats: TraderTokenStats) -> TraderStats:
        """
        Actualiza las estadísticas agregando los datos de un TraderTokenStats.
        
        Args:
            trader_stats: Estadísticas del trader a actualizar
            trader_token_stats: Estadísticas del trader para un token específico
            
        Returns:
            TraderStats actualizado
        """
        updated_stats = TraderStats(
            nickname=trader_stats.nickname,
            open_positions=trader_stats.open_positions + trader_token_stats.open_positions,
            closed_positions=trader_stats.closed_positions + trader_token_stats.closed_positions,
            total_volume_sol_open=format(Decimal(trader_stats.total_volume_sol_open) + Decimal(trader_token_stats.total_volume_sol_open), "f"),
            total_volume_sol_closed=format(Decimal(trader_stats.total_volume_sol_closed) + Decimal(trader_token_stats.total_volume_sol_closed), "f"),
            total_pnl_sol=format(Decimal(trader_stats.total_pnl_sol) + Decimal(trader_token_stats.total_pnl_sol), "f"),
            total_pnl_sol_with_costs=format(Decimal(trader_stats.total_pnl_sol_with_costs) + Decimal(trader_token_stats.total_pnl_sol_with_costs), "f")
        )

        logger.debug(f"TraderStats actualizado desde TraderTokenStats")
        return updated_stats
