"""
应用管理服务
"""

import secrets
import uuid
import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.core.models import App
from gateway.core.schemas import CreateAppRequest
from gateway.core.exceptions import NotFoundException, BadRequestException, InternalServerException

logger = structlog.get_logger(__name__)


def generate_api_key() -> str:
    """
    生成安全的 API Key
    格式：sk_xxx (40 字符)
    """
    random_part = secrets.token_urlsafe(32)[:32]  # 32 字符随机部分
    return f"sk_{random_part}"


class AppService:
    """应用管理服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_app(self, req: CreateAppRequest) -> App:
        """
        创建新应用

        Args:
            req: 创建应用请求

        Returns:
            创建的应用对象

        Raises:
            HTTPException: 如果应用名称已存在或其他错误
        """
        log = logger.bind(name=req.name)

        # 检查应用名称是否已存在
        stmt = select(App).where(App.name == req.name)
        result = await self.session.execute(stmt)
        existing_app = result.scalar_one_or_none()

        if existing_app:
            log.warning("应用名称已存在")
            raise BadRequestException(
                message=f"应用名称 '{req.name}' 已存在",
                code=4008,
                details={"name": req.name}
            )

        # 生成唯一的 API Key
        max_retries = 5
        api_key = None
        for _ in range(max_retries):
            candidate_key = generate_api_key()
            # 检查 API Key 是否已存在
            stmt = select(App).where(App.api_key == candidate_key)
            result = await self.session.execute(stmt)
            if result.scalar_one_or_none() is None:
                api_key = candidate_key
                break

        if api_key is None:
            log.error("生成唯一API Key失败")
            raise InternalServerException(
                message="生成唯一的 API Key 失败",
                code=5004,
            )

        # 创建应用
        app = App(
            id=uuid.uuid4(),
            name=req.name,
            api_key=api_key,
            notify_url=req.notify_url,
            is_active=True,
        )

        self.session.add(app)
        await self.session.commit()
        await self.session.refresh(app)

        log.info("应用创建完成", app_id=str(app.id), api_key=api_key)
        return app

    async def list_apps(self, skip: int = 0, limit: int = 100) -> tuple[list[App], int]:
        """
        列举所有应用

        Args:
            skip: 跳过的记录数（分页）
            limit: 返回的最大记录数（分页）

        Returns:
            (应用列表, 总数) 元组
        """
        # 查询总数
        count_stmt = select(func.count()).select_from(App)
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        # 查询应用列表
        stmt = select(App).order_by(App.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        apps = list(result.scalars().all())

        logger.info("应用列表查询完成", total=total, returned=len(apps))
        return apps, total

    async def get_app_by_id(self, app_id: uuid.UUID) -> App:
        """
        根据 ID 获取应用

        Args:
            app_id: 应用 ID

        Returns:
            应用对象

        Raises:
            HTTPException: 如果应用不存在
        """
        stmt = select(App).where(App.id == app_id)
        result = await self.session.execute(stmt)
        app = result.scalar_one_or_none()

        if app is None:
            raise NotFoundException(
                message="应用不存在",
                code=4047,
                details={"app_id": str(app_id)}
            )

        return app

    async def delete_app(self, app_id: uuid.UUID) -> None:
        """
        删除应用

        Args:
            app_id: 应用 ID

        Raises:
            HTTPException: 如果应用不存在
        """
        app = await self.get_app_by_id(app_id)

        await self.session.delete(app)
        await self.session.commit()

        logger.info("应用删除完成", app_id=str(app_id))

    async def update_app_status(self, app_id: uuid.UUID, is_active: bool) -> App:
        """
        更新应用状态（启用/禁用）

        Args:
            app_id: 应用 ID
            is_active: 是否启用

        Returns:
            更新后的应用对象

        Raises:
            HTTPException: 如果应用不存在
        """
        app = await self.get_app_by_id(app_id)
        app.is_active = is_active

        await self.session.commit()
        await self.session.refresh(app)

        logger.info("应用状态更新完成", app_id=str(app_id), is_active=is_active)
        return app
