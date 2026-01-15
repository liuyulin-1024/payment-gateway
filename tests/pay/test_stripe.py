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
customer_name = 'test'
customer_email = 'test@example.com'
merchant_order_no = "test00009"
product_name = 'test'
product_desc = 'test desc'


async def test_session():
    # print("=" * 80)
    # print("Test 1: Manual payment methods (alipay + card)")
    # print("=" * 80)
    # result1 = await adapter.create_checkout_session(
    #     'CNY', 1000, 1, '测试商品', '商品描述',
    #     customer_email, 'test', merchant_order_no, False
    # )
    #
    # print("\n" + "=" * 80)
    # print("SUMMARY")
    # print("=" * 80)
    # if result1:
    #     print(f"\nManual methods URL:")
    #     print(f"{result1.url}\n")
    #     print(f"Available methods: {result1.payment_method_types}")

    print("\n" + "=" * 80)
    print("测试2：自动支付方式（由 Stripe 选择）")
    print("=" * 80)
    result2 = await adapter.create_payment(
        currency=currency, merchant_order_no=merchant_order_no,
        notify_url="https://brandie-hagiolatrous-daina.ngrok-free.dev/v1/callbacks/stripe",
        quantity=quantity, unit_amount=unit_amount, expire_minutes=30, product_name="测试商品", product_desc="商品描述",
        metadata={
            'customer_email':customer_email,
            "customer_name": customer_name,
            "merchant_order_no": merchant_order_no,
        },
    )

    if result2:
        print("\n自动支付方式返回：")
        print(f"{result2.model_dump()}\n")


async def create_checkout_session():
    use_automatic_methods, include_wechat_pay = True, True
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
        "metadata": {"customer_name": customer_name, "merchant_order_no": merchant_order_no},
        # 将 metadata 同时传递到 PaymentIntent，确保在 payment_intent.* 事件中也能获取到
        "payment_intent_data": {
            "metadata": {
                "customer_name": customer_name,
                "merchant_order_no": merchant_order_no,
            }
        },
        "success_url": "https://www.baidu.com?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": "https://google.com",
    }

    # 方式1：自动支付方式
    if use_automatic_methods:
        session_data["automatic_payment_methods"] = {"enabled": True}
    else:
        # 方式2：手动指定支付方式
        payment_methods = ["alipay", "card"]
        if include_wechat_pay:
            payment_methods.append("wechat_pay")

        session_data["payment_method_types"] = payment_methods
        print(f"使用手动指定支付方式: {', '.join(payment_methods)}")

    # 微信支付需要额外配置 payment_method_options
    if include_wechat_pay:
        session_data["payment_method_options"] = {
            "wechat_pay": {
                "client": "web"  # 'web' 用于网页端，'mobile' 用于移动端
            }
        }
        print("微信支付客户端类型: web")

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