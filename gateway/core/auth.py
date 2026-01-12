"""
App 鉴权与依赖注入
"""

from fastapi import Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db import get_session
from gateway.core.models import App


async def get_app_from_api_key(
    authorization: str = Header(..., description="应用 API Key"),
    session: AsyncSession = Depends(get_session),
) -> App:
    """
    从请求头的 X-API-Key 解析并验证 App

    依赖注入用法：
        @app.post("/v1/payments")
        async def create_payment(
            app: App = Depends(get_app_from_api_key),
            ...
        ):
            ...
    """
    x_api_key = authorization.split(" ")[-1]
    stmt = select(App).where(App.api_key == x_api_key)
    result = await session.execute(stmt)
    app = result.scalar_one_or_none()

    if app is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )

    if not app.is_active:
        raise HTTPException(
            status_code=403,
            detail="App is inactive",
        )

    return app
