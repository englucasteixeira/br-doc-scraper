from enum import Enum


class ErrorCategory(str, Enum):
    EXPIRED = "EXPIRED"
    REPLACED = "REPLACED"
    NOT_FOUND_800501 = "NOT_FOUND_800501"
    INVALID_201705 = "INVALID_201705"
    UNKNOWN = "UNKNOWN"
