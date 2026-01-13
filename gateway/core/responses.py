"""
统一响应格式处理
"""

from typing import Any
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class ResponseModel(BaseModel):
    """统一响应数据模型"""
    
    code: int = Field(..., description="业务状态码，0表示成功")
    msg: str = Field(..., description="响应消息")
    data: Any | None = Field(None, description="响应数据")


def success_response(
    data: Any = None,
    msg: str = "success",
    status_code: int = 200
) -> JSONResponse:
    """
    成功响应
    
    Args:
        data: 响应数据
        msg: 响应消息
        status_code: HTTP状态码，默认200
        
    Returns:
        JSONResponse对象
    """
    response = ResponseModel(code=0, msg=msg, data=data)
    return JSONResponse(
        content=response.model_dump(),
        status_code=status_code
    )


def error_response(
    msg: str,
    code: int = 1000,
    data: Any = None,
    status_code: int = 500
) -> JSONResponse:
    """
    错误响应
    
    Args:
        msg: 错误消息
        code: 业务错误码
        data: 额外数据
        status_code: HTTP状态码，默认500
        
    Returns:
        JSONResponse对象
    """
    response = ResponseModel(code=code, msg=msg, data=data)
    return JSONResponse(
        content=response.model_dump(),
        status_code=status_code
    )


def bad_request_response(
    msg: str = "请求参数错误",
    code: int = 4000,
    data: Any = None
) -> JSONResponse:
    """400 Bad Request 响应"""
    return error_response(msg=msg, code=code, data=data, status_code=400)


def unauthorized_response(
    msg: str = "未授权，请提供有效的认证信息",
    code: int = 4010,
    data: Any = None
) -> JSONResponse:
    """401 Unauthorized 响应"""
    return error_response(msg=msg, code=code, data=data, status_code=401)


def forbidden_response(
    msg: str = "禁止访问",
    code: int = 4030,
    data: Any = None
) -> JSONResponse:
    """403 Forbidden 响应"""
    return error_response(msg=msg, code=code, data=data, status_code=403)


def not_found_response(
    msg: str = "资源不存在",
    code: int = 4040,
    data: Any = None
) -> JSONResponse:
    """404 Not Found 响应"""
    return error_response(msg=msg, code=code, data=data, status_code=404)


def conflict_response(
    msg: str = "资源冲突",
    code: int = 4090,
    data: Any = None
) -> JSONResponse:
    """409 Conflict 响应"""
    return error_response(msg=msg, code=code, data=data, status_code=409)


def validation_error_response(
    msg: str = "数据验证失败",
    code: int = 4220,
    data: Any = None
) -> JSONResponse:
    """422 Unprocessable Entity 响应"""
    return error_response(msg=msg, code=code, data=data, status_code=422)


def internal_server_response(
    msg: str = "服务器内部错误",
    code: int = 5000,
    data: Any = None
) -> JSONResponse:
    """500 Internal Server Error 响应"""
    return error_response(msg=msg, code=code, data=data, status_code=500)


def service_unavailable_response(
    msg: str = "服务暂时不可用",
    code: int = 5030,
    data: Any = None
) -> JSONResponse:
    """503 Service Unavailable 响应"""
    return error_response(msg=msg, code=code, data=data, status_code=503)
