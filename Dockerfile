# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# 安装 uv（快速 Python 包管理器）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 设置工作目录
WORKDIR /app

# 环境变量：Python 不生成 .pyc 文件，输出不缓冲
ENV TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy

# 安装 tzdata 并设置时区
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml

# 安装依赖
RUN uv sync --no-dev

# 复制应用代码
COPY . .

# 暴露端口（FastAPI 默认 8000）
EXPOSE 8000

# 默认命令（直接使用虚拟环境中的 Python）
CMD ["uv", "run", "uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
