"""
Provider 适配器工厂（根据 App + Provider 加载配置并实例化）
"""

from gateway.core.constants import Provider
from .base import ProviderAdapter
from .stripe import StripeAdapter, get_stripe_adapter
from .wechatpay import WeChatPayAdapter, get_wechatpay_adapter
from .alipay import AlipayAdapter, get_alipay_adapter

# 导出类和获取函数
__all__ = [
    "ProviderAdapter",
    "StripeAdapter",
    "WeChatPayAdapter",
    "AlipayAdapter",
    "get_stripe_adapter",
    "get_wechatpay_adapter",
    "get_alipay_adapter",
    "get_adapter",
]


def get_adapter(provider: Provider) -> ProviderAdapter:
    """
    根据 Provider 获取对应的适配器单例

    只有在调用此函数时才会初始化对应的适配器，
    避免启动时就要求所有支付提供商的配置
    """
    if provider == Provider.stripe:
        return get_stripe_adapter()
    elif provider == Provider.wechatpay:
        return get_wechatpay_adapter()
    elif provider == Provider.alipay:
        return get_alipay_adapter()
    else:
        raise ValueError(f"Unsupported provider: {provider}")
