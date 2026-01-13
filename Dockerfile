FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# uv 用于根据 uv.lock 安装依赖（项目使用 uv 作为依赖管理器）
RUN python -m pip install --upgrade pip && \
    python -m pip install uv

# 先复制依赖清单以利用 Docker layer cache
COPY pyproject.toml uv.lock ./

# 安装运行时依赖到项目虚拟环境（.venv）
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # 让运行时直接使用 builder 生成的虚拟环境
    PATH="/app/.venv/bin:$PATH"

# 创建非 root 用户运行服务
RUN useradd --create-home --shell /usr/sbin/nologin appuser

# 拷贝虚拟环境与应用代码
COPY --from=builder /app/.venv /app/.venv
COPY . /app

# FastAPI 默认端口
EXPOSE 8000

USER appuser

# 默认启动 API（worker 会在 docker-compose 中覆盖 command）
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]

