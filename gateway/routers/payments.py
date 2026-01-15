"""
支付 API 路由
"""

import uuid
import structlog
from fastapi import APIRouter, Depends, Header, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.core.models import App
from gateway.db import get_session
from gateway.providers import get_adapter
from gateway.core.settings import get_settings
from gateway.core.auth import get_app_from_api_key
from gateway.services.payments import PaymentService
from gateway.core.schemas import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    PaymentResponse,
)
from gateway.core.responses import success_response


logger = structlog.get_logger(__name__)
settings = get_settings()

router = APIRouter()

# API Key 安全方案定义（用于 Swagger UI 显示）
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@router.post("/payments")
async def create_payment(
    req: CreatePaymentRequest,
    app: App = Depends(get_app_from_api_key),
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    api_key: str = Security(api_key_header),
):
    """
    创建支付（统一下单）

    - 幂等：以 (app_id, merchant_order_no) 为准
    - 返回：混合类型（type + payload）
    - 鉴权：需要在请求头中提供 X-API-Key
    """
    log = logger.bind(
        app_id=str(app.id),
        merchant_order_no=req.merchant_order_no,
        provider=req.provider.value,
        idempotency_key=idempotency_key,
    )

    log.info("收到创建支付请求")

    payment_service = PaymentService(session)

    # 创建或获取支付
    payment, is_new = await payment_service.create_or_get_payment(
        app=app,
        req=req,
        idempotency_key=idempotency_key,
    )

    # 如果是新创建的支付，调用 provider 下单
    if is_new:
        provider_adapter = get_adapter(req.provider)
        expire_minutes = req.expire_minutes or settings.payment_expire_minutes_default

        result = await provider_adapter.create_payment(
            currency=req.currency.value,
            merchant_order_no=req.merchant_order_no,
            quantity=req.quantity,
            notify_url=payment.notify_url,
            expire_minutes=expire_minutes,
            unit_amount=req.unit_amount,
            product_name=req.product_name,
            product_desc=req.product_desc,
            success_url=req.success_url,
            cancel_url=req.cancel_url,
            metadata=req.metadata,
        )

        # 更新 provider_txn_id（如果渠道返回）
        if result.provider_txn_id:
            payment.provider_txn_id = result.provider_txn_id
            await session.commit()

        log.info(
            "创建支付成功",
            payment_id=str(payment.id),
            type=result.type.value,
        )

        response_data = CreatePaymentResponse(
            payment_id=payment.id,
            merchant_order_no=payment.merchant_order_no,
            status=payment.status,
            type=result.type,
            payload=result.payload,
        )
        return success_response(data=response_data.model_dump(mode='json'), msg="创建支付成功")
    else:
        # 幂等返回：需要重新生成 payload（简化：返回空 payload）
        log.info("支付幂等返回", payment_id=str(payment.id))

        # TODO: 从 payment 状态恢复 type/payload（v1 简化为返回空）
        response_data = CreatePaymentResponse(
            payment_id=payment.id,
            merchant_order_no=payment.merchant_order_no,
            status=payment.status,
            type="redirect",  # 占位
            payload={"message": "Payment already exists"},
        )
        return success_response(data=response_data.model_dump(mode='json'), msg="支付已存在（幂等返回）")


@router.get("/payments/{payment_id}")
async def get_payment_by_id(
    payment_id: uuid.UUID,
    app: App = Depends(get_app_from_api_key),
    session: AsyncSession = Depends(get_session),
    api_key: str = Security(api_key_header),
):
    """
    按 payment_id 查询支付

    - 鉴权：需要在请求头中提供 X-API-Key
    """
    payment_service = PaymentService(session)
    payment = await payment_service.get_payment_by_id(app, payment_id)
    response_data = PaymentResponse.model_validate(payment)
    return success_response(data=response_data.model_dump(mode='json'), msg="查询成功")


@router.get("/payments/by-merchant-order/{merchant_order_no}")
async def get_payment_by_merchant_order_no(
    merchant_order_no: str,
    app: App = Depends(get_app_from_api_key),
    session: AsyncSession = Depends(get_session),
    api_key: str = Security(api_key_header),
):
    """
    按 merchant_order_no 查询支付

    - 鉴权：需要在请求头中提供 X-API-Key
    """
    payment_service = PaymentService(session)
    payment = await payment_service.get_payment_by_merchant_order_no(
        app, merchant_order_no
    )
    response_data = PaymentResponse.model_validate(payment)
    return success_response(data=response_data.model_dump(mode='json'), msg="查询成功")
