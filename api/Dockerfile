FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY predict_service ./predict_service
COPY metrics_service ./metrics_service
COPY data ./data

EXPOSE 8000

CMD ["uvicorn", "predict_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
