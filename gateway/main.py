"""
FastAPI 主应用入口
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .db import close_db, init_db
from gateway.core.logging import configure_logging
from gateway.core.settings import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理：启动时初始化,关闭时清理"""
    # 启动
    configure_logging()
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


@app.get("/")
async def root():
    """根路径：基础信息"""
    return {"service": "payment-gateway", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """健康检查"""
    return JSONResponse(
        content={"status": "ok"},
        status_code=200,
    )


# 路由注册
from .routers import payments, callbacks, admin

app.include_router(payments.router, prefix="/v1", tags=["payments"])
app.include_router(callbacks.router, prefix="/v1/callbacks", tags=["callbacks"])
app.include_router(admin.router, prefix="/v1/admin", tags=["admin"])
