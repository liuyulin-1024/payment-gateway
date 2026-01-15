"""
支付服务层（创建/查询/状态机推进）
"""

import uuid
from datetime import datetime, UTC

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from gateway.core.models import App, Payment
from gateway.core.constants import PaymentStatus
from gateway.core.exceptions import NotFoundException, ConflictException
from gateway.core.schemas import CreatePaymentRequest

logger = structlog.get_logger(__name__)


class PaymentService:
    """支付服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_or_get_payment(
        self,
        app: App,
        req: CreatePaymentRequest,
        idempotency_key: str | None = None,
    ) -> tuple[Payment, bool]:
        """
        创建或获取支付（弱幂等：以 merchant_order_no 为准）

        返回：(Payment, is_new: bool)

        冲突规则：
        - 若同一 merchant_order_no 已存在，检查关键字段（amount/currency/provider）
        - 若不一致，返回 409
        - 若一致，返回已有 Payment
        """
        log = logger.bind(
            app_id=str(app.id),
            merchant_order_no=req.merchant_order_no,
            provider=req.provider.value,
            idempotency_key=idempotency_key,
        )

        # 尝试查找已有订单
        stmt = select(Payment).where(
            Payment.app_id == app.id,
            Payment.merchant_order_no == req.merchant_order_no,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # 计算请求的总金额
            request_total_amount = (req.unit_amount or 0) * req.quantity
            
            # 幂等检查：验证关键字段是否一致
            if (
                existing.amount != request_total_amount
                or existing.currency != req.currency
                or existing.provider != req.provider
            ):
                log.warning(
                    "幂等校验冲突",
                    existing_amount=existing.amount,
                    existing_currency=existing.currency.value,
                    existing_provider=existing.provider.value,
                    request_amount=request_total_amount,
                    request_currency=req.currency.value,
                    request_provider=req.provider.value,
                )
                raise ConflictException(
                    message="该商户订单号已存在，但关键参数不一致",
                    code=4091,
                    details={
                        "merchant_order_no": req.merchant_order_no,
                        "existing": {
                            "amount": existing.amount,
                            "currency": existing.currency.value,
                            "provider": existing.provider.value,
                        },
                        "request": {
                            "amount": request_total_amount,
                            "currency": req.currency.value,
                            "provider": req.provider.value,
                        }
                    }
                )

            log.info("幂等命中返回已有支付", payment_id=str(existing.id))
            return existing, False

        # 计算总金额（单价 * 数量）
        total_amount = (req.unit_amount or 0) * req.quantity
        
        # 创建新支付
        payment = Payment(
            id=uuid.uuid4(),
            app_id=app.id,
            merchant_order_no=req.merchant_order_no,
            provider=req.provider,
            amount=total_amount,
            currency=req.currency,
            status=PaymentStatus.pending,
            notify_url=req.notify_url or app.notify_url,
            provider_txn_id=None,
        )

        self.session.add(payment)

        try:
            await self.session.flush()
            log.info("支付记录已创建", payment_id=str(payment.id))
            return payment, True
        except IntegrityError as exc:
            # 并发创建冲突（理论上应该被前面的 select 捕获，但保险起见）
            await self.session.rollback()
            log.warning("支付创建并发冲突", error=str(exc))
            raise ConflictException(
                message="支付创建并发冲突，请重试",
                code=4092,
                details={"error": str(exc)}
            )

    async def get_payment_by_id(self, app: App, payment_id: uuid.UUID) -> Payment:
        """按 payment_id 查询支付（需验证归属）"""
        stmt = select(Payment).where(
            Payment.id == payment_id,
            Payment.app_id == app.id,
        )
        result = await self.session.execute(stmt)
        payment = result.scalar_one_or_none()

        if payment is None:
            raise NotFoundException(
                message="支付记录不存在",
                code=4041,
                details={"payment_id": str(payment_id)}
            )

        return payment

    async def get_payment_by_merchant_order_no(
        self, app: App, merchant_order_no: str
    ) -> Payment:
        """按 merchant_order_no 查询支付"""
        stmt = select(Payment).where(
            Payment.app_id == app.id,
            Payment.merchant_order_no == merchant_order_no,
        )
        result = await self.session.execute(stmt)
        payment = result.scalar_one_or_none()

        if payment is None:
            raise NotFoundException(
                message="支付记录不存在",
                code=4042,
                details={"merchant_order_no": merchant_order_no}
            )

        return payment

    async def update_payment_status(
        self,
        payment: Payment,
        new_status: PaymentStatus,
        provider_txn_id: str | None = None,
    ):
        """
        更新支付状态（状态机推进）

        注意：调用者应在事务内调用，并负责 commit
        """
        log = logger.bind(
            payment_id=str(payment.id),
            old_status=payment.status.value,
            new_status=new_status.value,
        )

        payment.status = new_status

        if provider_txn_id and not payment.provider_txn_id:
            payment.provider_txn_id = provider_txn_id

        if new_status == PaymentStatus.succeeded and not payment.paid_at:
            payment.paid_at = datetime.now(UTC)

        log.info("支付状态已更新")
