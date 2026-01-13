import enum


class Provider(str, enum.Enum):
    stripe = "stripe"
    alipay = "alipay"
    wechatpay = "wechatpay"


class Currency(str, enum.Enum):
    USD = "USD"  # 美元
    CNY = "CNY"  # 人民币
    HKD = "HKD"  # 港币
    KRW = "KRW"  # 韩元
    THB = "THB"  # 泰铢
    EUR = "EUR"  # 欧元
    GBP = "GBP"  # 英镑
    JPY = "JPY"  # 日元
    INR = "INR"  # 印度卢比


class PayType(str, enum.Enum):
    """统一下单返回类型"""

    redirect = "redirect"
    form = "form"
    qr = "qr"
    client_secret = "client_secret"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class CallbackStatus(str, enum.Enum):
    received = "received"
    processing = "processing"
    processed = "processed"
    failed = "failed"


class DeliveryStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"
    dead = "dead"


class RefundStatus(str, enum.Enum):
    """退款状态"""

    pending = "pending"  # 退款中
    succeeded = "succeeded"  # 退款成功
    failed = "failed"  # 退款失败
    canceled = "canceled"  # 已取消
