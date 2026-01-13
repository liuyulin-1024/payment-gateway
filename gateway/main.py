"""
FastAPI 主应用入口
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
import traceback
import structlog

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from gateway.db import close_db, init_db
from gateway.core.bootstrap import reset_tables
from gateway.core.logging import configure_logging
from gateway.core.settings import get_settings
from gateway.core.exceptions import BaseAPIException
from gateway.core.responses import (
    error_response,
    bad_request_response,
    validation_error_response,
    internal_server_response,
    success_response,
)

settings = get_settings()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理：启动时初始化,关闭时清理"""
    # 启动
    configure_logging()
    await reset_tables()
    await init_db()
    yield
    # 关闭
    await close_db()


app = FastAPI(
    title="Payment Gateway",
    description="统一支付网关服务（Stripe/微信/支付宝）",
    version="1.0.0",
    lifespan=lifespan,
    swagger_ui_parameters={
        "persistAuthorization": True,  # 持久化授权信息
    },
)


# 配置 OpenAPI 安全方案，让 Swagger UI 显示鉴权按钮
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    from fastapi.openapi.utils import get_openapi

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # 添加 API Key 安全方案
    openapi_schema["components"]["securitySchemes"] = {
        "X-API-Key": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "应用的 API Key（从管理 API 创建应用时获取）",
        }
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# ===== 全局异常处理器 =====


@app.exception_handler(BaseAPIException)
async def base_api_exception_handler(request: Request, exc: BaseAPIException):
    """处理自定义API异常"""
    logger.error(
        "api_exception",
        path=request.url.path,
        method=request.method,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )
    
    return error_response(
        msg=exc.message,
        code=exc.code,
        data=exc.details,
        status_code=exc.status_code
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求参数验证错误（FastAPI自动验证）"""
    logger.warning(
        "validation_error",
        path=request.url.path,
        method=request.method,
        errors=exc.errors(),
    )
    
    # 格式化验证错误信息
    error_details = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        error_details.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"]
        })
    
    return bad_request_response(
        msg="请求参数验证失败",
        code=4000,
        data=error_details
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    """处理Pydantic数据验证错误"""
    logger.warning(
        "pydantic_validation_error",
        path=request.url.path,
        method=request.method,
        errors=exc.errors(),
    )
    
    error_details = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        error_details.append({
            "field": field,
            "message": error["msg"],
            "type": error["type"]
        })
    
    return validation_error_response(
        msg="数据验证失败",
        code=4220,
        data=error_details
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """处理所有未捕获的异常"""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        traceback=traceback.format_exc(),
    )
    
    # 在开发环境返回详细错误信息，生产环境隐藏
    error_details = None
    if settings.debug:
        error_details = {
            "error": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc()
        }
    
    return internal_server_response(
        msg="服务器内部错误",
        code=5000,
        data=error_details
    )


# ===== 基础路由 =====


@app.get("/")
async def root():
    """根路径：基础信息"""
    return success_response(
        data={"service": "payment-gateway", "version": "1.0.0"}
    )


@app.get("/health")
async def health_check():
    """健康检查"""
    return success_response(
        data={"status": "ok"}
    )


# ===== 路由注册 =====
from .routers import payments, callbacks, admin

app.include_router(payments.router, prefix="/v1", tags=["payments"])
app.include_router(callbacks.router, prefix="/v1/callbacks", tags=["callbacks"])
app.include_router(admin.router, prefix="/v1/admin", tags=["admin"])
