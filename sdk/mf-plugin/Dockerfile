# Fly.io HND 用、shared-cpu-1x / 256MB を想定。
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY app.py config.py oauth_callback.py proxy_endpoints.py /app/
COPY frontend /app/frontend

EXPOSE 8080

# Fly proxy が PORT を渡す。uvicorn 直叩き、access log は stdout。
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
