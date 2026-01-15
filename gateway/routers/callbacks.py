"""
渠道回调 API 路由
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Request, Response, Depends

from gateway.db import get_session
from gateway.core.constants import Provider
from gateway.providers.stripe import get_stripe_adapter
from gateway.providers.alipay import get_alipay_adapter
from gateway.services.callbacks import CallbackService
from gateway.core.exceptions import IgnoredException


logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/stripe")
async def stripe_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """
    Stripe Webhook 回调

    注意：不需要鉴权（Stripe 通过 signature 验签）
    """
    body = await request.body()
    headers = dict(request.headers)
    log = logger.bind(provider="stripe")
    log.info(f"收到回调原始内容: {body}")

    try:
        event = await get_stripe_adapter().parse_and_verify_callback(headers, body)
        event.raw_payload["provider"] = Provider.stripe.value
        log.info(f"回调解析完成: {event.model_dump()}")

        # 处理回调
        callback_service = CallbackService(session)
        await callback_service.process_callback(event)

        return Response(status_code=200)
    except IgnoredException as err:
        logger.warning(str(err))
        return Response(status_code=200)
    except Exception as exc:
        log.error("回调处理失败", error=str(exc), exc_info=True)
        return Response(status_code=500)


@router.post("/alipay")
async def alipay_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """支付宝回调"""
    body = await request.body()
    headers = dict(request.headers)

    log = logger.bind(provider="alipay")
    log.info(f"收到回调原始内容: {body}")

    try:
        event = await get_alipay_adapter().parse_and_verify_callback(headers, body)
        event.raw_payload["provider"] = Provider.alipay.value
        log.info(f"回调解析完成: {event.model_dump()}")

        # 处理回调
        callback_service = CallbackService(session)
        await callback_service.process_callback(event)
        return Response(status_code=200)
    except Exception as exc:
        log.error("回调处理失败", error=str(exc), exc_info=True)
        return Response(status_code=500)


@router.post("/wechatpay")
async def wechatpay_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """微信支付 APIv3 回调"""
    body = await request.body()
    headers = dict(request.headers)

    log = logger.bind(provider="wechatpay")
    log.info(f"收到回调原始内容: {body} {headers}")

    try:
        # FIXME: 同 Stripe，需要动态加载配置
        return Response(status_code=200, content='{"code": "SUCCESS", "message": "OK"}')

    except Exception as exc:
        log.error("回调处理失败", error=str(exc), exc_info=True)
        return Response(status_code=500)
