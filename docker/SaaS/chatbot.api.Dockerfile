FROM ghcr.io/astral-sh/uv:0.8.17 AS uv

FROM python:3.13-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /workspace/pyproject.toml
COPY uv.lock /workspace/uv.lock
COPY README.md /workspace/README.md

RUN uv sync --frozen --no-dev --no-install-project

EXPOSE 8100

CMD ["uv", "run", "uvicorn", "server_fastapi:app", "--app-dir", "/workspace/chatbot", "--host", "0.0.0.0", "--port", "8100"]
