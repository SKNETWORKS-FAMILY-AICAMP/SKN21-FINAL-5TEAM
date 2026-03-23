FROM ghcr.io/astral-sh/uv:0.8.17 AS uv

FROM python:3.11-slim

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY bilyeo/backend/requirements.txt /app/requirements.txt
RUN uv pip install --system --no-cache -r /app/requirements.txt

COPY bilyeo /app/bilyeo

WORKDIR /app/bilyeo/backend

EXPOSE 5000

CMD ["python", "app.py"]
