from __future__ import annotations

import os
import sys
import asyncio
import argparse
import threading
from pathlib import Path

from uvicorn import Config, Server
from sqlalchemy.ext.asyncio import create_async_engine

from gateway.db import get_database_url


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def set_default_env() -> None:
    #     os.environ.setdefault("LOG_LEVEL", "INFO")
    #     os.environ.setdefault("DB_HOST", "localhost")
    #     os.environ.setdefault("DB_PORT", "5432")
    #     os.environ.setdefault("DB_USER", "postgres")
    #     os.environ.setdefault("DB_PASSWORD", "g0!(!Lmmd9^aAQ5")
    #     os.environ.setdefault("DB_NAME", "pgm")
    #     os.environ.setdefault("DB_ECHO", "false")
    #     os.environ.setdefault("DB_POOL_SIZE", "5")
    #     os.environ.setdefault("DB_MAX_OVERFLOW", "10")
    #
    os.environ["alipay_private_key"] = (
        "MIIEogIBAAKCAQEAqzF778mPTyN2/q+edfaV45Vt/6TwM7UsotVUhy05QMCpeIF1AY8d+lcEDBKj5SN2ZnhOTIzAGYBfyQbJvmqxoQDEXG6Ps2Cff1cSA7EAc2J1/K6NgfqOIeHm66RKP1AZ8b0fTgLHu+K9dnkifSToUu5A/8dAoEyJy+fOE8rnifj3oqK1wfLl4Rv0FgoMHNzqhqMiqKNnGg9ULzSmsg0CphJ0lTw1Ebq0C6wYYVd4VBYDtxQWKsk8WDoNLJXl+oU4nBqxNFsHY8wi6sOSVu5L0NtydsUTlb6yZ4FciIeaKoHm0sDBMaMrlRYvEsqMdkkSLeGX5oen8c/IXHqRT0eW7wIDAQABAoIBACWi02R8I416doa3hVbZx0opZ+10DXrQsed6jwLI5nVd5eQgUeDt3eFTkAg3cODHUxhkCpK5vuHcXzKK03+RZUvIJ2NKyzzcWTRdqBA3samsU9Qha+rPcr/wMhxMGiahLZL/yQoVgmPEDXMmXna0zn6s8o1I+ORE72Zsp9miGhUy0vGQ1+VGgbZpualfaAQR+c6JWz4VtbhBWvjOxDyI2PQKjGMWZZeGab4lJ2x97ocO3BKupK9nmeTgsF9AFzx5ws1xhnJF7kYf+fi5itabIJEQYAIOswSt3zgMDAyZ1oxhOaxLn3uOpqMiDq6i8LYS72bYi8IixSpGugHoLaq2wUECgYEA0o/6OxJ4gp0iyo++kH+lIPbptPECdgZB4a8FfudhV3DoTG6f/V2YY/P89q2uG0Ul0I+6wjFGYcPi0cVu8SjGR/Rv1K/eZMb9pHC3IpxvyXJSfYvPGEnts8swTQPLMD5FV/v3QPRdwmS3eKZsFhDW2M+QsVBqeRSZB4uZX+QtrvMCgYEA0CKnLIpD0p5QuJuY7R/0TpkxFOM/7rJzacqi6Z3OHLF6UWoULKdFHYz4zheioQ5qh481F72Xuc6S1sQ/bo4RZV5jAotfxTkx/hvjJs5uLW9u7Oohh4gRvh1THrdgZCBoOwS/V3VzbSMjaBcN4PxWaKukk6tRydpNRyFLPU6YDxUCgYA5qVnyMVW1Fwj/Baw+7+WtiFBpz5JH9eC2x/IuVXivtGi4/ZZskOP5g0hj2R4Ts7TuT13qbgoDHdyQa4u9GNhrvgGd8edqG6A8Fu3f2Y03UkpKvS2iTiR9FwiMHpzXAkaFGKgWLpU6ddBUhuaUiFn9l6HdHNN7guuBSHZg7yCfhwKBgFYkQXRZtUBSba46F8zsULzHAl1WwHsWOFYsm8h8m3WcrrdLZBYnFJ/qXH9PoOtvf/+i8aJlwYoRSQzCJE6pVeHScr/21yhVR6+X8yd4gHkliY9cR4xEcLNyh5hK5QYLs5fZmyejYKZmyJyoDgJz7X9cqrzDRxJ320v5J560DJMRAoGAJ5NMiTbL+g71LkyyXs4mkYupDh4+qniD0QZtD3djfupWoP29raZTJM4JiZjAVaV5wih/7C6hDCX66KjtLkxH5D7gKwbTA4ebuvD3FFIQ228EIt1NsAKK4aweUPNd4oke1TskisZVtSPMRrm/BnG/zgvhBYXKpmrBp2IP5ypKLos="
    )
    os.environ["alipay_public_key"] = (
        "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA3Zl/mD4LQpkZ6ZrIwSfDFEN2SRzu7Ld55SclxMh6Thhbekl8REbV/OjdJZH3TBgFYM+5hWxYZeCQLZDVZsrK6lngf/ozGZ1Tuat2fEAI9Frqn5UGteLZ74hsdW6IX+gbW433gSGs0LVKk8+FY++iChnIrsIbYgPvd4X72NPhJDUFTHKu32/acxAlYiM314TQzUodcQ/R3AGpry1pIW10OJWNsW1S7iHMmr7/YX8d/ZhRmXu2h1vnzxo76dUNVYKarQU4W81JcqYvcYXYnANRjMabHGIETbIVxrHjJGXC9tNlqs4F5f1pW6nMde2SUfaLHhsuAiw4kk3v8IZN42+2pwIDAQAB"
    )

    # os.environ["ALIPAY_PRIVATE_KEY"] = "MIIEogIBAAKCAQEAqzF778mPTyN2/q+edfaV45Vt/6TwM7UsotVUhy05QMCpeIF1AY8d+lcEDBKj5SN2ZnhOTIzAGYBfyQbJvmqxoQDEXG6Ps2Cff1cSA7EAc2J1/K6NgfqOIeHm66RKP1AZ8b0fTgLHu+K9dnkifSToUu5A/8dAoEyJy+fOE8rnifj3oqK1wfLl4Rv0FgoMHNzqhqMiqKNnGg9ULzSmsg0CphJ0lTw1Ebq0C6wYYVd4VBYDtxQWKsk8WDoNLJXl+oU4nBqxNFsHY8wi6sOSVu5L0NtydsUTlb6yZ4FciIeaKoHm0sDBMaMrlRYvEsqMdkkSLeGX5oen8c/IXHqRT0eW7wIDAQABAoIBACWi02R8I416doa3hVbZx0opZ+10DXrQsed6jwLI5nVd5eQgUeDt3eFTkAg3cODHUxhkCpK5vuHcXzKK03+RZUvIJ2NKyzzcWTRdqBA3samsU9Qha+rPcr/wMhxMGiahLZL/yQoVgmPEDXMmXna0zn6s8o1I+ORE72Zsp9miGhUy0vGQ1+VGgbZpualfaAQR+c6JWz4VtbhBWvjOxDyI2PQKjGMWZZeGab4lJ2x97ocO3BKupK9nmeTgsF9AFzx5ws1xhnJF7kYf+fi5itabIJEQYAIOswSt3zgMDAyZ1oxhOaxLn3uOpqMiDq6i8LYS72bYi8IixSpGugHoLaq2wUECgYEA0o/6OxJ4gp0iyo++kH+lIPbptPECdgZB4a8FfudhV3DoTG6f/V2YY/P89q2uG0Ul0I+6wjFGYcPi0cVu8SjGR/Rv1K/eZMb9pHC3IpxvyXJSfYvPGEnts8swTQPLMD5FV/v3QPRdwmS3eKZsFhDW2M+QsVBqeRSZB4uZX+QtrvMCgYEA0CKnLIpD0p5QuJuY7R/0TpkxFOM/7rJzacqi6Z3OHLF6UWoULKdFHYz4zheioQ5qh481F72Xuc6S1sQ/bo4RZV5jAotfxTkx/hvjJs5uLW9u7Oohh4gRvh1THrdgZCBoOwS/V3VzbSMjaBcN4PxWaKukk6tRydpNRyFLPU6YDxUCgYA5qVnyMVW1Fwj/Baw+7+WtiFBpz5JH9eC2x/IuVXivtGi4/ZZskOP5g0hj2R4Ts7TuT13qbgoDHdyQa4u9GNhrvgGd8edqG6A8Fu3f2Y03UkpKvS2iTiR9FwiMHpzXAkaFGKgWLpU6ddBUhuaUiFn9l6HdHNN7guuBSHZg7yCfhwKBgFYkQXRZtUBSba46F8zsULzHAl1WwHsWOFYsm8h8m3WcrrdLZBYnFJ/qXH9PoOtvf/+i8aJlwYoRSQzCJE6pVeHScr/21yhVR6+X8yd4gHkliY9cR4xEcLNyh5hK5QYLs5fZmyejYKZmyJyoDgJz7X9cqrzDRxJ320v5J560DJMRAoGAJ5NMiTbL+g71LkyyXs4mkYupDh4+qniD0QZtD3djfupWoP29raZTJM4JiZjAVaV5wih/7C6hDCX66KjtLkxH5D7gKwbTA4ebuvD3FFIQ228EIt1NsAKK4aweUPNd4oke1TskisZVtSPMRrm/BnG/zgvhBYXKpmrBp2IP5ypKLos="
    # os.environ["ALIPAY_PUBLIC_KEY"] = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA3Zl/mD4LQpkZ6ZrIwSfDFEN2SRzu7Ld55SclxMh6Thhbekl8REbV/OjdJZH3TBgFYM+5hWxYZeCQLZDVZsrK6lngf/ozGZ1Tuat2fEAI9Frqn5UGteLZ74hsdW6IX+gbW433gSGs0LVKk8+FY++iChnIrsIbYgPvd4X72NPhJDUFTHKu32/acxAlYiM314TQzUodcQ/R3AGpry1pIW10OJWNsW1S7iHMmr7/YX8d/ZhRmXu2h1vnzxo76dUNVYKarQU4W81JcqYvcYXYnANRjMabHGIETbIVxrHjJGXC9tNlqs4F5f1pW6nMde2SUfaLHhsuAiw4kk3v8IZN42+2pwIDAQAB"


