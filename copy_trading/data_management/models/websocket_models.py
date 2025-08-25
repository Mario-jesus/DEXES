# -*- coding: utf-8 -*-
"""
Models for websocket subscriptions.
"""
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, Any, Optional, Literal, Union, cast

from logging_system import AppLogger

_logger = AppLogger(__name__)


@dataclass(slots=True)
class WebsocketSubscription:
    signature: str
    timeout: int
    queued_at: datetime
    status: Literal['pending', 'subscribed', 'confirmed', 'timeout'] = 'pending'
    subscription_id: Optional[int] = None
    subscribed_at: datetime = field(default_factory=datetime.now)
    confirmed_at: Optional[datetime] = None
    commitment: Literal["finalized", "confirmed", "processed"] = "finalized"
    enable_received_notification: bool = False
    wait_time: float = field(init=False)

    def __post_init__(self):
        self.wait_time = (self.subscribed_at - self.queued_at).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebsocketSubscription":
        """Crea desde diccionario"""
        return cls(
            signature=data["signature"],
            timeout=data["timeout"],
            queued_at=datetime.fromisoformat(data["queued_at"]),
            status=data["status"],
            subscription_id=data["subscription_id"],
            subscribed_at=datetime.fromisoformat(data["subscribed_at"]),
            confirmed_at=datetime.fromisoformat(data["confirmed_at"]) if data["confirmed_at"] else None,
            commitment=data["commitment"],
            enable_received_notification=data["enable_received_notification"]
        )


@dataclass(slots=True)
class RpcContext:
    """Contexto de la respuesta RPC."""
    slot: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RpcContext":
        """Crea desde diccionario"""
        return RpcContext(
            slot=data["slot"]
        )


@dataclass(slots=True)
class SignatureNotificationValue:
    """Valor de la notificación de firma."""
    err: Optional[Literal['slippage', 'insufficient_tokens', 'insufficient_lamports', 'insufficient_funds_for_rent', 'unknown']] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignatureNotificationValue":
        """
        Optimización de la conversión desde diccionario para SignatureNotificationValue.
        Mantiene la funcionalidad original, pero agrega la lógica de mapeo de códigos de error
        similar a SignatureStatus.
        """
        type_error: Optional[str] = None

        if isinstance(data, dict):
            _logger.debug(f"[SignatureNotificationValue] Procesando data: {data}")
            err_data = data.get("err")

            if err_data and isinstance(err_data, dict):
                _logger.debug(f"[SignatureNotificationValue] err_data es dict: {err_data}")
                # Mapear InsufficientFundsForRent en err directo
                if "InsufficientFundsForRent" in err_data:
                    type_error = "insufficient_funds_for_rent"
                else:
                    ins_err = err_data.get("InstructionError", [0, {}])
                    code_error = 0
                    if (
                        isinstance(ins_err, list)
                        and len(ins_err) > 1
                        and isinstance(ins_err[1], dict)
                        and isinstance(ins_err[1].get("Custom"), int)
                    ):
                        code_error = ins_err[1]["Custom"]
                        _logger.debug(f"[SignatureNotificationValue] code_error detectado: {code_error}")
                    elif (
                        isinstance(ins_err, list)
                        and len(ins_err) > 1
                        and isinstance(ins_err[1], dict)
                        and "InsufficientFundsForRent" in ins_err[1]
                    ):
                        type_error = "insufficient_funds_for_rent"
                    elif (
                        isinstance(ins_err, list)
                        and len(ins_err) > 1
                        and isinstance(ins_err[1], str)
                        and ins_err[1] == "InsufficientFundsForRent"
                    ):
                        type_error = "insufficient_funds_for_rent"

                    if type_error is None:
                        if code_error == 6002:
                            type_error = "slippage"
                        elif code_error == 6023:
                            type_error = "insufficient_tokens"
                        elif code_error == 1:
                            type_error = "insufficient_lamports"
                        else:
                            type_error = "unknown"
                    _logger.debug(f"[SignatureNotificationValue] type_error mapeado: {type_error}")
            elif (isinstance(err_data, str) and
                err_data in ["slippage", "insufficient_tokens", "insufficient_lamports", "insufficient_funds_for_rent", "unknown"]):
                _logger.debug(f"[SignatureNotificationValue] err_data es string conocido: {err_data}")
                type_error = err_data
            elif err_data is not None:
                _logger.debug(f"[SignatureNotificationValue] err_data no reconocido: {err_data}")
                type_error = "unknown"
        else:
            _logger.debug(f"[SignatureNotificationValue] data no es dict: {data}")

        _logger.debug(f"[SignatureNotificationValue] Retornando err={type_error}")
        return SignatureNotificationValue(
            err=cast(
                Optional[Literal['slippage', 'insufficient_tokens', 'insufficient_lamports', 'insufficient_funds_for_rent', 'unknown']],
                type_error
            )
        )


@dataclass(slots=True)
class SignatureNotificationResult:
    """Resultado de la notificación de firma."""
    context: RpcContext
    value: Union[SignatureNotificationValue, Literal["receivedSignature"]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignatureNotificationResult":
        """Crea desde diccionario"""
        context = RpcContext.from_dict(data["context"])

        # El valor puede ser un objeto o un string literal
        value_data: Union[Dict[str, Any], str] = data["value"]
        if isinstance(value_data, str) and value_data == "receivedSignature":
            value = value_data
        else:
            value = SignatureNotificationValue.from_dict(value_data if isinstance(value_data, dict) else {})

        return SignatureNotificationResult(
            context=context,
            value=value
        )


@dataclass(slots=True)
class WebsocketSignatureNotificationParams:
    result: SignatureNotificationResult
    subscription: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebsocketSignatureNotificationParams":
        """Crea desde diccionario"""
        return WebsocketSignatureNotificationParams(
            result=SignatureNotificationResult.from_dict(data["result"]),
            subscription=data["subscription"]
        )


@dataclass(slots=True)
class SignatureNotification:
    """Notificación de firma del método RPC signatureSubscribe."""
    params: WebsocketSignatureNotificationParams
    jsonrpc: Literal["2.0"]
    method: Literal["signatureNotification"]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def result(self) -> Optional[SignatureNotificationResult]:
        """Obtiene el resultado de la notificación."""
        return self.params.result

    @property
    def subscription_id(self) -> Optional[int]:
        """Obtiene el ID de suscripción."""
        return self.params.subscription

    @property
    def slot(self) -> Optional[int]:
        """Obtiene el slot de la transacción."""
        return self.result.context.slot if self.result else None

    @property
    def is_success(self) -> bool:
        """Determina si la transacción fue exitosa."""
        if not self.result:
            return False

        if isinstance(self.result.value, str):
            return True

        return self.result.value.err is None

    @property
    def is_received_signature(self) -> bool:
        """Determina si es una notificación de firma recibida."""
        if not self.result:
            return False

        return isinstance(self.result.value, str) and self.result.value == "receivedSignature"

    @property
    def error(self) -> Optional[Literal['slippage', 'insufficient_tokens', 'insufficient_lamports', 'insufficient_funds_for_rent', 'unknown']]:
        """Obtiene el error si existe."""
        if not self.result or isinstance(self.result.value, str):
            return None

        return self.result.value.err

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignatureNotification":
        """Crea desde diccionario"""
        return SignatureNotification(
            params=WebsocketSignatureNotificationParams.from_dict(data["params"]),
            jsonrpc=data["jsonrpc"],
            method=data["method"]
        )
