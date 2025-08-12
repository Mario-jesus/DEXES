# -*- coding: utf-8 -*-
"""
Servicio especializado para optimización de posiciones de trading.
Separa la lógica de optimización de memoria y operaciones en lote.
"""
from typing import Dict, Any, List
from decimal import Decimal

from ..models import OpenPosition, ClosePosition, SubClosePosition, PositionStatus


class PositionOptimizationService:
    """
    Servicio especializado para optimización de posiciones de trading.
    Responsabilidad: Optimizar memoria y operaciones en lote.
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
    def get_memory_usage_estimate(cls, position: OpenPosition) -> int:
        """
        Estima el uso de memoria de una posición en bytes.
        
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
        Optimiza una posición para almacenamiento eliminando datos innecesarios.
        
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

    @classmethod
    def filter_positions_by_criteria(cls, positions: List[OpenPosition], 
                                    criteria: Dict[str, Any]) -> List[OpenPosition]:
        """
        Filtra posiciones por criterios específicos de forma eficiente.
        
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
    def batch_get_summary_stats(cls, positions: List[OpenPosition]) -> Dict[str, Any]:
        """
        Obtiene estadísticas resumidas de múltiples posiciones.
        
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
    def optimize_positions_batch(cls, positions: List[OpenPosition]) -> None:
        """
        Optimiza múltiples posiciones de forma eficiente.
        
        Args:
            positions: Lista de posiciones a optimizar
        """
        for position in positions:
            cls.optimize_position_for_storage(position)

    @classmethod
    def get_memory_usage_batch(cls, positions: List[OpenPosition]) -> Dict[str, int]:
        """
        Estima el uso de memoria de múltiples posiciones.
        
        Args:
            positions: Lista de posiciones
            
        Returns:
            Diccionario {position_id: memory_bytes}
        """
        memory_usage = {}
        for position in positions:
            memory_usage[position.id] = cls.get_memory_usage_estimate(position)
        return memory_usage

    @classmethod
    def get_total_memory_usage(cls, positions: List[OpenPosition]) -> int:
        """
        Calcula el uso total de memoria de una lista de posiciones.
        
        Args:
            positions: Lista de posiciones
            
        Returns:
            Total de bytes utilizados
        """
        total_memory = 0
        for position in positions:
            total_memory += cls.get_memory_usage_estimate(position)
        return total_memory
