from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import inspect

from gateway.db import get_database_url
from gateway.core.settings import get_settings


async def reset_tables() -> None:
    """根据配置创建或重置数据库表"""
    
    settings = get_settings()
    
    # 确保导入所有模型
    from gateway.core.models import Base
    
    # 创建异步引擎
    engine = create_async_engine(get_database_url(), echo=False)
    
    if settings.need_reset_database:
        # 强制重置数据库：删除所有表后重新创建
        print("🗄️  正在重置数据库表...")
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        print("✅ 数据库表重置完成！")
    else:
        # 检查表是否存在，不存在才创建
        print("🔍 检查数据库表...")
        
        async with engine.begin() as conn:
            # 检查表是否存在
            def check_tables_exist(connection):
                inspector = inspect(connection)
                existing_tables = inspector.get_table_names()
                required_tables = Base.metadata.tables.keys()
                return set(required_tables).issubset(set(existing_tables))
            
            tables_exist = await conn.run_sync(check_tables_exist)
            
            if tables_exist:
                print("✅ 数据库表已存在，跳过创建")
            else:
                print("🗄️  数据库表不存在，正在创建...")
                await conn.run_sync(Base.metadata.create_all)
                print("✅ 数据库表创建完成！")
    
    await engine.dispose()