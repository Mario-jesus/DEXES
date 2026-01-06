# -*- coding: utf-8 -*-
"""
Servicio de dominio: Validador de transacciones para backtest.

Orquesta múltiples validaciones y las ejecuta según operadores lógicos.
"""
import logging
from typing import Dict, List, Optional, Any, Tuple

from ..entities.transactions import SwapTransaction
from ..validations.models import ValidationResult, BaseValidation, ValidationItem


class BacktestValidator:
    """Validador de transacciones para backtest con validaciones configurables"""

    def __init__(self, validations: Optional[List[ValidationItem]] = None):
        """
        Inicializa el validador.
        
        Args:
            validations: Lista opcional que puede contener:
                - Objetos BaseValidation directamente
                - Diccionarios con estructura:
                    {
                        "validations": [BaseValidation o estructuras anidadas],
                        "logical_operator": "AND" | "OR"
                    }
        """
        self.validations: List[ValidationItem] = []
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        if validations:
            self.validations = validations
            self._logger.debug(f"Validador inicializado con {len(validations)} elementos de validación")

    def add_validation(self, validation: ValidationItem) -> None:
        """
        Agrega una validación o grupo de validaciones al validador.
        
        Args:
            validation: Puede ser BaseValidation o un dict con grupo de validaciones
        """
        self.validations.append(validation)
        if isinstance(validation, BaseValidation):
            self._logger.debug(f"Validación agregada: {validation.name} (enabled={validation.enabled})")
        else:
            self._logger.debug(f"Grupo de validaciones agregado")

    def _remove_from_item(self, item: ValidationItem, validation_name: str) -> Tuple[bool, Optional[ValidationItem]]:
        """Helper recursivo para remover validación de un item o grupo"""
        if isinstance(item, BaseValidation):
            if item.name == validation_name:
                return True, None
            return False, item
        elif isinstance(item, dict) and "validations" in item:
            new_validations = []
            removed = False
            for sub_item in item["validations"]:
                was_removed, updated_item = self._remove_from_item(sub_item, validation_name)
                if was_removed:
                    removed = True
                elif updated_item is not None:
                    new_validations.append(updated_item)

            if removed:
                if new_validations:
                    return True, {"validations": new_validations, "logical_operator": item.get("logical_operator", "AND")}
                else:
                    return True, None  # Grupo vacío, remover todo
            return False, item
        return False, item

    def remove_validation(self, validation_name: str) -> bool:
        """
        Remueve una validación por nombre (busca en grupos anidados).
        
        Args:
            validation_name: Nombre de la validación a remover
        
        Returns:
            True si se removió, False si no se encontró
        """
        new_validations = []
        removed = False
        for item in self.validations:
            was_removed, updated_item = self._remove_from_item(item, validation_name)
            if was_removed:
                removed = True
            if updated_item is not None:
                new_validations.append(updated_item)

        if removed:
            self.validations = new_validations
            self._logger.debug(f"Validación removida: {validation_name}")
        return removed

    def _find_validation_in_item(self, item: ValidationItem, validation_name: str) -> Optional[BaseValidation]:
        """Helper recursivo para encontrar validación en item o grupo"""
        if isinstance(item, BaseValidation):
            if item.name == validation_name:
                return item
        elif isinstance(item, dict) and "validations" in item:
            for sub_item in item["validations"]:
                found = self._find_validation_in_item(sub_item, validation_name)
                if found:
                    return found
        return None

    def enable_validation(self, validation_name: str) -> bool:
        """
        Habilita una validación por nombre (busca en grupos anidados).
        
        Args:
            validation_name: Nombre de la validación
        
        Returns:
            True si se habilitó, False si no se encontró
        """
        for item in self.validations:
            validation = self._find_validation_in_item(item, validation_name)
            if validation:
                validation.enabled = True
                self._logger.debug(f"Validación habilitada: {validation_name}")
                return True
        return False

    def disable_validation(self, validation_name: str) -> bool:
        """
        Deshabilita una validación por nombre (busca en grupos anidados).
        
        Args:
            validation_name: Nombre de la validación
        
        Returns:
            True si se deshabilitó, False si no se encontró
        """
        for item in self.validations:
            validation = self._find_validation_in_item(item, validation_name)
            if validation:
                validation.enabled = False
                self._logger.debug(f"Validación deshabilitada: {validation_name}")
                return True
        return False

    def _evaluate_validation_item(self, item: ValidationItem, transaction: SwapTransaction, 
                                    context: Dict[str, Any]) -> Tuple[Optional[bool], List[ValidationResult]]:
        """
        Evalúa recursivamente un item de validación (puede ser BaseValidation o un grupo).
        
        Args:
            item: Puede ser BaseValidation o un dict con grupo de validaciones
            transaction: SwapTransaction a validar
            context: Contexto compartido
        
        Returns:
            Tupla (is_valid, results) donde:
            - is_valid: True si la validación/grupo pasa, False si falla, None si está deshabilitada
            - results: Lista de resultados de todas las validaciones evaluadas
        """
        # Si es un diccionario, es un grupo de validaciones
        if isinstance(item, dict):
            if "validations" not in item or "logical_operator" not in item:
                self._logger.warning(f"Grupo de validación inválido: {item}")
                return True, []  # Si está mal formado, se acepta por defecto

            validations_list = item["validations"]
            operator = item["logical_operator"].upper()

            if operator not in ["AND", "OR"]:
                self._logger.warning(f"Operador lógico inválido: {operator}, usando AND por defecto")
                operator = "AND"

            all_results: List[ValidationResult] = []
            all_valid: List[bool] = []

            # Evaluar recursivamente cada validación del grupo
            for sub_item in validations_list:
                sub_valid, sub_results = self._evaluate_validation_item(sub_item, transaction, context)
                # Solo incluir en all_valid si es un valor booleano (no None)
                if sub_valid is not None:
                    all_valid.append(sub_valid)
                all_results.extend(sub_results)

            # Aplicar operador lógico solo si hay validaciones booleanas
            if all_valid:
                if operator == "AND":
                    is_valid = all(all_valid)
                else:  # OR
                    is_valid = any(all_valid)
            else:
                # Si no hay validaciones booleanas (todas deshabilitadas), retornar None
                is_valid = None

            self._logger.debug(f"Grupo evaluado: operator={operator}, results={all_valid}, final={is_valid}")
            return is_valid, all_results

        # Si es BaseValidation, evaluarla directamente
        elif isinstance(item, BaseValidation):
            if not item.enabled:
                return None, []  # Si está deshabilitada, retornar None

            result = item.validate(transaction, context)
            if not result.is_valid:
                self._logger.debug(f"Validación falló: {result.validation_name} - {result.message}")

            return result.is_valid, [result]

        # Tipo no reconocido
        else:
            self._logger.warning(f"Tipo de validación no reconocido: {type(item)}")
            return True, []

    def validate(self, transaction: SwapTransaction, context: Dict[str, Any]) -> Tuple[bool, List[ValidationResult]]:
        """
        Valida una transacción con todas las validaciones activas.
        
        Si hay grupos con operadores lógicos, se evalúan recursivamente.
        Si hay validaciones simples, se evalúan directamente.
        Por defecto, todas las validaciones/grupos de nivel superior se combinan con AND.
        
        Args:
            transaction: SwapTransaction a validar
            context: Contexto compartido (puede contener estado, config, etc.)
        
        Returns:
            Tupla (is_valid, results) donde:
            - is_valid: True si todas las validaciones/grupos de nivel superior pasan (AND implícito)
            - results: Lista de resultados de cada validación
        """
        all_results: List[ValidationResult] = []
        all_valid: List[bool] = []

        # Evaluar cada item (puede ser validación simple o grupo)
        for item in self.validations:
            is_valid, results = self._evaluate_validation_item(item, transaction, context)
            # Solo incluir en all_valid si es un valor booleano (no None)
            if is_valid is not None:
                all_valid.append(is_valid)
            all_results.extend(results)

        # A nivel superior, todas las validaciones/grupos se combinan con AND
        is_valid = all(all_valid) if all_valid else True

        return is_valid, all_results

    def _list_validations_from_item(self, item: ValidationItem) -> List[Dict[str, Any]]:
        """Helper recursivo para listar validaciones de un item o grupo"""
        if isinstance(item, BaseValidation):
            return [{
                "name": item.name,
                "enabled": item.enabled,
                "type": item.__class__.__name__
            }]
        elif isinstance(item, dict) and "validations" in item:
            result = []
            for sub_item in item["validations"]:
                result.extend(self._list_validations_from_item(sub_item))
            return result
        return []

    def get_validation(self, validation_name: str) -> Optional[BaseValidation]:
        """
        Obtiene una validación por nombre (busca en grupos anidados).
        
        Args:
            validation_name: Nombre de la validación
        
        Returns:
            La validación si existe, None en caso contrario
        """
        for item in self.validations:
            validation = self._find_validation_in_item(item, validation_name)
            if validation:
                return validation
        return None

    def list_validations(self) -> List[Dict[str, Any]]:
        """
        Lista todas las validaciones registradas (incluye las de grupos anidados).
        
        Returns:
            Lista de diccionarios con información de cada validación
        """
        result = []
        for item in self.validations:
            result.extend(self._list_validations_from_item(item))
        return result

    def _collect_metrics_from_item(self, item: ValidationItem) -> Dict[str, Dict[str, Any]]:
        """Helper recursivo para recopilar métricas de un item o grupo"""
        metrics_dict: Dict[str, Dict[str, Any]] = {}
        if isinstance(item, BaseValidation):
            metrics_dict[item.name] = item.get_metrics()
        elif isinstance(item, dict) and "validations" in item:
            for sub_item in item["validations"]:
                metrics_dict.update(self._collect_metrics_from_item(sub_item))
        return metrics_dict

    def collect_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        Recopila métricas de todas las validaciones registradas (incluye grupos anidados).
        
        Returns:
            Diccionario donde la clave es el nombre de la validación y el valor
            son las métricas específicas de esa validación
        """
        all_metrics: Dict[str, Dict[str, Any]] = {}
        for item in self.validations:
            all_metrics.update(self._collect_metrics_from_item(item))
        return all_metrics

    def reset_all_metrics(self) -> None:
        """Reinicia los contadores de métricas de todas las validaciones"""
        for item in self.validations:
            self._reset_metrics_from_item(item)

    def _reset_metrics_from_item(self, item: ValidationItem) -> None:
        """Helper recursivo para reiniciar métricas de un item o grupo"""
        if isinstance(item, BaseValidation):
            item.reset_metrics()
        elif isinstance(item, dict) and "validations" in item:
            for sub_item in item["validations"]:
                self._reset_metrics_from_item(sub_item)
