# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# 安装 uv（快速 Python 包管理器）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 设置工作目录
WORKDIR /app

# 环境变量：Python 不生成 .pyc 文件，输出不缓冲
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

# 复制依赖定义
COPY pyproject.toml uv.lock ./

# 安装依赖（使用 uv sync --frozen 确保可复现）
RUN uv sync --frozen --no-dev

# 复制应用代码
COPY . .

# 暴露端口（FastAPI 默认 8000）
EXPOSE 8000

# 默认命令（可被 docker-compose 覆盖）
CMD ["uvicorn", "payment_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
