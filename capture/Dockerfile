FROM python:3.11-slim

# Set timezone ke WIB
ENV TZ=Asia/Jakarta
RUN apt-get update && apt-get install -y --no-install-recommends tzdata cron && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY capture/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY capture/ ./capture/
COPY scripts/ ./scripts/

# Berikan izin eksekusi skrip
RUN chmod +x ./scripts/*.sh

CMD ["python", "-m", "capture.scheduler"]
