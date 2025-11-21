# -*- coding: utf-8 -*-
"""
Detected errors.
"""
from typing import Any, Dict, Optional, TypedDict
from logging_system import AppLogger


class DetectedError(TypedDict):
    kind: Optional[str]
    message: Optional[str]

class DetectedErrors:
    """
    Detects errors in a transaction.
    """

    def __init__(self) -> None:
        self._logger = AppLogger(self.__class__.__name__)

    def detect_error(self, err: Any = None) -> Optional[DetectedError]:
        """
        Detects an error in a transaction.
        """
        error_info: DetectedError = {"kind": None, "message": None}

        # Meta error (usar err para clasificar el tipo)
        if err is not None:
            try:
                self._logger.debug(f"Attempting to parse err: {err}")
                kind: Optional[str] = None
                message: Optional[str] = None

                if isinstance(err, dict):
                    # Caso directo: {'InsufficientFundsForRent': {...}}
                    if "InsufficientFundsForRent" in err:
                        rent_detail = err.get("InsufficientFundsForRent")
                        account_index = None
                        if isinstance(rent_detail, dict):
                            account_index = rent_detail.get("account_index") or rent_detail.get("accountIndex")
                        elif isinstance(rent_detail, int):
                            account_index = rent_detail
                        kind = "insufficient_funds_for_rent"
                        message = (
                            f"insufficient funds for rent-exemption on account_index {account_index}"
                            if account_index is not None else
                            "insufficient funds for rent-exemption"
                        )
                        self._logger.debug("Err indicates insufficient_funds_for_rent.")

                    # Caso InstructionError
                    elif "InstructionError" in err:
                        err_val = err.get("InstructionError")
                        if isinstance(err_val, list) and len(err_val) >= 2:
                            detail = err_val[1]

                            # Variante: {'Custom': code}
                            if isinstance(detail, dict) and isinstance(detail.get("Custom"), int):
                                code = int(detail["Custom"])  # anchor custom code
                                if code == 6002:
                                    kind = "slippage"
                                elif code == 6023:
                                    kind = "insufficient_tokens"
                                elif code == 1:
                                    kind = "insufficient_lamports"
                                else:
                                    kind = "unknown"
                                message = f"custom program error: {code}"

                            # Variante: {'InsufficientFundsForRent': {...}} dentro de InstructionError
                            elif isinstance(detail, dict) and "InsufficientFundsForRent" in detail:
                                rent_detail = detail.get("InsufficientFundsForRent")
                                account_index = None
                                if isinstance(rent_detail, dict):
                                    account_index = rent_detail.get("account_index") or rent_detail.get("accountIndex")
                                elif isinstance(rent_detail, int):
                                    account_index = rent_detail
                                kind = "insufficient_funds_for_rent"
                                message = (
                                    f"insufficient funds for rent-exemption on account_index {account_index}"
                                    if account_index is not None else
                                    "insufficient funds for rent-exemption"
                                )

                            # Variante: string builtin
                            elif isinstance(detail, str):
                                if detail == "InsufficientFundsForRent":
                                    kind = "insufficient_funds_for_rent"
                                    message = "insufficient funds for rent-exemption"
                                elif detail.lower().startswith("insufficient"):
                                    # Podrían aparecer mensajes genéricos de insuficiencia
                                    kind = "unknown"
                                    message = detail
                                else:
                                    kind = "unknown"
                                    message = detail
                            else:
                                kind = "unknown"
                                message = str(detail)

                        else:
                            kind = "unknown"
                            message = str(err)

                    # Cualquier otra clave en err => unknown
                    else:
                        kind = "unknown"
                        message = str(err)

                elif isinstance(err, str):
                    if "InsufficientFundsForRent" in err:
                        kind = "insufficient_funds_for_rent"
                        message = err
                    else:
                        kind = "unknown"
                        message = err
                else:
                    kind = "unknown"
                    message = str(err)

                error_info["kind"] = kind
                if message:
                    error_info["message"] = message
            except Exception as e:
                self._logger.warning(f"Error processing meta_err: {e}")
                pass

        # Ya no usamos logs para mensajes; construir mensajes descriptivos.
        # Si no hubo mapeo previo (kind None) o no se asignó mensaje, definimos por defecto más abajo

        # Completar mensajes descriptivos estándar según kind mapeado
        if error_info["kind"] in ("slippage", "insufficient_tokens", "insufficient_lamports", "insufficient_funds_for_rent"):
            if not error_info.get("message"):
                if error_info["kind"] == "slippage":
                    error_info["message"] = "price slippage exceeded allowed threshold"
                elif error_info["kind"] == "insufficient_tokens":
                    error_info["message"] = "not enough tokens to complete operation"
                elif error_info["kind"] == "insufficient_lamports":
                    error_info["message"] = "insufficient lamports to cover fees or transfer"
                elif error_info["kind"] == "insufficient_funds_for_rent":
                    error_info["message"] = "insufficient funds for rent-exemption"
        else:
            # Caso unknown u otro no permitido: construir mensaje a partir de err
            if isinstance(err, dict):
                try:
                    # Tomar primera clave y valor completo
                    if err:
                        first_key = next(iter(err.keys()))
                        first_value = err[first_key]
                        value_str = str(first_value) if not isinstance(first_value, dict) else str(first_value)
                        error_info["kind"] = "unknown"
                        error_info["message"] = f"{first_key}: {value_str}"
                    else:
                        error_info["kind"] = "unknown"
                        error_info["message"] = "{}"
                except Exception:
                    error_info["kind"] = "unknown"
                    error_info["message"] = str(err)
            elif err is not None:
                error_info["kind"] = "unknown"
                error_info["message"] = str(err)

        if error_info["kind"] is None:
            self._logger.warning(f"Could not categorize meta error: {err}")

        return error_info if error_info["kind"] else None
