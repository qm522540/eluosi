"""统一响应格式"""

import time
from typing import Any, Optional

from app.utils.errors import ErrorCode, ERROR_MESSAGES


def success(data: Any = None, msg: str = "success") -> dict:
    return {
        "code": ErrorCode.SUCCESS,
        "msg": msg,
        "data": data,
        "timestamp": int(time.time()),
    }


def error(code: int = ErrorCode.UNKNOWN_ERROR, msg: Optional[str] = None, data: Any = None) -> dict:
    return {
        "code": code,
        "msg": msg or ERROR_MESSAGES.get(code, "未知错误"),
        "data": data,
        "timestamp": int(time.time()),
    }


def paginated(items: list, total: int, page: int, page_size: int) -> dict:
    return success(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        }
    )
