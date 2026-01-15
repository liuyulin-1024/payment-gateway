import sys
import json
import asyncio
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 加载 .env 文件
from dotenv import load_dotenv

env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path, verbose=True)
print(f"✅ 已加载环境变量文件: {env_path}")

from gateway.providers.alipay import get_alipay_adapter


adapter = get_alipay_adapter()
currency = "CNY"
order_no = "test009"
product_name = 'test'
product_desc = 'test desc'


async def test_payment():
    result = await adapter.create_payment(
        quantity=1,
        unit_amount=5000,
        product_name=product_name,
        product_desc=product_desc,
        currency=currency,
        metadata={'customer_email': 'test@autogame.ai'},
        merchant_order_no=order_no,
        notify_url="https://brandie-hagiolatrous-daina.ngrok-free.dev/v1/callbacks/alipay",
        expire_minutes=30,
    )
    print("\n✅ 支付创建成功:")
    print(f"   类型: {result.model_dump()}")

    # 支付宝返回的是 HTML form，不是 URL
    html = result.payload.get("html", "N/A")
    if html != "N/A":
        print(f"   HTML 表单长度: {len(html)} 字符")
        print(f"   HTML 表单预览: {html[:200]}...")
        with open("./alipay/payment.html", "w", encoding="utf-8") as f:
            f.write(html)
    else:
        print(f"   HTML 表单: {html}")

    print(f"   交易号: {result.provider_txn_id}")


async def query_payment():
    result = await adapter.query_payment(
        merchant_order_no=order_no,
    )
    print(result)
    return json.loads(result)


async def refund_payment():
    data = await query_payment()
    response = await adapter.create_refund(
        txn_id=data["trade_no"], amount=amount, reason="退款"
    )
    print(response)


if __name__ == "__main__":
    # asyncio.run(test_payment())
    # asyncio.run(query_payment())
    asyncio.run(refund_payment())
