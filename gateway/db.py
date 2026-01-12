"""
数据库连接与会话管理（Async SQLAlchemy）
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from gateway.core.settings import get_settings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


settings = get_settings()

# 全局异步引擎（应用启动时创建，关闭时释放）
engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_database_url() -> str:
    """构造异步数据库连接 URL"""
    return (
        f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


async def init_db() -> None:
    """初始化数据库引擎与会话工厂（应用启动时调用）"""
    global engine, async_session_factory

    engine = create_async_engine(
        get_database_url(),
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,  # 连接池健康检查
    )

    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


async def close_db() -> None:
    """关闭数据库引擎（应用关闭时调用）"""
    global engine
    if engine:
        await engine.dispose()
        engine = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入：获取异步数据库会话

    Usage:
        @app.get("/")
        async def handler(session: AsyncSession = Depends(get_session)):
            ...
    """
    if async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_session_ctx() -> AsyncGenerator[AsyncSession, None]:
    """
    上下文管理器：在非 FastAPI 场景（如 worker）中获取异步会话

    Usage:
        async with get_session_ctx() as session:
            ...
    """
    if async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
