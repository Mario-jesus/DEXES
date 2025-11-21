# -*- coding: utf-8 -*-
"""
Modelos para transacciones enhanced.
"""
from typing import TypedDict, NotRequired, Any, List, Optional, Dict


class EnhancedTransactionResponse(TypedDict):
    description: str
    type: str
    source: str
    fee: int
    feePayer: str
    signature: str
    slot: int
    timestamp: int
    tokenTransfers: List['TokenTransfer']
    nativeTransfers: List['NativeTransfer']
    accountData: List['AccountData']
    transactionError: Optional[Dict[str, Any]]
    instructions: List['Instruction']
    events: Any


class TokenTransfer(TypedDict):
    fromTokenAccount: str
    toTokenAccount: str
    fromUserAccount: str
    toUserAccount: str
    tokenAmount: float
    mint: str
    tokenStandard: NotRequired[str]


class NativeTransfer(TypedDict):
    fromUserAccount: str
    toUserAccount: str
    amount: float


class AccountData(TypedDict):
    account: str
    nativeBalanceChange: int
    tokenBalanceChanges: List['TokenBalanceChange']


class TokenBalanceChange(TypedDict):
    userAccount: str
    tokenAccount: str
    rawTokenAmount: 'RawTokenAmount'
    mint: str


class RawTokenAmount(TypedDict):
    tokenAmount: str
    decimals: int


class Instruction(TypedDict):
    accounts: List[str]
    data: str
    programId: str
    innerInstructions: List['InnerInstruction']


class InnerInstruction(TypedDict):
    accounts: List[str]
    data: str
    programId: str
