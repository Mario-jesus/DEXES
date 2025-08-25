# -*- coding: utf-8 -*- 
"""
Models for the analyzer.
"""
from typing import TypedDict, Optional, List, Any, Literal, Dict, NamedTuple, cast
from dataclasses import dataclass, asdict

from logging_system import AppLogger

_logger = AppLogger(__name__)


class SolanaRPCError(RuntimeError):
    """Error lanzado cuando el RPC retorna un error JSON-RPC válido."""

    def __init__(self, message: str, *, code: Optional[int] = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


class TokenBalance(TypedDict):
    """
    Token balance information.
    """
    pubkey: str
    mint: str
    amount: int
    decimals: int
    ui_amount: float
    ui_amount_string: str
    lamports: int


class BalanceResponse(TypedDict):
    """
    Response from token balance query.
    """
    owner: str
    tokens: List[TokenBalance]
    total_tokens: int


@dataclass(slots=True)
class TransactionAnalysis:
    """
    Analysis of a transaction.
    """
    success: bool
    op_type: Optional[str] = None
    error_kind: Optional[Literal['slippage', 'insufficient_tokens', 'insufficient_lamports', 'invalid_transaction_format', 'transaction_not_found', 'insufficient_funds_for_rent', 'unknown']] = None
    error_message: Optional[str] = None
    token_ui_delta: Optional[str] = None
    bonding_curve_sol_delta: Optional[str] = None
    signer_sol_delta: Optional[str] = None
    fee_sol: Optional[str] = None
    total_cost_sol: Optional[str] = None
    price_sol_per_token: Optional[str] = None


@dataclass(slots=True)
class SignatureStatus:
    """
    Status information for a transaction signature.
    """
    confirmationStatus: Optional[Literal['finalized', 'confirmed', 'processed']]
    confirmations: Optional[int]
    slot: int
    success: bool
    type_error: Optional[Literal['slippage', 'insufficient_tokens', 'insufficient_lamports', 'insufficient_funds_for_rent', 'unknown']] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignatureStatus":
        """
        Optimización de la conversión desde diccionario para SignatureStatus.
        Mantiene la funcionalidad original, pero simplifica la lógica y mejora la legibilidad.
        """
        type_error = None
        status = False

        _logger.debug(f"[SignatureStatus.from_dict] Recibiendo data: {data}")

        status_data = data.get("status")
        _logger.debug(f"[SignatureStatus.from_dict] status_data: {status_data}")

        if isinstance(status_data, dict):
            status = "Ok" in status_data
            _logger.debug(f"[SignatureStatus.from_dict] status (Ok in status_data): {status}")
            err = status_data.get("Err")
            _logger.debug(f"[SignatureStatus.from_dict] err: {err}")
            if err and isinstance(err, dict):
                # Mapear InsufficientFundsForRent directamente
                if "InsufficientFundsForRent" in err:
                    type_error = "insufficient_funds_for_rent"
                    _logger.debug(f"[SignatureStatus.from_dict] InsufficientFundsForRent detectado")
                else:
                    ins_err = err.get("InstructionError", [0, {}])
                    _logger.debug(f"[SignatureStatus.from_dict] ins_err: {ins_err}")
                    code_error = 0
                    if (
                        isinstance(ins_err, list)
                        and len(ins_err) > 1
                        and isinstance(ins_err[1], dict)
                        and isinstance(ins_err[1].get("Custom"), int)
                    ):
                        code_error = cast(int, ins_err[1]["Custom"])
                        _logger.debug(f"[SignatureStatus.from_dict] code_error detectado: {code_error}")
                    elif (
                        isinstance(ins_err, list)
                        and len(ins_err) > 1
                        and isinstance(ins_err[1], dict)
                        and "InsufficientFundsForRent" in ins_err[1]
                    ):
                        type_error = "insufficient_funds_for_rent"
                        _logger.debug(f"[SignatureStatus.from_dict] InsufficientFundsForRent dentro de InstructionError detectado")
                    elif (
                        isinstance(ins_err, list)
                        and len(ins_err) > 1
                        and isinstance(ins_err[1], str)
                        and ins_err[1] == "InsufficientFundsForRent"
                    ):
                        type_error = "insufficient_funds_for_rent"
                        _logger.debug(f"[SignatureStatus.from_dict] InsufficientFundsForRent string dentro de InstructionError detectado")

                    if type_error is None:
                        if code_error == 6002:
                            type_error = "slippage"
                        elif code_error == 6023:
                            type_error = "insufficient_tokens"
                        elif code_error == 1:
                            type_error = "insufficient_lamports"
                        else:
                            type_error = "unknown"
                        _logger.debug(f"[SignatureStatus.from_dict] type_error mapeado: {type_error}")
            elif err is not None:
                type_error = "unknown"
                _logger.debug(f"[SignatureStatus.from_dict] err no es dict pero existe, type_error=unknown")
        elif isinstance(status_data, bool):
            status = status_data
            type_error = data.get("type_error")
            _logger.debug(f"[SignatureStatus.from_dict] status_data es bool: {status}, type_error: {type_error}")

        _logger.debug(f"[SignatureStatus.from_dict] Retornando: confirmationStatus={data.get('confirmationStatus')}, confirmations={data.get('confirmations')}, slot={data.get('slot', 0)}, success={bool(status)}, type_error={type_error}")

        return cls(
            confirmationStatus=data.get("confirmationStatus"),
            confirmations=data.get("confirmations"),
            slot=data.get("slot", 0),
            success=bool(status),
            type_error=type_error
        )


@dataclass(slots=True)
class RpcContext:
    """
    Context information for a transaction.
    """
    slot: int
    apiVersion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RpcContext":
        return cls(**data)


@dataclass(slots=True)
class SignatureStatusesResponse:
    """
    Response from getSignatureStatuses RPC call.
    """
    context: RpcContext
    value: List[Optional[SignatureStatus]]

    @property
    def all_success(self) -> bool:
        return all(self.value) and all(status.success for status in self.value if status is not None)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignatureStatusesResponse":
        value: List[Optional[SignatureStatus]] = []
        for status in data["value"]:
            if status is not None and isinstance(status, dict):
                value.append(SignatureStatus.from_dict(status))
            else:
                value.append(None)

        return cls(
            context=RpcContext.from_dict(data["context"]),
            value=value
        )


class SignaturesWithStatuses(NamedTuple):
    data: Dict[str, Optional[SignatureStatus]]
    all_success: bool
    all_exists: bool
