FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GLPI_ASSISTANT_DATA=/data

WORKDIR /opt/glpi-assistant

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

RUN mkdir -p /data

EXPOSE 8765

# Host networking inherits the Linux host DNS path. Loopback binding keeps the
# local UI and its credentials inaccessible from the LAN.
CMD ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8765", "--no-proxy-headers", "--limit-concurrency", "32", "--timeout-keep-alive", "5"]
