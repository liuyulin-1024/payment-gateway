"""
管理 API 路由
"""

import uuid
import structlog
from fastapi import APIRouter, Depends, Query, Body, HTTPException

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..services.apps import AppService
from ..services.refunds import RefundService
from gateway.core.models import Payment
from gateway.core.schemas import (
    CallbackEvent,
    CreateRefundRequest,
    RefundResponse,
    RefundListResponse,
)
from gateway.services.callbacks import CallbackService
from gateway.core.constants import PaymentStatus, Provider
from gateway.core.schemas import CreateAppRequest, AppResponse, AppListResponse

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/apps", response_model=AppResponse, status_code=201)
async def create_app(
    req: CreateAppRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    创建应用

    创建一个新的应用并自动生成 API Key。

    - **name**: 应用名称（必填，唯一）
    - **notify_url**: 默认支付结果回调通知地址（可选）

    返回创建的应用信息，包括生成的 API Key。
    """
    log = logger.bind(name=req.name)
    log.info("create_app_request")

    app_service = AppService(session)
    app = await app_service.create_app(req)

    log.info("create_app_success", app_id=str(app.id))
    return AppResponse.model_validate(app)


@router.get("/apps", response_model=AppListResponse)
async def list_apps(
    skip: int = Query(0, ge=0, description="跳过的记录数"),
    limit: int = Query(100, ge=1, le=1000, description="返回的最大记录数"),
    session: AsyncSession = Depends(get_session),
):
    """
    列举所有应用

    返回应用列表，支持分页。

    - **skip**: 跳过的记录数（用于分页，默认 0）
    - **limit**: 返回的最大记录数（默认 100，最大 1000）
    """
    logger.info("list_apps_request", skip=skip, limit=limit)

    app_service = AppService(session)
    apps, total = await app_service.list_apps(skip=skip, limit=limit)

    logger.info("list_apps_success", total=total, returned=len(apps))
    return AppListResponse(
        total=total, items=[AppResponse.model_validate(app) for app in apps]
    )


@router.get("/apps/{app_id}", response_model=AppResponse)
async def get_app(
    app_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """
    获取应用详情

    根据应用 ID 获取应用的详细信息。
    """
    logger.info("get_app_request", app_id=str(app_id))

    app_service = AppService(session)
    app = await app_service.get_app_by_id(app_id)

    logger.info("get_app_success", app_id=str(app_id))
    return AppResponse.model_validate(app)


@router.delete("/apps/{app_id}", status_code=204)
async def delete_app(
    app_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """
    删除应用

    根据应用 ID 删除应用。注意：删除应用会影响该应用下的所有支付记录。
    """
    logger.info("delete_app_request", app_id=str(app_id))

    app_service = AppService(session)
    await app_service.delete_app(app_id)

    logger.info("delete_app_success", app_id=str(app_id))


@router.patch("/apps/{app_id}/status", response_model=AppResponse)
async def update_app_status(
    app_id: uuid.UUID,
    is_active: bool = Query(..., description="是否启用应用"),
    session: AsyncSession = Depends(get_session),
):
    """
    更新应用状态

    启用或禁用应用。禁用的应用无法进行支付操作。

    - **is_active**: true 启用，false 禁用
    """
    logger.info("update_app_status_request", app_id=str(app_id), is_active=is_active)

    app_service = AppService(session)
    app = await app_service.update_app_status(app_id, is_active)

    logger.info("update_app_status_success", app_id=str(app_id), is_active=is_active)
    return AppResponse.model_validate(app)


@router.post("/payments/{payment_id}/test-success", summary="模拟支付成功")
async def test_payment_success(
    payment_id: uuid.UUID,
    provider: Provider = Body(embed=True),
    session: AsyncSession = Depends(get_session),
):
    """
    测试接口：直接模拟支付成功（仅用于开发测试）

    ### 功能
    - 查找对应的支付记录
    - 模拟 Stripe 支付成功（如果是 Stripe 支付）
    - 构造标准化的回调事件
    - 触发内部 webhook 处理流程
    - 更新支付状态并生成 webhook 投递任务

    ### 注意
    - 此接口仅用于测试环境
    - 生产环境应该删除或禁用
    - 仅支持 Stripe 支付渠道

    ### 返回
    - 支付状态更新结果
    - webhook 投递任务创建状态

    ### 示例
    ```bash
    curl -X POST http://localhost:8000/admin/payments/{payment_id}/test-success
    ```
    """

    log = logger.bind(payment_id=str(payment_id))
    log.info("test_payment_success_request")

    # 1. 查找支付记录
    stmt = select(Payment).where(Payment.id == payment_id)
    result = await session.execute(stmt)
    payment = result.scalar_one_or_none()

    if not payment:
        log.warning("payment_not_found")
        raise HTTPException(status_code=404, detail="Payment not found")

    # 2. 检查当前状态
    if payment.status == PaymentStatus.succeeded:
        log.info("payment_already_succeeded")
        return {
            "success": True,
            "message": "Payment already succeeded",
            "payment_id": str(payment.id),
            "status": payment.status.value,
            "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        }

    # 3. 检查支付渠道
    match provider:
        case Provider.stripe:
            # 4. 在 Stripe 侧真实完成支付（用于测试）
            provider_txn_id = payment.provider_txn_id
            if not provider_txn_id:
                log.warning(
                    "payment_missing_provider_txn_id", payment_id=str(payment_id)
                )
                # 如果没有 provider_txn_id，无法在 Stripe 侧操作
                raise HTTPException(
                    status_code=400,
                    detail="Payment does not have provider_txn_id, cannot test on Stripe",
                )
            from gateway.providers.stripe import get_stripe_adapter

            await get_stripe_adapter().confirm_payment(payment_id, provider_txn_id)

        case _:
            log.warning("unsupported_provider", provider=payment.provider.value)
            raise HTTPException(
                status_code=400,
                detail=f"Test endpoint only supports Stripe, got {payment.provider.value}",
            )

    # 6. 构造标准化的 CallbackEvent（基于真实的 Stripe 状态）
    # 参考：https://docs.stripe.com/webhooks
    event_id = f"evt_test_{payment_id}_{int(__import__('time').time())}"
    callback_event = CallbackEvent(
        provider_event_id=event_id,
        provider_txn_id=provider_txn_id,
        merchant_order_no=payment.merchant_order_no,
        outcome="succeeded",  # 已确认 Stripe 侧成功
        raw_payload={
            "id": event_id,
            "object": "event",
            "type": "payment_intent.succeeded",
            "provider": "stripe",
            "data": {
                "object": {
                    "id": provider_txn_id,
                    "object": "payment_intent",
                    "amount": payment.amount,
                    "currency": payment.currency.value,
                    "status": "succeeded",
                    "metadata": {
                        "merchant_order_no": payment.merchant_order_no,
                    },
                }
            },
        },
    )

    # 7. 调用 CallbackService 处理回调（触发状态更新和 webhook 投递）
    callback_service = CallbackService(session)
    try:
        await callback_service.process_callback(callback_event)
        log.info("callback_processed_successfully")
    except Exception as e:
        log.error("callback_processing_failed", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to process callback: {str(e)}"
        )

    # 8. 刷新支付记录以获取最新状态
    await session.refresh(payment)

    log.info(
        "test_payment_success_completed",
        new_status=payment.status.value,
        paid_at=payment.paid_at.isoformat() if payment.paid_at else None,
    )

    return {
        "success": True,
        "message": "Payment test success completed",
        "payment_id": str(payment.id),
        "merchant_order_no": payment.merchant_order_no,
        "status": payment.status.value,
        "amount": payment.amount,
        "currency": payment.currency.value,
        "provider_txn_id": payment.provider_txn_id,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        "test_mode": True,
    }


# ===== 退款管理 API =====


@router.post(
    "/refunds", response_model=RefundResponse, status_code=201, summary="创建退款"
)
async def create_refund(
    req: CreateRefundRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    创建退款（支持全额退款和部分退款）
    
    ### 功能
    - 创建退款请求
    - 支持全额退款（不传 refund_amount）和部分退款
    - 验证支付状态和退款金额
    - 调用支付渠道退款接口
    - 记录退款结果
    
    ### 业务规则
    1. 支付必须是成功状态（succeeded）
    2. 如果不指定退款金额，则为全额退款
    3. 部分退款时，累计退款金额不能超过支付金额
    4. 支持多次部分退款
    
    ### 参数
    - **payment_id**: 支付交易ID（必填）
    - **refund_amount**: 退款金额（最小货币单位，如分）。不填则为全额退款
    - **reason**: 退款原因（可选）
    
    ### 返回
    - 退款记录详情，包括退款ID、状态、金额等
    
    ### 示例
    ```bash
    # 全额退款
    curl -X POST http://localhost:8000/admin/refunds \\
      -H "Content-Type: application/json" \\
      -d '{
        "payment_id": "550e8400-e29b-41d4-a716-446655440000",
        "reason": "Customer requested refund"
      }'
    
    # 部分退款（退款 500 分 = 5 USD）
    curl -X POST http://localhost:8000/admin/refunds \\
      -H "Content-Type: application/json" \\
      -d '{
        "payment_id": "550e8400-e29b-41d4-a716-446655440000",
        "refund_amount": 500,
        "reason": "Partial refund"
      }'
    ```
    """
    log = logger.bind(payment_id=str(req.payment_id))
    log.info("create_refund_request")

    refund_service = RefundService(session)
    refund = await refund_service.create_refund(req)

    log.info("create_refund_success", refund_id=str(refund.id))
    return RefundResponse.model_validate(refund)


@router.get(
    "/refunds/{refund_id}", response_model=RefundResponse, summary="查询退款详情"
)
async def get_refund(
    refund_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """
    查询退款详情

    根据退款ID获取退款的详细信息。

    ### 参数
    - **refund_id**: 退款ID

    ### 返回
    - 退款记录详情
    """
    logger.info("get_refund_request", refund_id=str(refund_id))

    refund_service = RefundService(session)
    refund = await refund_service.get_refund(refund_id)

    logger.info("get_refund_success", refund_id=str(refund_id))
    return RefundResponse.model_validate(refund)


@router.get(
    "/payments/{payment_id}/refunds",
    response_model=RefundListResponse,
    summary="查询支付的退款记录",
)
async def list_refunds_by_payment(
    payment_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="跳过的记录数"),
    limit: int = Query(100, ge=1, le=1000, description="返回的最大记录数"),
    session: AsyncSession = Depends(get_session),
):
    """
    查询支付的所有退款记录

    返回指定支付的所有退款记录，支持分页。

    ### 参数
    - **payment_id**: 支付交易ID
    - **skip**: 跳过的记录数（用于分页，默认 0）
    - **limit**: 返回的最大记录数（默认 100，最大 1000）

    ### 返回
    - 退款记录列表和总数
    """
    logger.info(
        "list_refunds_request", payment_id=str(payment_id), skip=skip, limit=limit
    )

    refund_service = RefundService(session)
    refunds, total = await refund_service.list_refunds_by_payment(
        payment_id=payment_id,
        skip=skip,
        limit=limit,
    )

    logger.info("list_refunds_success", total=total, returned=len(refunds))
    return RefundListResponse(
        total=total, items=[RefundResponse.model_validate(refund) for refund in refunds]
    )


@router.post(
    "/refunds/{refund_id}/sync", response_model=RefundResponse, summary="同步退款状态"
)
async def sync_refund_status(
    refund_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """
    同步退款状态（从支付渠道）

    从支付渠道查询最新的退款状态并更新本地记录。

    ### 功能
    - 查询支付渠道的退款状态
    - 更新本地退款记录
    - 如果状态已经是最终状态，则跳过同步

    ### 参数
    - **refund_id**: 退款ID

    ### 返回
    - 更新后的退款记录详情

    ### 示例
    ```bash
    curl -X POST http://localhost:8000/admin/refunds/{refund_id}/sync
    ```
    """
    logger.info("sync_refund_status_request", refund_id=str(refund_id))

    refund_service = RefundService(session)
    refund = await refund_service.sync_refund_status(refund_id)

    logger.info(
        "sync_refund_status_success",
        refund_id=str(refund_id),
        status=refund.status.value,
    )
    return RefundResponse.model_validate(refund)
