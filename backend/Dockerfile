FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN useradd --create-home --uid 1000 reportbox
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /data/storage && chown -R reportbox /data
USER reportbox

EXPOSE 8000
# Apply database migrations, then start the API. --proxy-headers lets the API see real client
# IPs (used by login limits and the audit log) behind the Caddy proxy.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips='*'"]
