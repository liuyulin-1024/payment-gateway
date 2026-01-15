"""
WebhookDelivery 投递 Worker（异步轮询 + 重试 + 死信）
"""

import asyncio
import random
from datetime import datetime, timedelta, UTC

import httpx
import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.core.constants import DeliveryStatus
from .db import init_db, close_db, get_session_ctx
from gateway.core.models import WebhookDelivery
from gateway.core.settings import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class WebhookDeliveryWorker:
    """WebhookDelivery 投递 Worker"""

    def __init__(self):
        self.poll_interval = settings.worker_poll_interval
        self.batch_size = settings.worker_batch_size
        self.max_retries = settings.worker_max_retries
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def start(self):
        """启动 worker 主循环"""
        logger.info(
            "Webhook投递Worker启动",
            poll_interval=self.poll_interval,
            batch_size=self.batch_size,
            max_retries=self.max_retries,
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
        """处理待投递任务"""
        async with get_session_ctx() as session:
            # 查询待投递任务（pending 或 failed 且到达重试时间）
            now = datetime.now(UTC)
            stmt = (
                select(WebhookDelivery)
                .where(
                    and_(
                        WebhookDelivery.status.in_(
                            [DeliveryStatus.pending, DeliveryStatus.failed]
                        ),
                        WebhookDelivery.attempt_count < self.max_retries,
                        (
                            WebhookDelivery.next_attempt_at.is_(None)
                            | (WebhookDelivery.next_attempt_at <= now)
                        ),
                    )
                )
                .order_by(WebhookDelivery.created_at)
                .limit(self.batch_size)
            )

            result = await session.execute(stmt)
            deliveries = result.scalars().all()

            if not deliveries:
                # logger.debug("webhook_delivery_worker_no_pending_tasks")
                return

            logger.info(
                "开始处理Webhook投递批次",
                count=len(deliveries),
            )

            for delivery in deliveries:
                try:
                    await self.deliver_webhook(session, delivery)
                except Exception as exc:
                    log = logger.bind(
                        delivery_id=str(delivery.id),
                        event_id=delivery.event_id,
                        event_type=delivery.event_type,
                        attempt_count=delivery.attempt_count,
                    )
                    delivery.last_http_status = None
                    delivery.last_error = f"WorkerError: {str(exc)[:200]}"
                    await self.schedule_retry(session, delivery, log)

    async def deliver_webhook(self, session: AsyncSession, delivery: WebhookDelivery):
        """投递单个 webhook"""
        log = logger.bind(
            delivery_id=str(delivery.id),
            event_id=delivery.event_id,
            event_type=delivery.event_type,
            attempt_count=delivery.attempt_count + 1,
        )

        delivery.status = DeliveryStatus.processing
        delivery.attempt_count += 1
        delivery.last_attempt_at = datetime.now(UTC)
        await session.commit()

        try:
            log.info("开始投递Webhook", notify_url=delivery.notify_url)

            response = await self.http_client.post(
                delivery.notify_url,
                json=delivery.payload,
                headers={"Content-Type": "application/json"},
            )

            delivery.last_http_status = response.status_code

            if 200 <= response.status_code < 300:
                # 投递成功
                delivery.status = DeliveryStatus.succeeded
                delivery.delivered_at = datetime.now(UTC)
                delivery.next_attempt_at = None
                await session.commit()

                log.info(
                    "Webhook投递成功",
                    http_status=response.status_code,
                )
            else:
                # HTTP 非 2xx：投递失败，计划重试
                delivery.last_error = (
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                await self.schedule_retry(session, delivery, log)

        except httpx.RequestError as exc:
            # 网络错误/超时：投递失败，计划重试
            delivery.last_http_status = None
            delivery.last_error = f"RequestError: {str(exc)[:200]}"
            await self.schedule_retry(session, delivery, log)

        except Exception as exc:
            # 其他异常：投递失败，计划重试
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
            # 超过重试上限：标记死信
            delivery.status = DeliveryStatus.dead
            delivery.next_attempt_at = None
            await session.commit()

            log.error(
                "Webhook投递进入死信",
                last_error=delivery.last_error,
            )
        else:
            # 计划重试：指数退避 + 抖动
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
