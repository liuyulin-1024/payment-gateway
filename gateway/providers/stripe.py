"""
Stripe Provider Adapter
"""

import time
import uuid
import stripe
import traceback

from gateway.core.logging import get_logger
from gateway.core.constants import Provider
from gateway.core.settings import get_settings
from gateway.core.schemas import PaymentTypeEnum, CallbackEvent
from .base import ProviderAdapter, ProviderPaymentResult, PaymentFlowType


settings = get_settings()
logger = get_logger()


class StripeAdapter(ProviderAdapter):
    """Stripe 支付适配器"""

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

    @property
    def supported_flows(self) -> list[PaymentFlowType]:
        """Stripe 仅支持 Checkout 托管支付流程"""
        return [PaymentFlowType.HOSTED]

    async def create_payment(
        self,
        *,
        currency: str,
        merchant_order_no: str,
        quantity: int,
        notify_url: str,
        expire_minutes: int | None = None,
        unit_amount: int | None = None,
        product_name: str | None = None,
        product_desc: str | None = None,
        **kwargs,
    ) -> ProviderPaymentResult:
        """
        创建 Stripe 托管支付（Checkout Session）
        
        这是 Stripe 推荐的集成方式，提供：
        - 完整的支付 UI（无需前端开发）
        - 自动支持多种支付方式（卡支付、支付宝、微信支付等）
        - 自动处理 3D Secure 验证
        - 移动端友好
        
        Args:
            currency: 货币代码（如 USD, CNY）
            merchant_order_no: 商户订单号
            quantity: 数量
            notify_url: 回调通知 URL（Stripe 使用 webhook）
            expire_minutes: 过期时间（Stripe Session 默认 24 小时）
            unit_amount: 单价（最小货币单位，如分）
            product_name: 商品名称
            product_desc: 商品描述
            
            **kwargs: 额外参数
                - success_url: 支付成功跳转 URL
                - cancel_url: 取消支付跳转 URL
                - metadata: 额外的元数据
        
        Returns:
            ProviderPaymentResult: 包含 session_id 和 checkout_url
        
        参考：https://docs.stripe.com/payments/checkout
        """
        # 从 kwargs 中提取可选参数
        success_url = kwargs.get("success_url")
        cancel_url = kwargs.get("cancel_url")
        metadata = kwargs.get("metadata")
        customer_email = metadata.get('customer_email')
        payment_method_types = kwargs.get("payment_method_types")  # 手动指定支付方式
        
        logger.info(
            f"开始创建Stripe Checkout Session - 订单号: {merchant_order_no}, "
            f"单价: {unit_amount}, 数量: {quantity}, 货币: {currency}"
        )

        # 准备元数据
        session_metadata = {
            "merchant_order_no": merchant_order_no,
            **(metadata or {}),
        }

        # 构造 Session 参数（基础部分）
        session_data = {
            "mode": "payment",
            "customer_email": customer_email,
            "line_items": [
                {
                    "quantity": quantity,
                    "price_data": {
                        "currency": currency.lower(),
                        "unit_amount": unit_amount,
                        "product_data": {
                            "name": (product_name or "商品")[:250],  # Stripe 限制
                            "description": product_desc[:500] if product_desc else None,
                        },
                    },
                }
            ],
            "metadata": session_metadata,
            # 将 metadata 同时传递到 PaymentIntent
            "payment_intent_data": {"metadata": session_metadata},
            "success_url": success_url or "https://example.com/success?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": cancel_url or "https://example.com/cancel",
        }
        
        # 配置支付方式（默认使用手动指定）
        if payment_method_types:
            # 用户指定的支付方式
            session_data["payment_method_types"] = payment_method_types
            logger.info(f"使用指定支付方式: {', '.join(payment_method_types)}")
        else:
            # 默认支付方式：card（信用卡）
            session_data["payment_method_types"] = ["card"]
            logger.info("使用默认支付方式: card")

        # 如果指定了过期时间
        if expire_minutes:
            # Stripe Session 最短 30 分钟，最长 24 小时
            expire_seconds = max(1800, min(expire_minutes * 60, 86400))
            session_data["expires_at"] = int(time.time() + expire_seconds)

        logger.info(f"Stripe 下单参数：{session_data}")

        try:
            session = stripe.checkout.Session.create(**session_data)

            logger.info(
                f"Stripe Checkout Session 创建成功 - ID: {session.id}, "
                f"URL: {session.url}, "
                f"支付方式: {', '.join(session.payment_method_types or [])}"
            )

            return ProviderPaymentResult(
                type=PaymentTypeEnum.url,
                payload={
                    "checkout_url": session.url,
                    "session_id": session.id,
                },
                provider_txn_id=session.payment_intent if isinstance(session.payment_intent, str) else None,
            )

        except stripe.error.InvalidRequestError as e:
            # 处理参数错误（如不支持的支付方式）
            error_msg = str(e)
            logger.error(f"Stripe 请求参数错误：{error_msg}")
            
            # 如果是支付方式相关错误，尝试回退到只使用 card
            if "payment_method" in error_msg.lower() and session_data.get("payment_method_types") != ["card"]:
                logger.warning("回退为仅使用 card 支付方式")
                session_data["payment_method_types"] = ["card"]
                try:
                    session = stripe.checkout.Session.create(**session_data)
                    logger.info(f"回退方式创建成功 - ID: {session.id}")
                    return ProviderPaymentResult(
                        type=PaymentTypeEnum.url,
                        payload={
                            "checkout_url": session.url,
                            "session_id": session.id,
                        },
                        provider_txn_id=session.payment_intent if isinstance(session.payment_intent, str) else None,
                    )
                except stripe.StripeError as retry_error:
                    logger.error(f"回退创建失败: {str(retry_error)}")
                    traceback.print_exc()
                    raise
            else:
                traceback.print_exc()
                raise
                
        except stripe.StripeError as e:
            error_msg = e.user_message if hasattr(e, "user_message") else str(e)
            logger.error(f"Stripe Checkout Session 创建失败：{error_msg}")
            traceback.print_exc()
            raise

    async def create_refund(
        self,
        *,
        txn_id: str,
        refund_amount: int | None = None,
        reason: str | None = None,
    ) -> dict:
        """
        创建 Stripe 退款

        Args:
            txn_id: Stripe PaymentIntent ID
            refund_amount: 退款金额（分），None 表示全额退款
            reason: 退款原因，可选值：'duplicate', 'fraudulent', 'requested_by_customer'

        Returns:
            包含退款信息的字典，包括 refund_id 和 status

        参考：https://docs.stripe.com/api/refunds/create
        """
        try:
            # 构造退款参数
            refund_params = {
                "payment_intent": txn_id,
            }

            # 如果指定了退款金额（部分退款）
            if refund_amount is not None:
                refund_params["amount"] = refund_amount
                logger.info(f"创建部分退款 - PaymentIntent: {txn_id}, 金额: {refund_amount}")
            else:
                logger.info(f"创建全额退款 - PaymentIntent: {txn_id}")

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

            logger.info(
                f"退款创建成功 - Refund ID: {refund.id}, "
                f"状态: {refund.status}, "
                f"金额: {refund.amount} {refund.currency.upper()}"
            )

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
            logger.error(f"Stripe 退款失败 - PaymentIntent: {txn_id}, 错误: {str(e)}")
            traceback.print_exc()
            raise ValueError(f"Stripe 退款失败: {str(e)}")

    async def cancel_payment(
        self,
        *,
        merchant_order_no: str,
        provider_txn_id: str | None = None,
    ) -> dict:
        """
        取消 Stripe PaymentIntent

        注意：只能取消状态为 requires_payment_method, requires_capture,
        requires_confirmation, requires_action, processing 的 PaymentIntent

        Args:
            merchant_order_no: 商户订单号（用于从 metadata 查找）
            provider_txn_id: Stripe PaymentIntent ID，如果提供则直接使用

        Returns:
            包含取消结果的字典：
            {
                "success": True/False,
                "payment_intent_id": "pi_xxx",
                "status": "canceled",
                "cancellation_reason": "requested_by_customer"
            }

        参考：https://docs.stripe.com/api/payment_intents/cancel
        """
        try:
            payment_intent_id = provider_txn_id

            # 如果没有提供 provider_txn_id，需要通过 merchant_order_no 查找
            if not payment_intent_id:
                # Stripe 不支持直接通过 metadata 查询，这里需要从数据库查找
                # 或者要求调用方必须提供 provider_txn_id
                raise ValueError("Stripe cancel_payment 需要提供 provider_txn_id (PaymentIntent ID)")

            logger.info(f"开始取消 PaymentIntent - ID: {payment_intent_id}, 订单号: {merchant_order_no}")

            # 调用 Stripe API 取消 PaymentIntent
            payment_intent = stripe.PaymentIntent.cancel(
                payment_intent_id, cancellation_reason="requested_by_customer"
            )

            logger.info(
                f"PaymentIntent 取消成功 - ID: {payment_intent.id}, "
                f"状态: {payment_intent.status}, "
                f"原因: {payment_intent.cancellation_reason}"
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
            logger.warning(
                f"PaymentIntent 无法取消 - ID: {provider_txn_id}, "
                f"订单号: {merchant_order_no}, 错误: {str(e)}"
            )
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "message": "PaymentIntent 无法取消（可能已完成或状态不允许）",
            }
        except stripe.error.StripeError as e:
            logger.error(f"取消 PaymentIntent 失败 - ID: {provider_txn_id}, 错误: {str(e)}")
            traceback.print_exc()
            raise ValueError(f"Stripe 取消支付失败: {str(e)}")

    async def get_refund(self, refund_id: str) -> dict:
        """
        查询 Stripe 退款状态

        Args:
            refund_id: Stripe Refund ID

        Returns:
            包含退款信息的字典

        参考：https://docs.stripe.com/api/refunds/retrieve
        """
        try:
            refund = stripe.Refund.retrieve(refund_id)

            logger.info(
                f"退款查询成功 - Refund ID: {refund.id}, "
                f"状态: {refund.status}, "
                f"金额: {refund.amount} {refund.currency.upper()}"
            )

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
            logger.error(f"查询Stripe退款失败 - Refund ID: {refund_id}, 错误: {str(e)}")
            traceback.print_exc()
            raise ValueError(f"查询 Stripe 退款失败: {str(e)}")

    async def parse_and_verify_callback(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> CallbackEvent:
        """
        验证并解析 Stripe Webhook

        支持的事件类型：
        - checkout.session.completed: Checkout Session 完成
        - checkout.session.async_payment_succeeded: 异步支付成功（Alipay等）
        - checkout.session.async_payment_failed: 异步支付失败
        - checkout.session.expired: Session 过期（网关统一视为 canceled）

        Args:
            headers: HTTP 请求头
            body: HTTP 请求体（原始字节）

        Returns:
            CallbackEvent: 解析后的回调事件

        参考：https://docs.stripe.com/webhooks
        """
        if not self.webhook_secret:
            logger.error("未配置 Stripe webhook_secret")
            raise ValueError("Stripe webhook_secret not configured")

        sig_header = headers.get("stripe-signature")
        if not sig_header:
            logger.error("缺少 Stripe-Signature 请求头")
            raise ValueError("Missing Stripe-Signature header")

        try:
            event = stripe.Webhook.construct_event(
                payload=body,
                sig_header=sig_header,
                secret=self.webhook_secret,
            )
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Stripe 签名验证失败: {str(e)}")
            raise ValueError(f"Stripe signature verification failed: {e}")

        # 解析事件
        event_type = event["type"]
        event_data = event["data"]["object"]
        provider_event_id = event["id"]

        logger.info(f"收到Stripe Webhook事件 - 类型: {event_type}, ID: {provider_event_id}")

        if not event_type.startswith("checkout.session"):
            logger.warning(f"忽略非 Checkout 事件类型: {event_type}")
            raise ValueError(f"Unsupported Stripe event type: {event_type}")

        # 仅处理 Checkout Session 事件
        provider_txn_id, merchant_order_no, outcome = self._parse_checkout_event(
            event_type, event_data
        )

        logger.info(
            f"Webhook 事件解析完成 - 结果: {outcome}, "
            f"订单号: {merchant_order_no}, "
            f"交易ID: {provider_txn_id}"
        )

        return CallbackEvent(
            provider_event_id=provider_event_id,
            provider_txn_id=provider_txn_id,
            merchant_order_no=merchant_order_no,
            outcome=outcome,
            raw_payload=event,
        )

    def _parse_checkout_event(
        self, event_type: str, event_data: dict
    ) -> tuple[str | None, str | None, str]:
        # Checkout Session 事件
        provider_txn_id = event_data.get("payment_intent")
        merchant_order_no = event_data.get("metadata", {}).get("merchant_order_no")

        # Checkout Session 完成：无论是否有 payment_intent，都以 payment_status 为准
        if event_type == "checkout.session.completed":
            payment_status = event_data.get("payment_status")
            if payment_status == "paid":
                outcome = "succeeded"
            elif payment_status == "unpaid":
                # 异步支付方式（如 Alipay）常见：Session completed 但尚未支付完成
                outcome = "pending"
            else:
                outcome = "unknown"
        else:
            # 其他 Checkout Session 事件
            outcome_map = {
                "checkout.session.async_payment_succeeded": "succeeded",
                "checkout.session.async_payment_failed": "failed",
                "checkout.session.expired": "canceled",
            }
            outcome = outcome_map.get(event_type, "unknown")

        return provider_txn_id, merchant_order_no, outcome


# 延迟初始化单例实例（只在首次访问时创建）
_stripe_adapter_instance = None


def get_stripe_adapter() -> StripeAdapter:
    """获取 Stripe 适配器单例"""
    global _stripe_adapter_instance
    if _stripe_adapter_instance is None:
        _stripe_adapter_instance = StripeAdapter()
    return _stripe_adapter_instance
