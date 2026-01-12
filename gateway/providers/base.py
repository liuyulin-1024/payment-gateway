"""
Provider Adapter 基类（定义统一接口）
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from gateway.core.constants import Provider
from gateway.core.schemas import PaymentTypeEnum, CallbackEvent


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

    @abstractmethod
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
        创建支付（调用渠道下单 API）

        返回：统一的 ProviderPaymentResult（type + payload）
        """
        pass

    @abstractmethod
    async def create_refund(
        self,
        *,
        txn_id: str,
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
