# -*- coding: utf-8 -*-
from enum import Enum

class OpenPositionStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_CLOSED = "partially_closed"
    CLOSED = "closed"
    FAILED = "failed"


class CloseOrderStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    SUCCESS = "success"
    FAILED = "failed"


class PartialCloseOrderStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
