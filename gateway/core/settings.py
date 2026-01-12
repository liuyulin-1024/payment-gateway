"""
应用配置管理（pydantic-settings）
"""

from __future__ import annotations
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置（从环境变量加载）"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 数据库配置
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "gateway"
    db_password: str = "dev_password"
    db_name: str = "gateway"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # 支付配置（所有支付提供商配置均为可选）
    ## stripe
    stripe_secret_key: str
    stripe_webhook_secret: str

    ## alipay
    alipay_app_id: str = ""
    alipay_private_key: str = ""  # 应用私钥内容
    alipay_public_key: str = ""  # 支付宝公钥内容
    alipay_sandbox: bool = False

    # 应用配置
    log_level: str = "INFO"
    payment_expire_minutes_default: int = Field(default=30, ge=1, le=24 * 60)

    # Worker 配置
    worker_poll_interval: int = 5  # 轮询间隔（秒）
    worker_batch_size: int = 10  # 每批处理任务数
    worker_max_retries: int = 10  # 最大重试次数


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
