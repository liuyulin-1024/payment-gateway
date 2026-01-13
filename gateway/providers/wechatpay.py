"""
微信支付 Native Adapter

https://pay.weixin.qq.com/doc/v3/merchant/4012791877
"""

import json
from datetime import datetime, timedelta, UTC

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from gateway.core.constants import Provider
from gateway.core.settings import get_settings
from gateway.core.schemas import PaymentTypeEnum, CallbackEvent
from .base import ProviderAdapter, ProviderPaymentResult


settings = get_settings()


class WeChatPayAdapter(ProviderAdapter):
    """
    微信支付 Native 适配器（单例模式）

    参考：https://pay.weixin.qq.com/doc/v3/merchant/4012791877

    注意：完整实现需要微信 APIv3 签名/验签逻辑，这里提供最小可跑版本
    实际生产中建议使用官方或社区维护的 SDK（如 wechatpayv3）
    """

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
        self.mchid = settings.wechatpay_mchid
        self.appid = settings.wechatpay_appid
        self.api_v3_key = settings.wechatpay_api_v3_key
        self.serial_no = settings.wechatpay_serial_no
        self.private_key_path = settings.wechatpay_private_key_path

        # 验证必需配置
        if not all(
            [
                self.mchid,
                self.appid,
                self.api_v3_key,
                self.serial_no,
                self.private_key_path,
            ]
        ):
            raise ValueError(
                "微信支付配置不完整。请设置以下环境变量：\n"
                "- WECHATPAY_MCHID\n"
                "- WECHATPAY_APPID\n"
                "- WECHATPAY_API_V3_KEY\n"
                "- WECHATPAY_SERIAL_NO\n"
                "- WECHATPAY_PRIVATE_KEY_PATH"
            )

        # 加载商户私钥（用于请求签名）
        with open(self.private_key_path, "rb") as f:
            self.private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend(),
            )

        self.http_client = httpx.AsyncClient(timeout=30.0)

        WeChatPayAdapter._initialized = True

    @property
    def provider(self) -> Provider:
        return Provider.wechatpay

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
        微信 Native 下单

        调用：POST /v3/pay/transactions/native
        返回：code_url（二维码内容）
        """
        url = "https://api.mch.weixin.qq.com/v3/pay/transactions/native"

        # 计算总金额（单价 * 数量）
        total_amount = (unit_amount or 0) * quantity

        # 构造请求体
        body = {
            "appid": self.appid,
            "mchid": self.mchid,
            "description": (product_name or product_desc or "商品")[:127],  # 最大 127 字符
            "out_trade_no": merchant_order_no,
            "notify_url": notify_url,
            "amount": {
                "total": total_amount,  # 单位：分
                "currency": currency,
            },
        }

        # 如果指定了过期时间，添加 time_expire（rfc3339 格式）
        if expire_minutes:
            expire_at = datetime.now(UTC) + timedelta(minutes=expire_minutes)
            body["time_expire"] = expire_at.strftime("%Y-%m-%dT%H:%M:%S+08:00")

        # 签名与请求（简化版，实际需完整 APIv3 签名逻辑）
        # 这里用占位实现，生产环境建议用 wechatpayv3 库
        headers = self._build_request_headers(
            "POST", "/v3/pay/transactions/native", json.dumps(body)
        )

        response = await self.http_client.post(url, json=body, headers=headers)
        response.raise_for_status()

        result = response.json()
        code_url = result.get("code_url")

        if not code_url:
            raise ValueError("WeChat Pay did not return code_url")

        return ProviderPaymentResult(
            type=PaymentTypeEnum.qr,
            payload={"code_url": code_url},
            provider_txn_id=None,  # 微信下单时不返回交易号，回调时才有
        )

    async def create_refund(
        self,
        *,
        txn_id: str,
        refund_amount: int | None = None,
        reason: str | None = None,
    ) -> dict:
        """
        创建微信支付退款
        
        参考：https://pay.weixin.qq.com/doc/v3/merchant/4012791877
        
        注意：完整实现需要调用微信退款API，这里是占位实现
        """
        # TODO: 实现微信支付退款逻辑
        # POST /v3/refund/domestic/refunds
        pass

    async def cancel_payment(
        self,
        *,
        merchant_order_no: str,
        provider_txn_id: str | None = None,
    ) -> dict:
        """
        关闭微信支付订单

        调用：POST /v3/pay/transactions/out-trade-no/{out_trade_no}/close
        参考：https://pay.weixin.qq.com/doc/v3/merchant/4012791877

        注意：订单只能在未支付状态下关闭

        参数：
            merchant_order_no: 商户订单号（必填）
            provider_txn_id: 微信交易号（可选，微信关闭订单只需要商户订单号）

        返回：
            {
                "success": True/False,
                "out_trade_no": "商户订单号",
                "message": "关闭成功/失败信息"
            }
        """
        if not merchant_order_no:
            raise ValueError("微信支付关闭订单需要提供 merchant_order_no")

        url = f"https://api.mch.weixin.qq.com/v3/pay/transactions/out-trade-no/{merchant_order_no}/close"

        # 构造请求体
        body = {"mchid": self.mchid}

        try:
            # 签名与请求（简化版）
            headers = self._build_request_headers(
                "POST",
                f"/v3/pay/transactions/out-trade-no/{merchant_order_no}/close",
                json.dumps(body),
            )

            response = await self.http_client.post(url, json=body, headers=headers)

            # 微信关闭订单成功时返回 204 No Content
            if response.status_code == 204:
                return {
                    "success": True,
                    "out_trade_no": merchant_order_no,
                    "message": "订单关闭成功",
                }

            # 其他情况视为失败
            result = response.json() if response.text else {}
            return {
                "success": False,
                "out_trade_no": merchant_order_no,
                "error_code": result.get("code"),
                "message": result.get("message", "订单关闭失败"),
            }

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "out_trade_no": merchant_order_no,
                "error": str(e),
                "message": "关闭订单请求失败",
            }
        except Exception as e:
            raise ValueError(f"WeChat Pay cancel payment failed: {str(e)}")

    async def parse_and_verify_callback(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> CallbackEvent:
        """
        验证并解析微信 APIv3 回调

        参考：https://pay.weixin.qq.com/doc/v3/merchant/4012791877
        （回调验签+解密逻辑）
        """
        # 1. 验签（需要微信平台证书公钥，这里简化省略）
        # 实际应验证 Wechatpay-Signature

        # 2. 解密 resource（AES-256-GCM + api_v3_key）
        payload_json = json.loads(body.decode("utf-8"))
        resource = payload_json.get("resource", {})

        # 简化：假设已解密（实际需 AES-GCM 解密）
        # decrypted = self._decrypt_resource(resource)
        # 这里用占位
        decrypted = resource  # FIXME: 需要真实解密

        # 3. 提取字段
        provider_event_id = payload_json.get("id")  # 微信事件 ID
        event_type = payload_json.get("event_type")  # 如 TRANSACTION.SUCCESS

        out_trade_no = decrypted.get("out_trade_no")  # 商户订单号
        transaction_id = decrypted.get("transaction_id")  # 微信交易号
        trade_state = decrypted.get("trade_state")  # SUCCESS / PAYERROR / ...

        # 映射 trade_state 到 outcome
        outcome_map = {
            "SUCCESS": "succeeded",
            "PAYERROR": "failed",
            "CLOSED": "canceled",
        }
        outcome = outcome_map.get(trade_state, "unknown")

        return CallbackEvent(
            provider_event_id=provider_event_id,
            provider_txn_id=transaction_id,
            merchant_order_no=out_trade_no,
            outcome=outcome,
            raw_payload=payload_json,
        )

    def _build_request_headers(
        self, method: str, url_path: str, body: str
    ) -> dict[str, str]:
        """
        构造微信 APIv3 请求头（简化版）

        实际需要：
        - 计算签名串
        - 使用商户私钥签名
        - 组装 Authorization 头

        这里用占位，生产环境建议用官方 SDK
        """
        # FIXME: 真实签名逻辑
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "payment-gateway/1.0",
            # Authorization: WECHATPAY2-SHA256-RSA2048 mchid=...,serial_no=...,signature=...,timestamp=...,nonce=...
        }


# 延迟初始化单例实例（只在首次访问时创建）
_wechatpay_adapter_instance = None


def get_wechatpay_adapter() -> WeChatPayAdapter:
    """获取微信支付适配器单例"""
    global _wechatpay_adapter_instance
    if _wechatpay_adapter_instance is None:
        _wechatpay_adapter_instance = WeChatPayAdapter()
    return _wechatpay_adapter_instance
