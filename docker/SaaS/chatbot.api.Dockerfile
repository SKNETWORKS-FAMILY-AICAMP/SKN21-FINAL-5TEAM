FROM ghcr.io/astral-sh/uv:0.8.17 AS uv

FROM python:3.11-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=uv /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libopenblas-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY ecommerce/backend/requirements.txt /workspace/ecommerce/backend/requirements.txt
RUN grep -vE '^(torch|torchvision)(==|>=|<=|~=|>|<).*' /workspace/ecommerce/backend/requirements.txt > /tmp/chatbot-requirements-no-torch.txt \
    && printf '%s\n' orjson pillow >> /tmp/chatbot-requirements-no-torch.txt \
    && uv pip install --system --no-cache -r /tmp/chatbot-requirements-no-torch.txt \
    && uv pip install --system --no-cache --index-url https://download.pytorch.org/whl/cpu torch==2.10.0 torchvision==0.25.0

COPY . .

EXPOSE 8100

CMD ["uvicorn", "server_fastapi:app", "--app-dir", "/workspace/chatbot", "--host", "0.0.0.0", "--port", "8100", "--proxy-headers", "--forwarded-allow-ips", "*"]
