from sqlalchemy.ext.asyncio import create_async_engine

from gateway.db import get_database_url


async def reset_tables() -> None:
    """直接从模型创建数据库表"""

    print("🗄️  正在创建数据库表...")

    # 确保导入所有模型
    from gateway.core.models import Base

    # 创建异步引擎
    engine = create_async_engine(get_database_url(), echo=False)

    # 删除所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    async with engine.begin() as conn:
        # 创建所有表（如果不存在）
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()
    print("✅ 数据库表创建完成！")