"""
Provider Adapter 基类（定义统一接口）
"""

from abc import ABC, abstractmethod
from typing import Any
from enum import Enum

from pydantic import BaseModel

from gateway.core.constants import Provider
from gateway.core.schemas import PaymentTypeEnum, CallbackEvent


class PaymentFlowType(str, Enum):
    """支付流程类型"""

    HOSTED = "hosted"  # 托管支付（跳转到支付渠道页面）- Stripe Session, Alipay Form, WeChat QR


class ProviderPaymentResult(BaseModel):
    """Provider 下单结果"""

    type: PaymentTypeEnum
    payload: dict[str, Any]
    provider_txn_id: str | None = None


class ProviderAdapter(ABC):
    """支付渠道适配器基类"""

    @property
    @abstractmethod
    def provider(self) -> Provider:
        """渠道标识"""
        pass

    @property
    def supported_flows(self) -> list[PaymentFlowType]:
        """
        当前 provider 支持的支付流程类型

        子类可以重写此方法声明支持的流程
        默认只支持 HOSTED 流程
        """
        return [PaymentFlowType.HOSTED]

    @abstractmethod
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
        创建支付（统一入口）

        这是主要的支付创建方法，适用于：
        - Stripe Checkout Session（托管页面）
        - Alipay 电脑网站支付（Form 表单）
        - WeChat Native 支付（二维码）

        参数：
            currency: 货币代码（如 USD, CNY）
            merchant_order_no: 商户订单号
            quantity: 数量
            notify_url: 异步回调通知 URL
            expire_minutes: 过期时间（分钟）
            unit_amount: 单价（最小货币单位，如分）
            product_name: 商品名称
            product_desc: 商品描述
            **kwargs: 额外参数（如 success_url, cancel_url, metadata）

        返回：
            ProviderPaymentResult:
                - type: 支付类型（url/form/qr）
                - payload: 支付数据
                - provider_txn_id: 渠道交易号（如果有）
        """
        pass

    @abstractmethod
    async def create_refund(
        self,
        *,
        txn_id: str,
        merchant_order_no: str,
        refund_amount: int | None = None,
        reason: str | None = None,
    ) -> dict:
        """
        创建退款

        返回：统一的 ProviderPaymentResult（type + payload）
        """
        pass

    @abstractmethod
    async def parse_and_verify_callback(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> CallbackEvent:
        """
        解析并验证渠道回调

        - 验签/解密
        - 提取关键字段（event_id, txn_id, order_no, outcome）
        - 返回标准化的 CallbackEvent

        如果验签失败，抛出异常
        """
        pass

    @abstractmethod
    async def cancel_payment(
        self,
        *,
        merchant_order_no: str,
        provider_txn_id: str | None = None,
    ) -> dict[str, Any]:
        """
        取消支付/关闭交易

        参数：
            merchant_order_no: 商户订单号
            provider_txn_id: 支付渠道交易号（可选，部分渠道支持）

        返回：包含取消结果的字典
        """
        pass

    async def query_payment(self, provider_txn_id: str) -> dict[str, Any]:
        """
        查询支付（可选实现，v1 暂不强制）
        """
        raise NotImplementedError(f"{self.provider} does not implement query_payment")
