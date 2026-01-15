"""
Callback 处理服务（入站回调 -> 落库 -> 推进 Payment -> 生成 WebhookDelivery）
"""
import traceback
import uuid
from datetime import datetime, UTC

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from gateway.core.constants import CallbackStatus, PaymentStatus, DeliveryStatus
from gateway.core.models import App, Callback, Payment, WebhookDelivery
from gateway.core.schemas import CallbackEvent

logger = structlog.get_logger(__name__)


class CallbackService:
    """回调处理服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def process_callback(self, event: CallbackEvent):
        """
        处理标准化的回调事件

        流程：
        1. 写入 callbacks 表（幂等）
        2. 定位 Payment（通过 merchant_order_no 或 provider_txn_id）
        3. 推进 Payment 状态
        4. 生成 WebhookDelivery
        """
        log = logger.bind(
            provider_event_id=event.provider_event_id,
            provider_txn_id=event.provider_txn_id,
            merchant_order_no=event.merchant_order_no,
            outcome=event.outcome,
        )

        log.info("callback_processing_start")

        # 1. 写入 callbacks（幂等）
        callback = await self._upsert_callback(event)

        # 2. 定位 Payment
        payment = await self._find_payment(event)
        if not payment:
            log.warning("callback_payment_not_found")
            callback.status = CallbackStatus.failed
            await self.session.commit()
            return

        payment_id = payment.id

        # 关联 callback -> payment
        callback.payment_id = payment_id

        # 3. 推进 Payment 状态（加锁）
        await self.session.refresh(payment, with_for_update=True)

        old_status = payment.status
        new_status = self._map_outcome_to_status(event.outcome)

        if new_status and new_status != old_status:
            payment.status = new_status

            if event.provider_txn_id and not payment.provider_txn_id:
                payment.provider_txn_id = event.provider_txn_id

            if new_status == PaymentStatus.succeeded and not payment.paid_at:
                payment.paid_at = datetime.now(UTC)

            log.info(
                "callback_payment_status_updated",
                payment_id=str(payment_id),
                old_status=old_status.value,
                new_status=new_status.value,
            )

        # 4. 生成 WebhookDelivery（如果状态变更为终态）
        if new_status in [
            PaymentStatus.succeeded,
            PaymentStatus.failed,
            PaymentStatus.canceled,
        ]:
            await self._create_webhook_delivery(payment, new_status)

        # 标记 callback 已处理
        callback.status = CallbackStatus.processed
        callback.processed_at = datetime.now(UTC)

        await self.session.commit()
        log.info("callback_processing_completed", payment_id=str(payment_id))

    async def _upsert_callback(self, event: CallbackEvent) -> Callback:
        """写入 callback（幂等）"""
        # 尝试插入
        callback = Callback(
            id=uuid.uuid4(),
            provider=event.raw_payload.get("provider"),
            provider_event_id=event.provider_event_id,
            provider_txn_id=event.provider_txn_id,
            payment_id=None,
            payload=event.raw_payload,
            status=CallbackStatus.processing,
        )

        self.session.add(callback)

        try:
            await self.session.flush()
            return callback
        except IntegrityError:
            # 已存在（幂等），回滚后查询
            logger.error(f"写入Callback事件失败：{traceback.format_exc()}")
            await self.session.rollback()
            stmt = select(Callback).where(
                Callback.provider == callback.provider,
                Callback.provider_event_id == callback.provider_event_id,
            )
            result = await self.session.execute(stmt)
            existing = result.scalar_one()
            return existing

    async def _find_payment(self, event: CallbackEvent) -> Payment | None:
        """定位 Payment（通过 merchant_order_no 或 provider_txn_id）"""
        # 优先用 merchant_order_no
        if event.merchant_order_no:
            stmt = select(Payment).where(
                Payment.merchant_order_no == event.merchant_order_no
            )
            result = await self.session.execute(stmt)
            payment = result.scalar_one_or_none()
            if payment:
                return payment

        # 回退用 provider_txn_id
        if event.provider_txn_id:
            stmt = select(Payment).where(
                Payment.provider_txn_id == event.provider_txn_id
            )
            result = await self.session.execute(stmt)
            payment = result.scalar_one_or_none()
            if payment:
                return payment

        return None

    def _map_outcome_to_status(self, outcome: str) -> PaymentStatus | None:
        """映射 outcome 到 PaymentStatus"""
        outcome_map = {
            "succeeded": PaymentStatus.succeeded,
            "failed": PaymentStatus.failed,
            "canceled": PaymentStatus.canceled,
            # 统一收敛：过期视为取消（未完成支付而关闭）
            "expired": PaymentStatus.canceled,
            "pending": PaymentStatus.pending,
        }
        return outcome_map.get(outcome)

    async def _create_webhook_delivery(
        self, payment: Payment, event_status: PaymentStatus
    ):
        """生成 WebhookDelivery 任务"""
        event_id = f"{payment.id}_{event_status.value}"
        event_type = f"payment.{event_status.value}"

        notify_url = payment.notify_url
        if not notify_url:
            stmt = select(App.notify_url).where(App.id == payment.app_id)
            result = await self.session.execute(stmt)
            notify_url = result.scalar_one_or_none()

        if not notify_url:
            logger.warning(
                "webhook_delivery_missing_notify_url",
                payment_id=str(payment.id),
                app_id=str(payment.app_id),
            )
            return

        payload = {
            "event_id": event_id,
            "event_type": event_type,
            "payment_id": str(payment.id),
            "merchant_order_no": payment.merchant_order_no,
            "status": payment.status.value,
            "amount": payment.amount,
            "currency": payment.currency.value,
            "provider_txn_id": payment.provider_txn_id,
            "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        }

        stmt = select(WebhookDelivery).where(
            WebhookDelivery.app_id == payment.app_id,
            WebhookDelivery.event_id == event_id,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.notify_url = notify_url
            existing.payload = payload
            existing.status = DeliveryStatus.pending
            existing.attempt_count = 0
            existing.next_attempt_at = datetime.now(UTC)
            existing.last_attempt_at = None
            existing.last_http_status = None
            existing.last_error = None
            existing.delivered_at = None
            logger.info(
                "webhook_delivery_requeued",
                delivery_id=str(existing.id),
                event_id=event_id,
            )
            return

        delivery = WebhookDelivery(
            id=uuid.uuid4(),
            app_id=payment.app_id,
            payment_id=payment.id,
            event_id=event_id,
            event_type=event_type,
            notify_url=notify_url,
            payload=payload,
            status=DeliveryStatus.pending,
            attempt_count=0,
            next_attempt_at=datetime.now(UTC),  # 立即尝试
        )

        self.session.add(delivery)
        await self.session.flush()
        logger.info(
            "webhook_delivery_created",
            delivery_id=str(delivery.id),
            event_id=event_id,
        )
