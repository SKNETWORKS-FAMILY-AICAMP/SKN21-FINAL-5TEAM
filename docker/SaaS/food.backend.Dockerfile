FROM ghcr.io/astral-sh/uv:0.8.17 AS uv

FROM python:3.11-slim

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv

COPY food/backend/requirements.txt /app/requirements.txt
RUN sed -E -i 's/^django-environ>=1\.0$/django-environ>=0.13.0/' /app/requirements.txt \
	&& uv pip install --system --no-cache -r /app/requirements.txt

COPY food /app/food

WORKDIR /app/food/backend

RUN python manage.py migrate || true

EXPOSE 8002

CMD ["python", "manage.py", "runserver", "0.0.0.0:8002"]
