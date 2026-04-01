import sys
import stripe
import asyncio
import traceback
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 加载 .env 文件
from dotenv import load_dotenv

env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path, verbose=True)
print(f"✅ 已加载环境变量文件: {env_path}\n")

from gateway.providers.stripe import get_stripe_adapter


adapter = get_stripe_adapter()
quantity = 1
unit_amount = 1000
currency = "CNY"
customer_name = "test"
customer_email = "test@example.com"
merchant_order_no = "test00009"
product_name = "test"
product_desc = "test desc"


async def test_session():
    print("\n" + "=" * 80)
    print("测试2：自动支付方式（由 Stripe 选择）")
    print("=" * 80)
    result2 = await adapter.create_payment(
        currency=currency,
        merchant_order_no=merchant_order_no,
        notify_url="https://brandie-hagiolatrous-daina.ngrok-free.dev/v1/callbacks/stripe",
        quantity=quantity,
        unit_amount=unit_amount,
        expire_minutes=30,
        product_name="测试商品",
        product_desc="商品描述",
        metadata={
            "customer_email": customer_email,
            "customer_name": customer_name,
            "merchant_order_no": merchant_order_no,
        },
    )

    if result2:
        print("\n自动支付方式返回：")
        print(f"{result2.model_dump()}\n")


async def create_checkout_session():
    session_data = {
        "mode": "payment",
        "line_items": [
            {
                "quantity": 1,
                "price_data": {
                    "currency": "CNY",
                    "unit_amount": 1000,
                    "product_data": {
                        "name": "测试商品",
                        "description": "商品描述",
                    },
                },
            }
        ],
        "customer_email": customer_email,
        "metadata": {
            "customer_name": customer_name,
            "merchant_order_no": merchant_order_no,
        },
        "payment_intent_data": {
            "metadata": {
                "customer_name": customer_name,
                "merchant_order_no": merchant_order_no,
            }
        },
        "success_url": "https://www.baidu.com?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": "https://google.com",
        "payment_method_types": ["card"],
    }

    try:
        print(
            f"正在创建 Stripe Session - 货币: {currency}, 金额: {unit_amount}, 数量: {quantity}"
        )

        session = stripe.checkout.Session.create(**session_data)

        print(
            f"Stripe Session 创建成功 - ID: {session.id}, "
            f"URL: {session.url}, "
            f"支付方式: {', '.join(session.payment_method_types)}, "
            f"货币: {session.currency}, "
            f"总金额: {session.amount_total}"
        )

        return session

    except stripe.StripeError as e:
        error_msg = e.user_message if hasattr(e, "user_message") else str(e)
        error_type = type(e).__name__
        print(f"Stripe Session 创建失败 - 错误类型: {error_type}, 消息: {error_msg}")

        if hasattr(e, "json_body"):
            print(f"错误详情: {e.json_body}")

        traceback.print_exc()
        raise


asyncio.run(test_session())
