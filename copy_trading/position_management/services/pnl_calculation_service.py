# -*- coding: utf-8 -*-
"""
Servicio especializado para cálculos de P&L (Profit & Loss) de posiciones de trading.
Separa la lógica de cálculos financieros de otros análisis.
"""
from typing import Dict, Any, Tuple, List, Union
from decimal import Decimal, getcontext

from logging_system import AppLogger
from ..models import OpenPosition, ClosePosition, PositionStatus, SubClosePosition

# Configurar precisión de Decimal para operaciones financieras
getcontext().prec = 26

_logger = AppLogger("PnLCalculationService")


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
    def _normalize_cost(cls, cost: Decimal, context: str) -> Decimal:
        """Normaliza costos para que siempre sean positivos.
        Si se detecta un costo negativo (por datos mal signados), se vuelve positivo y se loggea.
        """
        if cost < 0:
            _logger.warning(f"Se detectó costo negativo {cost} en {context}. Normalizando a valor absoluto.")
            return -cost
        return cost

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

        _logger.debug(f"Cálculo P&L básico: amount={amount}, cost_basis={cost_basis}, pnl_sol={pnl_sol}, pnl_usd={pnl_usd}")

        return pnl_sol, pnl_usd

    @classmethod
    def calculate_pnl(cls, position: OpenPosition, sol_price_usd: str, include_transaction_costs: bool = False) -> Tuple[str, str]:
        """
        Calcula P&L actual basado en el estado de la posición.
        
        Args:
            position: Objeto OpenPosition
            sol_price_usd: Precio de SOL en USD
            include_transaction_costs: Si incluir costos de transacción en el cálculo
            
        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        if position.status not in [PositionStatus.OPEN, PositionStatus.CLOSED, PositionStatus.PARTIALLY_CLOSED]:
            return "0.0", "0.0"

        if position.status == PositionStatus.OPEN:
            if not position.amount_sol_executed or Decimal(position.amount_sol_executed) == 0:
                return "0.0", "0.0"

            current_value = Decimal(position.amount_sol_executed) if position.amount_sol_executed else Decimal('0')
            cost_basis = Decimal(position.total_cost_sol) if position.total_cost_sol and include_transaction_costs else Decimal('0')
            if include_transaction_costs and cost_basis < 0:
                _logger.warning(f"Costo negativo detectado en posición abierta {position.id}: {cost_basis}. Normalizando.")
                cost_basis = -cost_basis
            pnl_sol, pnl_usd = cls._calculate_pnl_from_amounts(current_value, cost_basis, Decimal(sol_price_usd))

            return format(pnl_sol, "f"), format(pnl_usd, "f")

        elif position.status in [PositionStatus.CLOSED, PositionStatus.PARTIALLY_CLOSED]:
            # Para posiciones cerradas o parcialmente cerradas, usar el P&L realizado
            return cls.calculate_realized_pnl(position, sol_price_usd, include_transaction_costs)

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
        _logger.debug(f"Calculando P&L realizado para posición {position.id}, incluir_costos={include_transaction_costs}")

        if not position.close_history:
            _logger.debug(f"Posición {position.id} no tiene historial de cierres, retornando 0.0")
            return "0.0", "0.0"

        # Valor de entrada (cuánto valían los tokens cuando se compraron)
        entry_value = Decimal(position.amount_sol_executed) if position.amount_sol_executed else Decimal('0')
        _logger.debug(f"Valor de entrada: {entry_value} SOL")

        # Valor total de salida (cuánto se recibió por los tokens)
        total_exit_value = Decimal('0')
        total_exit_costs = Decimal(position.total_cost_sol) if position.total_cost_sol else Decimal('0')
        if total_exit_costs < 0:
            _logger.warning(f"Costo inicial de entrada negativo en posición {position.id}: {total_exit_costs}. Normalizando.")
            total_exit_costs = -total_exit_costs
        _logger.debug(f"Costos iniciales de entrada: {total_exit_costs} SOL")

        _logger.debug(f"Procesando {len(position.close_history)} cierres en el historial")

        for i, close_item in enumerate(position.close_history):
            # Calcular valor de salida para este cierre
            close_amount = Decimal(close_item.amount_sol_executed) if close_item.amount_sol_executed else Decimal('0')
            close_cost = Decimal(close_item.total_cost_sol) if close_item.total_cost_sol else Decimal('0')
            if close_cost < 0:
                _logger.warning(f"Costo de cierre negativo en posición {position.id} (cierre {i+1}): {close_cost}. Normalizando.")
                close_cost = -close_cost

            total_exit_value += close_amount
            total_exit_costs += close_cost

            _logger.debug(f"Cierre {i+1}: amount={close_amount}, cost={close_cost}, total_exit={total_exit_value}, total_costs={total_exit_costs}")

        # Calcular P&L base (sin costos)
        pnl_sol_base = total_exit_value - entry_value
        _logger.debug(f"P&L base (sin costos): {pnl_sol_base} SOL")

        # Si se incluyen costos de transacción, restar fees
        if include_transaction_costs:
            pnl_sol = pnl_sol_base - total_exit_costs
            _logger.debug(f"P&L con costos: {pnl_sol} SOL (restados {total_exit_costs} SOL de costos)")
        else:
            pnl_sol = pnl_sol_base
            _logger.debug(f"P&L sin costos: {pnl_sol} SOL")

        # Convertir a USD
        pnl_usd = pnl_sol * Decimal(sol_price_usd)
        _logger.debug(f"P&L final: {pnl_sol} SOL = {pnl_usd} USD (precio SOL: {sol_price_usd})")

        return format(pnl_sol, "f"), format(pnl_usd, "f")

    @classmethod
    def calculate_realized_pnl_for_partial_close(cls, sub_close_position: Union[SubClosePosition, ClosePosition], sol_price_usd: str, include_transaction_costs: bool = False) -> Tuple[str, str]:
        """
        Calcula el P&L realizado para un cierre parcial.
        
        Args:
            sub_close_position: Objeto SubClosePosition
            sol_price_usd: Precio de SOL en USD
            include_transaction_costs: Si incluir costos de transacción en el cálculo

        Returns:
            Tuple de (pnl_sol, pnl_usd) como strings
        """
        try:
            _logger.debug(f"Calculando P&L realizado para cierre parcial {sub_close_position.id}, incluir_costos={include_transaction_costs}")

            open_position_proportional_amount_sol_executed = sub_close_position.get_metadata("open_position_proportional_amount_sol_executed")
            open_position_proportional_total_cost_sol = sub_close_position.get_metadata("open_position_proportional_total_cost_sol")

            entry_value = Decimal(open_position_proportional_amount_sol_executed or '0')
            total_exit_value = Decimal(sub_close_position.amount_sol_executed or '0')
            close_cost = abs(Decimal(sub_close_position.total_cost_sol or '0'))
            _logger.debug(f"Costos de cierre: {close_cost}")

            pnl_sol_base = total_exit_value - entry_value
            _logger.debug(f"P&L base (sin costos): {pnl_sol_base} SOL")

            total_exit_costs = close_cost + abs(Decimal(open_position_proportional_total_cost_sol or '0'))

            if include_transaction_costs:
                pnl_sol = pnl_sol_base - total_exit_costs
                _logger.debug(f"P&L con costos: {pnl_sol} SOL (restados {total_exit_costs} SOL de costos)")
            else:
                pnl_sol = pnl_sol_base
                _logger.debug(f"P&L sin costos: {pnl_sol} SOL")

            pnl_usd = pnl_sol * Decimal(sol_price_usd or '0')
            _logger.debug(f"P&L final: {pnl_sol} SOL = {pnl_usd} USD (precio SOL: {sol_price_usd})")

            return format(pnl_sol, "f"), format(pnl_usd, "f")
        except Exception as e:
            _logger.error(f"Error al calcular P&L para cierre parcial {sub_close_position.id}: {e}")
            return "0.0", "0.0"

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
        _logger.info(f"Iniciando cálculo de P&L con desglose de costos para posición {position.id}")

        # Calcular P&L sin costos de transacción
        _logger.debug("Calculando P&L sin costos de transacción")
        pnl_sol_without_costs, pnl_usd_without_costs = cls.calculate_realized_pnl(position, sol_price_usd, include_transaction_costs=False)

        # Calcular P&L con costos de transacción
        _logger.debug("Calculando P&L con costos de transacción")
        pnl_sol_with_costs, pnl_usd_with_costs = cls.calculate_realized_pnl(position, sol_price_usd, include_transaction_costs=True)

        _logger.info(f"P&L calculado para posición {position.id}: sin_costos={pnl_sol_without_costs} SOL, con_costos={pnl_sol_with_costs} SOL")

        return pnl_sol_without_costs, pnl_usd_without_costs, pnl_sol_with_costs, pnl_usd_with_costs

    @classmethod
    def calculate_realized_pnl_for_partial_close_with_costs_breakdown(cls, sub_close_position: Union[SubClosePosition, ClosePosition], sol_price_usd: str) -> Tuple[str, str, str, str]:
        """
        Calcula el P&L realizado para un cierre parcial tanto con costos de transacción como sin ellos.
        
        Args:
            sub_close_position: Objeto SubClosePosition
            sol_price_usd: Precio de SOL en USD
        """
        _logger.info(f"Iniciando cálculo de P&L con desglose de costos para cierre parcial {sub_close_position.id}")

        # Calcular P&L sin costos de transacción
        _logger.debug("Calculando P&L sin costos de transacción")
        pnl_sol_without_costs, pnl_usd_without_costs = cls.calculate_realized_pnl_for_partial_close(sub_close_position, sol_price_usd, include_transaction_costs=False)

        # Calcular P&L con costos de transacción
        _logger.debug("Calculando P&L con costos de transacción")
        pnl_sol_with_costs, pnl_usd_with_costs = cls.calculate_realized_pnl_for_partial_close(sub_close_position, sol_price_usd, include_transaction_costs=True)

        _logger.info(f"P&L calculado para cierre parcial {sub_close_position.id}: sin_costos={pnl_sol_without_costs} SOL, con_costos={pnl_sol_with_costs} SOL")

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
        close_id = getattr(close_item, 'id', 'unknown')
        if isinstance(close_item, SubClosePosition):
            close_id = getattr(close_item.close_position, 'id', 'unknown')

        _logger.debug(f"Calculando P&L individual para cierre {close_id} de posición {position.id}, incluir_costos={include_transaction_costs}")
        # Obtener los datos reales del cierre
        if isinstance(close_item, SubClosePosition):
            # Para SubClosePosition, usar los datos del subcierre
            close_amount_sol = Decimal(close_item.amount_sol_executed) if close_item.amount_sol_executed else Decimal('0')
            close_amount_tokens = Decimal(close_item.amount_tokens_executed) if close_item.amount_tokens_executed else Decimal('0')
            _logger.debug(f"SubClosePosition: amount_sol={close_amount_sol}, amount_tokens={close_amount_tokens}")
        else:
            # Para ClosePosition, usar los datos del cierre
            close_amount_sol = Decimal(close_item.amount_sol_executed) if close_item.amount_sol_executed else Decimal('0')
            close_amount_tokens = Decimal(close_item.amount_tokens_executed) if close_item.amount_tokens_executed else Decimal('0')
            _logger.debug(f"ClosePosition: amount_sol={close_amount_sol}, amount_tokens={close_amount_tokens}")

        if close_amount_sol == 0:
            _logger.debug(f"Cierre {close_id} tiene amount_sol=0, retornando P&L=0")
            return "0.0", "0.0"

        # Calcular el costo proporcional basado en los tokens cerrados
        total_original_tokens = Decimal(position.amount_tokens_executed) if position.amount_tokens_executed else Decimal('0')
        if total_original_tokens == 0:
            _logger.debug(f"Posición {position.id} tiene total_original_tokens=0, retornando P&L=0")
            return "0.0", "0.0"

        # Calcular la proporción de tokens cerrados
        open_position_total_cost = Decimal(position.total_cost_sol) if position.total_cost_sol else Decimal('0')
        close_position_total_cost = Decimal(close_item.total_cost_sol) if close_item.total_cost_sol else Decimal('0')
        if open_position_total_cost < 0:
            _logger.warning(f"Costo de apertura negativo en posición {position.id}: {open_position_total_cost}. Normalizando.")
            open_position_total_cost = -open_position_total_cost
        if close_position_total_cost < 0:
            _logger.warning(f"Costo de cierre negativo en posición {position.id} (cierre {close_id}): {close_position_total_cost}. Normalizando.")
            close_position_total_cost = -close_position_total_cost
        total_cost = open_position_total_cost + close_position_total_cost

        proportion = close_amount_tokens / total_original_tokens
        proportional_cost = total_cost * proportion if include_transaction_costs else Decimal('0')

        _logger.debug(f"Proporción de tokens: {proportion} ({close_amount_tokens}/{total_original_tokens})")
        _logger.debug(f"Costos: open={open_position_total_cost}, close={close_position_total_cost}, total={total_cost}, proporcional={proportional_cost}")

        # Calcular P&L del cierre individual
        pnl_sol, pnl_usd = cls._calculate_pnl_from_amounts(close_amount_sol, proportional_cost, Decimal(sol_price_usd))

        _logger.debug(f"P&L individual calculado para cierre {close_id}: {pnl_sol} SOL = {pnl_usd} USD")

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
        _logger.debug(f"Calculando P&L acumulado para posición {position.id} hasta índice {up_to_close_index}, incluir_costos={include_transaction_costs}")

        if not position.close_history:
            _logger.debug(f"Posición {position.id} no tiene historial de cierres, retornando 0.0")
            return "0.0", "0.0"

        # Normalizar el índice
        if up_to_close_index < 0:
            up_to_close_index = len(position.close_history) + up_to_close_index

        if up_to_close_index >= len(position.close_history):
            up_to_close_index = len(position.close_history) - 1

        _logger.debug(f"Índice normalizado: {up_to_close_index} (total cierres: {len(position.close_history)})")

        # Calcular P&L acumulado hasta ese cierre
        total_pnl_sol = Decimal('0')

        for i in range(up_to_close_index + 1):
            close_item = position.close_history[i]
            close_id = getattr(close_item, 'id', f'close_{i}')
            if isinstance(close_item, SubClosePosition):
                close_id = getattr(close_item.close_position, 'id', f'subclose_{i}')

            individual_pnl_sol, _ = cls.calculate_individual_close_pnl(position, close_item, sol_price_usd, include_transaction_costs)
            total_pnl_sol += Decimal(individual_pnl_sol)

            _logger.debug(f"Acumulando cierre {i+1}/{up_to_close_index+1} ({close_id}): individual={individual_pnl_sol}, total={total_pnl_sol}")

        total_pnl_usd = total_pnl_sol * Decimal(sol_price_usd)

        _logger.debug(f"P&L acumulado final para posición {position.id}: {total_pnl_sol} SOL = {total_pnl_usd} USD")

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
                close_amount_sol = close_item.amount_sol_executed
                close_amount_tokens = close_item.amount_tokens_executed
                close_type = "partial"
            else:
                close_data = close_item
                close_amount_sol = close_item.amount_sol_executed
                close_amount_tokens = close_item.amount_tokens_executed
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
                            sol_price_usd: str,
                            include_transaction_costs: bool = False) -> Dict[str, Tuple[str, str]]:
        """
        Calcula P&L para múltiples posiciones de forma eficiente.
        
        Args:
            positions: Lista de posiciones
            sol_price_usd: Precio de SOL en USD
            
        Returns:
            Diccionario {position_id: (pnl_sol, pnl_usd)}
        """
        results = {}
        for position in positions:
            pnl_sol, pnl_usd = cls.calculate_pnl(position, sol_price_usd, include_transaction_costs=include_transaction_costs)
            results[position.id] = (pnl_sol, pnl_usd)

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
                close_amount_sol = close_item.amount_sol_executed
                close_amount_tokens = close_item.amount_tokens_executed
                close_type = "partial"
            else:
                close_data = close_item
                close_amount_sol = close_item.amount_sol_executed
                close_amount_tokens = close_item.amount_tokens_executed
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
                if close_item.amount_sol_executed:
                    total_sol += Decimal(close_item.amount_sol_executed)
                if close_item.amount_tokens_executed:
                    total_tokens += Decimal(close_item.amount_tokens_executed)
            else:
                if close_item.amount_sol_executed:
                    total_sol += Decimal(close_item.amount_sol_executed)
                if close_item.amount_tokens_executed:
                    total_tokens += Decimal(close_item.amount_tokens_executed)

        return format(total_sol, "f"), format(total_tokens, "f")
