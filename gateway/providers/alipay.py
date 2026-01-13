"""
支付宝 Adapter
"""

from urllib.parse import unquote_plus

from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
from alipay.aop.api.request.AlipayTradeQueryRequest import AlipayTradeQueryRequest
from alipay.aop.api.request.AlipayTradeRefundRequest import AlipayTradeRefundRequest
from alipay.aop.api.request.AlipayTradePagePayRequest import AlipayTradePagePayRequest
from alipay.aop.api.request.AlipayTradeCloseRequest import AlipayTradeCloseRequest

from gateway.core.constants import Provider
from gateway.core.logging import get_logger
from gateway.core.settings import get_settings
from gateway.core.schemas import PaymentTypeEnum, CallbackEvent
from gateway.providers.base import ProviderAdapter, ProviderPaymentResult


logger = get_logger()
settings = get_settings()


class AlipayAdapter(ProviderAdapter):
    """
    支付宝电脑网站支付适配器（单例模式）

    参考：https://opendocs.alipay.com/open-v3/2423fad5_alipay.trade.page.pay
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
        self.app_id = settings.alipay_app_id
        self.is_sandbox = settings.alipay_sandbox

        # 验证 APP ID
        if not self.app_id:
            raise ValueError("支付宝配置不完整。请设置 ALIPAY_APP_ID 环境变量")

        # 初始化支付宝客户端
        config = AlipayClientConfig(sandbox_debug=self.is_sandbox)
        config.app_id = self.app_id
        config.app_private_key = settings.alipay_private_key
        config.alipay_public_key = settings.alipay_public_key

        self.client = DefaultAlipayClient(alipay_client_config=config)
        AlipayAdapter._initialized = True

    @property
    def provider(self) -> Provider:
        return Provider.alipay

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
        支付宝电脑网站支付（page pay）

        返回 form HTML（商户需在前端自动提交表单跳转到支付宝）
        """
        # 计算总金额（单价 * 数量）
        total_amount_cents = (unit_amount or 0) * quantity
        # 支付宝金额单位：元（需要从分转换）
        total_amount = f"{total_amount_cents / 100:.2f}"

        # 构造业务参数
        biz_content = {
            "out_trade_no": merchant_order_no,
            "product_code": "FAST_INSTANT_TRADE_PAY",
            "total_amount": total_amount,
            "subject": (product_name or "商品")[:256],  # 商品标题
        }
        
        # 商品描述（可选）
        if product_desc:
            biz_content["body"] = product_desc[:128]

        # 超时时间（格式：90m / 1h / 1d）
        if expire_minutes:
            if expire_minutes < 60:
                timeout_express = f"{expire_minutes}m"
            elif expire_minutes < 1440:
                timeout_express = f"{expire_minutes // 60}h"
            else:
                timeout_express = f"{expire_minutes // 1440}d"
            biz_content["timeout_express"] = timeout_express

        # 创建请求
        request = AlipayTradePagePayRequest()
        request.biz_content = biz_content  # 设置业务参数（SDK会自动转换字典为模型对象）
        request.notify_url = notify_url
        request.return_url = None  # 同步回调（v1 不实现）

        # 调用 SDK 生成表单 HTML
        response = self.client.page_execute(request, http_method="POST")

        logger.info(
            f"[{self.__class__.__name__}] 支付订单创建成功：{merchant_order_no=} {total_amount=}元"
        )
        # response 是一个包含 form 的 HTML 字符串
        return ProviderPaymentResult(
            type=PaymentTypeEnum.form,
            payload={"html": response},
            provider_txn_id=None,  # 支付宝下单时不返回交易号
        )

    async def query_payment(self, merchant_order_no: str):
        biz_content = {"out_trade_no": merchant_order_no}
        request = AlipayTradeQueryRequest()
        request.biz_content = biz_content
        response = self.client.execute(request)
        return response

    async def create_refund(
        self,
        *,
        txn_id: str,
        refund_amount: int | None = None,
        reason: str | None = None,
    ) -> dict:
        # 退款单位：元（需要从分转换）
        refund_amount_yuan = f"{refund_amount / 100:.2f}"
        biz_content = {
            "trade_no": txn_id,
            "refund_amount": refund_amount_yuan,
            "refund_reason": reason,
        }
        request = AlipayTradeRefundRequest()
        request.biz_content = biz_content
        response = self.client.execute(request)
        return response

    async def cancel_payment(
        self,
        *,
        merchant_order_no: str,
        provider_txn_id: str | None = None,
    ) -> dict:
        """
        取消支付/关闭交易（alipay.trade.close）

        用于关闭未支付的订单，或撤销已创建但未完成的交易。
        商户订单号和支付宝交易号二选一，如果同时存在优先取商户订单号。

        参考：https://opendocs.alipay.com/open-v3/429ffb46_alipay.trade.close

        参数：
            merchant_order_no: 商户订单号（out_trade_no）
            provider_txn_id: 支付宝交易号（trade_no），可选

        返回：
            {
                "success": True/False,
                "code": "响应码",
                "msg": "响应消息",
                "trade_no": "支付宝交易号",
                "out_trade_no": "商户订单号"
            }
        """
        # 构造业务参数
        biz_content = {}

        # 商户订单号和支付宝交易号至少提供一个
        if merchant_order_no:
            biz_content["out_trade_no"] = merchant_order_no
        elif provider_txn_id:
            biz_content["trade_no"] = provider_txn_id
        else:
            raise ValueError("merchant_order_no 和 provider_txn_id 至少需要提供一个")

        # 创建请求
        request = AlipayTradeCloseRequest()
        request.biz_content = biz_content

        # 调用 SDK 执行关闭交易
        response = self.client.execute(request)

        # 解析响应
        # SDK 返回的 response 可能是字符串或对象，需要处理
        result = {}

        if hasattr(response, "code"):
            result["code"] = response.code
            result["msg"] = response.msg
            result["success"] = response.code == "10000"

            if hasattr(response, "trade_no"):
                result["trade_no"] = response.trade_no
            if hasattr(response, "out_trade_no"):
                result["out_trade_no"] = response.out_trade_no
        else:
            # 如果返回的是字典或字符串，尝试解析
            import json

            if isinstance(response, str):
                response_data = json.loads(response)
                # 通常结构为 {"alipay_trade_close_response": {...}}
                close_response = response_data.get("alipay_trade_close_response", {})
            else:
                close_response = response

            result["code"] = close_response.get("code")
            result["msg"] = close_response.get("msg")
            result["success"] = close_response.get("code") == "10000"
            result["trade_no"] = close_response.get("trade_no")
            result["out_trade_no"] = close_response.get("out_trade_no")

        return result

    async def parse_and_verify_callback(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> CallbackEvent:
        """
        验证并解析支付宝回调

        支付宝回调：application/x-www-form-urlencoded
        需要验签（RSA2）
        """
        # 解析表单（简化：假设是 JSON，实际是 form）
        # 真实场景需要解析 form-encoded 数据
        data = {}
        for pair in body.decode("utf-8").split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                data[k] = unquote_plus(v)

        # 验签（使用 SDK）
        # FIXME: 需要调用 client.verify() 方法验签
        # is_valid = self.client.verify(data, data.get("sign"), data.get("sign_type"))
        # if not is_valid:
        #     raise ValueError("Alipay signature verification failed")

        # 提取字段
        provider_event_id = data.get("notify_id")
        out_trade_no = data.get("out_trade_no")
        trade_no = data.get("trade_no")  # 支付宝交易号
        trade_status = data.get("trade_status")

        # 映射 trade_status 到 outcome
        outcome_map = {
            "TRADE_SUCCESS": "succeeded",
            "TRADE_FINISHED": "succeeded",
            "TRADE_CLOSED": "canceled",
        }
        outcome = outcome_map.get(trade_status, "unknown")

        return CallbackEvent(
            provider_event_id=provider_event_id,
            provider_txn_id=trade_no,
            merchant_order_no=out_trade_no,
            outcome=outcome,
            raw_payload=data,
        )


# 延迟初始化单例实例（只在首次访问时创建）
_alipay_adapter_instance = None


def get_alipay_adapter() -> AlipayAdapter:
    """获取支付宝适配器单例"""
    global _alipay_adapter_instance
    if _alipay_adapter_instance is None:
        _alipay_adapter_instance = AlipayAdapter()
    return _alipay_adapter_instance