async def create_db_tables() -> None:
    """直接从模型创建数据库表（开发模式）"""

    print("🗄️  正在创建数据库表...")

    # 确保导入所有模型
    from gateway.core.models import Base

    # 创建异步引擎
    engine = create_async_engine(get_database_url(), echo=False)

    # 删除所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    async with engine.begin() as conn:
        # 创建所有表（如果不存在）
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()
    print("✅ 数据库表创建完成！")


def run_api(host: str, port: int, reload: bool) -> None:
    config = Config(
        "gateway.main:app",
        host=host,
        port=port,
        reload=reload,
    )
    server = Server(config)
    # 使用当前事件循环运行
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(server.serve())


async def run_worker() -> None:
    from gateway.worker import main as worker_main

    await worker_main()


async def run_all(host: str, port: int, reload: bool) -> None:
    """
    同时运行 API + Worker。

    注意：uvicorn.run() 是阻塞的，为了让 IDE 能一键运行，这里用线程启动 API。
    """

    t = threading.Thread(target=run_api, args=(host, port, reload), daemon=True)
    t.start()
    await run_worker()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Local dev runner for payment-gateway")
    p.add_argument(
        "mode",
        nargs="?",
        choices=("api", "worker", "all"),
        default="api",
        help="启动模式：api/worker/all（默认 api）",
    )
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument(
        "--reload", action="store_true", help="API 开启热重载（IDE 调试建议开）"
    )
    p.add_argument(
        "--reset-db", action="store_true", help="危险：强制重建数据库表（仅 localhost）"
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    set_default_env()
    if args.reset_db:
        asyncio.run(create_db_tables())

    if args.mode == "api":
        run_api(args.host, args.port, args.reload)
        return

    if args.mode == "worker":
        asyncio.run(run_worker())
        return

    asyncio.run(run_all(args.host, args.port, args.reload))


if __name__ == "__main__":
    main()
