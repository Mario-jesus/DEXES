# -*- coding: utf-8 -*-
from enum import Enum

class OpenPositionStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class CloseOrderStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PartialCloseOrderStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
