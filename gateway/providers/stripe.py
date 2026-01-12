"""
Stripe Provider Adapter
"""

import uuid
import stripe
import traceback

from gateway.core.constants import Provider
from gateway.core.settings import get_settings
from gateway.core.schemas import PaymentTypeEnum, CallbackEvent
from .base import ProviderAdapter, ProviderPaymentResult


settings = get_settings()


class StripeAdapter(ProviderAdapter):
    """Stripe 支付适配器（单例模式）"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # 避免重复初始化
        if self._initialized:
            return

        # 从配置中获取参数
        self.secret_key = settings.stripe_secret_key
        self.webhook_secret = settings.stripe_webhook_secret

        # 验证必需配置
        if not self.secret_key:
            raise ValueError(
                "Stripe 配置不完整。请设置以下环境变量：\n"
                "- STRIPE_SECRET_KEY\n"
                "- STRIPE_WEBHOOK_SECRET（用于回调验证）"
            )

        stripe.api_key = self.secret_key

        StripeAdapter._initialized = True

    @property
    def provider(self) -> Provider:
        return Provider.stripe

    async def create_payment(
        self,
        *,
        amount: int,
        currency: str,
        merchant_order_no: str,
        description: str,
        notify_url: str,
        expire_minutes: int | None = None,
    ) -> ProviderPaymentResult:
        """
        创建 Stripe PaymentIntent

        参考：https://docs.stripe.com/payments/quickstart
        """
        # todo：人民币有最低限额

        # Stripe 金额单位：分（最小货币单位）
        # 对于 USD/EUR 等，1 USD = 100 cents
        payment_intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=currency.lower(),
            description=description,
            metadata={
                "merchant_user_id": 1,
                "merchant_order_no": merchant_order_no,
            },
            # Stripe 不直接支持过期时间，但可以通过 cancel 来实现
            # v1 暂不实现渠道侧过期，由网关 worker 扫描
        )

        return ProviderPaymentResult(
            type=PaymentTypeEnum.client_secret,
            payload={
                "client_secret": payment_intent.client_secret,
                # "amount": payment_intent.amount,
                # "currency": payment_intent.currency,
            },
            provider_txn_id=payment_intent.id,
        )

    async def confirm_payment(self, payment_id: uuid, txn_id: str):
        try:
            payment_intent = stripe.PaymentIntent.retrieve(txn_id)
            # 如果 Stripe 侧已经是成功状态，跳过 confirm
            if payment_intent.status == "succeeded":
                print("stripe_payment_intent_already_succeeded")
            elif payment_intent.status in [
                "requires_payment_method",
                "requires_confirmation",
                "requires_action",
            ]:
                # 需要 confirm 的状态，根据 PaymentIntent 配置构造参数
                # 参考：https://docs.stripe.com/payments/paymentintents
                print(
                    f"confirming_stripe_payment_intent：{txn_id=} status={payment_intent.status}"
                )

                # 构造 confirm 参数
                confirm_params = {}

                # 1. 如果 PaymentIntent 没有绑定 payment_method，提供测试卡
                if not payment_intent.payment_method:
                    confirm_params["payment_method"] = "pm_card_visa"  # Stripe 测试卡
                    print("using_test_payment_method")

                # 2. 提供 return_url（某些支付方式可能需要重定向）
                confirm_params["return_url"] = (
                    f"http://localhost:8000/test/payment-return?payment_id={payment_id}"
                )
                print(f"providing_return_url: {confirm_params['return_url']}")

                # 3. 调用 Stripe API confirm
                stripe.PaymentIntent.confirm(txn_id, **confirm_params)
                print("stripe_payment_intent_confirmed")
        except stripe.error.StripeError:
            traceback.print_exc()

        # 4. 再次检查状态，确保支付真的成功了
        try:
            payment_intent = stripe.PaymentIntent.retrieve(txn_id)
            final_status = payment_intent.status

            # 检查是否真的成功
            if final_status != "succeeded":
                # 如果不是 succeeded，可能需要额外操作（如 3D 验证）
                raise ValueError(
                    f"PaymentIntent status is '{final_status}', not 'succeeded'. "
                    f"May require additional authentication or action."
                )
        except stripe.error.StripeError as e:
            raise ValueError(f"Failed to retrieve final PaymentIntent status: {str(e)}")

    async def create_refund(
        self,
        *,
        txn_id: str,
        refund_amount: int | None = None,
        reason: str | None = None,
    ) -> dict:
        """
        创建 Stripe 退款

        参考：https://docs.stripe.com/api/refunds/create

        Args:
            txn_id: Stripe PaymentIntent ID
            refund_amount: 退款金额（分），None 表示全额退款
            reason: 退款原因，可选值：'duplicate', 'fraudulent', 'requested_by_customer'

        Returns:
            包含退款信息的字典，包括 refund_id 和 status
        """
        try:
            # 构造退款参数
            refund_params = {
                "payment_intent": txn_id,
            }

            # 如果指定了退款金额（部分退款）
            if refund_amount is not None:
                refund_params["amount"] = refund_amount

            # 如果提供了退款原因
            if reason:
                # Stripe 支持的原因类型：duplicate, fraudulent, requested_by_customer
                # 如果是自定义原因，我们使用 requested_by_customer
                stripe_reason = "requested_by_customer"
                if reason in ["duplicate", "fraudulent", "requested_by_customer"]:
                    stripe_reason = reason
                refund_params["reason"] = stripe_reason

            # 调用 Stripe API 创建退款
            refund = stripe.Refund.create(**refund_params)

            return {
                "refund_id": refund.id,
                "status": refund.status,  # 'succeeded', 'pending', 'failed'
                "amount": refund.amount,
                "currency": refund.currency,
                "payment_intent": refund.payment_intent,
                "reason": refund.get("reason"),
                "created": refund.created,
            }

        except stripe.error.StripeError as e:
            traceback.print_exc()
            raise ValueError(f"Stripe refund failed: {str(e)}")

    async def cancel_payment(
        self,
        *,
        merchant_order_no: str,
        provider_txn_id: str | None = None,
    ) -> dict:
        """
        取消 Stripe PaymentIntent

        参考：https://docs.stripe.com/api/payment_intents/cancel

        注意：只能取消状态为 requires_payment_method, requires_capture,
        requires_confirmation, requires_action, processing 的 PaymentIntent

        参数：
            merchant_order_no: 商户订单号（用于从 metadata 查找）
            provider_txn_id: Stripe PaymentIntent ID，如果提供则直接使用

        返回：
            {
                "success": True/False,
                "payment_intent_id": "pi_xxx",
                "status": "canceled",
                "cancellation_reason": "requested_by_customer"
            }
        """
        try:
            payment_intent_id = provider_txn_id

            # 如果没有提供 provider_txn_id，需要通过 merchant_order_no 查找
            if not payment_intent_id:
                # Stripe 不支持直接通过 metadata 查询，这里需要从数据库查找
                # 或者要求调用方必须提供 provider_txn_id
                raise ValueError(
                    "Stripe cancel_payment 需要提供 provider_txn_id (PaymentIntent ID)"
                )

            # 调用 Stripe API 取消 PaymentIntent
            payment_intent = stripe.PaymentIntent.cancel(
                payment_intent_id, cancellation_reason="requested_by_customer"
            )

            return {
                "success": True,
                "payment_intent_id": payment_intent.id,
                "status": payment_intent.status,  # 应该是 'canceled'
                "cancellation_reason": payment_intent.cancellation_reason,
                "amount": payment_intent.amount,
                "currency": payment_intent.currency,
            }

        except stripe.error.InvalidRequestError as e:
            # PaymentIntent 已经完成或无法取消
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "message": "PaymentIntent 无法取消（可能已完成或状态不允许）",
            }
        except stripe.error.StripeError as e:
            traceback.print_exc()
            raise ValueError(f"Stripe cancel payment failed: {str(e)}")

    async def get_refund(self, refund_id: str) -> dict:
        """
        查询 Stripe 退款状态

        参考：https://docs.stripe.com/api/refunds/retrieve

        Args:
            refund_id: Stripe Refund ID

        Returns:
            包含退款信息的字典
        """
        try:
            refund = stripe.Refund.retrieve(refund_id)

            return {
                "refund_id": refund.id,
                "status": refund.status,
                "amount": refund.amount,
                "currency": refund.currency,
                "payment_intent": refund.payment_intent,
                "reason": refund.get("reason"),
                "created": refund.created,
            }

        except stripe.error.StripeError as e:
            traceback.print_exc()
            raise ValueError(f"Failed to retrieve Stripe refund: {str(e)}")

    async def parse_and_verify_callback(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> CallbackEvent:
        """
        验证并解析 Stripe Webhook

        参考：https://docs.stripe.com/webhooks
        """
        if not self.webhook_secret:
            raise ValueError("Stripe webhook_secret not configured")

        sig_header = headers.get("stripe-signature")
        if not sig_header:
            raise ValueError("Missing Stripe-Signature header")

        try:
            event = stripe.Webhook.construct_event(
                payload=body,
                sig_header=sig_header,
                secret=self.webhook_secret,
            )
        except stripe.error.SignatureVerificationError as e:
            raise ValueError(f"Stripe signature verification failed: {e}")

        # 解析事件
        event_type = event["type"]
        payment_intent = event["data"]["object"]

        provider_event_id = event["id"]
        provider_txn_id = payment_intent.get("id")
        merchant_order_no = payment_intent.get("metadata", {}).get("merchant_order_no")

        # 映射 Stripe 事件到我们的 outcome
        outcome_map = {
            "payment_intent.succeeded": "succeeded",
            "payment_intent.payment_failed": "failed",
            "payment_intent.canceled": "canceled",
        }
        outcome = outcome_map.get(event_type, "unknown")

        return CallbackEvent(
            provider_event_id=provider_event_id,
            provider_txn_id=provider_txn_id,
            merchant_order_no=merchant_order_no,
            outcome=outcome,
            raw_payload=event,
        )


# 延迟初始化单例实例（只在首次访问时创建）
_stripe_adapter_instance = None


def get_stripe_adapter() -> StripeAdapter:
    """获取 Stripe 适配器单例"""
    global _stripe_adapter_instance
    if _stripe_adapter_instance is None:
        _stripe_adapter_instance = StripeAdapter()
    return _stripe_adapter_instance
