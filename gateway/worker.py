"""
WebhookDelivery 投递 Worker（异步轮询 + 并发投递 + 重试 + 死信）
"""

import uuid
import asyncio
import random
from datetime import datetime, timedelta, UTC

import httpx
import structlog
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.core.constants import DeliveryStatus
from .db import init_db, close_db, get_session_ctx
from gateway.core.models import WebhookDelivery
from gateway.core.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# processing 状态超过此时长视为卡死，将被重新认领
PROCESSING_TIMEOUT = timedelta(minutes=5)


class WebhookDeliveryWorker:
    """WebhookDelivery 投递 Worker"""

    def __init__(self):
        self.poll_interval = settings.worker_poll_interval
        self.batch_size = settings.worker_batch_size
        self.max_retries = settings.worker_max_retries
        self.concurrency = settings.worker_concurrency
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30,
            ),
        )

    async def start(self):
        """启动 worker 主循环"""
        logger.info(
            "Webhook投递Worker启动",
            poll_interval=self.poll_interval,
            batch_size=self.batch_size,
            max_retries=self.max_retries,
            concurrency=self.concurrency,
        )

        try:
            while True:
                try:
                    await self.process_pending_deliveries()
                except Exception as exc:
                    logger.error(
                        "Webhook投递Worker运行异常",
                        error=str(exc),
                        exc_info=True,
                    )

                await asyncio.sleep(self.poll_interval)
        finally:
            await self.http_client.aclose()

    async def process_pending_deliveries(self):
        """
        处理待投递任务（两阶段）：
        Phase 1 - 认领：SELECT FOR UPDATE SKIP LOCKED 加锁，标记 processing 后释放行锁
        Phase 2 - 投递：并发 HTTP 投递，每个投递使用独立 DB session
        """
        # Phase 1: 认领任务
        delivery_ids: list[uuid.UUID] = []

        async with get_session_ctx() as session:
            now = datetime.now(UTC)
            stmt = (
                select(WebhookDelivery)
                .where(
                    and_(
                        WebhookDelivery.attempt_count < self.max_retries,
                        or_(
                            # 正常待投递：pending/failed 且到达重试时间
                            and_(
                                WebhookDelivery.status.in_(
                                    [DeliveryStatus.pending, DeliveryStatus.failed]
                                ),
                                (
                                    WebhookDelivery.next_attempt_at.is_(None)
                                    | (WebhookDelivery.next_attempt_at <= now)
                                ),
                            ),
                            # 卡死恢复：processing 超过阈值未完成
                            and_(
                                WebhookDelivery.status == DeliveryStatus.processing,
                                WebhookDelivery.last_attempt_at <= now - PROCESSING_TIMEOUT,
                            ),
                        ),
                    )
                )
                .order_by(WebhookDelivery.created_at)
                .limit(self.batch_size)
                .with_for_update(skip_locked=True)
            )

            result = await session.execute(stmt)
            deliveries = result.scalars().all()

            if not deliveries:
                return

            logger.info("开始处理Webhook投递批次", count=len(deliveries))

            for d in deliveries:
                d.status = DeliveryStatus.processing
                d.last_attempt_at = now
                delivery_ids.append(d.id)

        # Phase 2: 并发投递（每个投递使用独立 session 查询最新状态）
        sem = asyncio.Semaphore(self.concurrency)

        async def _deliver_one(delivery_id: uuid.UUID):
            async with sem:
                try:
                    async with get_session_ctx() as session:
                        stmt = select(WebhookDelivery).where(
                            WebhookDelivery.id == delivery_id
                        )
                        result = await session.execute(stmt)
                        delivery = result.scalar_one_or_none()
                        if delivery:
                            await self.deliver_webhook(session, delivery)
                except Exception as exc:
                    logger.error(
                        "Webhook投递任务异常",
                        delivery_id=str(delivery_id),
                        error=str(exc),
                        exc_info=True,
                    )
                    try:
                        async with get_session_ctx() as session:
                            stmt = select(WebhookDelivery).where(
                                WebhookDelivery.id == delivery_id
                            )
                            result = await session.execute(stmt)
                            delivery = result.scalar_one_or_none()
                            if delivery and delivery.status != DeliveryStatus.succeeded:
                                delivery.last_error = f"WorkerError: {str(exc)[:200]}"
                                await self.schedule_retry(
                                    session,
                                    delivery,
                                    logger.bind(delivery_id=str(delivery_id)),
                                )
                    except Exception as retry_exc:
                        logger.error(
                            "重试调度失败，等待超时恢复",
                            delivery_id=str(delivery_id),
                            error=str(retry_exc),
                        )

        await asyncio.gather(
            *[_deliver_one(d_id) for d_id in delivery_ids],
            return_exceptions=True,
        )

    async def deliver_webhook(self, session: AsyncSession, delivery: WebhookDelivery):
        """投递单个 webhook"""
        # 状态守卫：如果 delivery 已非 processing（被另一 worker 重新认领或已完成），跳过
        if delivery.status != DeliveryStatus.processing:
            logger.warning(
                "跳过投递：状态已变更",
                delivery_id=str(delivery.id),
                status=delivery.status.value,
            )
            return

        delivery.attempt_count += 1
        log = logger.bind(
            delivery_id=str(delivery.id),
            event_id=delivery.event_id,
            event_type=delivery.event_type,
            attempt_count=delivery.attempt_count,
        )

        try:
            log.info("开始投递Webhook", notify_url=delivery.notify_url)

            response = await self.http_client.post(
                delivery.notify_url,
                json=delivery.payload,
                headers={"Content-Type": "application/json"},
            )

            delivery.last_http_status = response.status_code

            if 200 <= response.status_code < 300:
                # 加锁确认状态仍为 processing，防止与卡死恢复 worker 重复写入
                try:
                    await session.refresh(delivery, with_for_update=True)
                except Exception as refresh_exc:
                    log.error(
                        "Webhook投递已成功但刷新状态失败，将由卡死恢复机制处理",
                        http_status=response.status_code,
                        error=str(refresh_exc),
                    )
                    return

                if delivery.status != DeliveryStatus.processing:
                    log.warning(
                        "投递完成但状态已被其他worker变更，放弃写入",
                        current_status=delivery.status.value,
                    )
                    return

                delivery.status = DeliveryStatus.succeeded
                delivery.delivered_at = datetime.now(UTC)
                delivery.next_attempt_at = None
                await session.commit()

                log.info(
                    "Webhook投递成功",
                    http_status=response.status_code,
                )
            else:
                delivery.last_error = (
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                await self.schedule_retry(session, delivery, log)

        except httpx.RequestError as exc:
            delivery.last_http_status = None
            delivery.last_error = f"RequestError: {str(exc)[:200]}"
            await self.schedule_retry(session, delivery, log)

        except Exception as exc:
            delivery.last_http_status = None
            delivery.last_error = f"Exception: {str(exc)[:200]}"
            await self.schedule_retry(session, delivery, log)

    async def schedule_retry(
        self,
        session: AsyncSession,
        delivery: WebhookDelivery,
        log: structlog.BoundLogger,
    ):
        """计划重试（指数退避 + 抖动）或标记死信"""
        if delivery.attempt_count >= self.max_retries:
            delivery.status = DeliveryStatus.dead
            delivery.next_attempt_at = None
            await session.commit()

            log.error(
                "Webhook投递进入死信",
                last_error=delivery.last_error,
            )
        else:
            base_delay = 2**delivery.attempt_count  # 2^n 秒
            jitter = random.uniform(0, base_delay * 0.2)  # ±20% 抖动
            delay_seconds = base_delay + jitter

            delivery.status = DeliveryStatus.failed
            delivery.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=delay_seconds
            )
            await session.commit()

            log.warning(
                "Webhook投递失败将重试",
                last_error=delivery.last_error,
                next_attempt_at=delivery.next_attempt_at.isoformat(),
            )


async def main():
    """Worker 入口"""
    await init_db()
    try:
        worker = WebhookDeliveryWorker()
        await worker.start()
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
