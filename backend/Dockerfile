# Two targets share one base: `api` serves HTTP, `worker` additionally carries the
# OCR stack and LibreOffice (needed to re-render workbooks for visual diffing).
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY pytest.ini ./


FROM base AS api

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS worker

# libgl1/libglib2.0 are OpenCV's runtime dependencies; LibreOffice renders the
# produced .xlsx back to PDF for the Phase 3 and Phase 4 checks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libreoffice-calc \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-ocr.txt ./
RUN pip install --no-cache-dir -r requirements-ocr.txt

COPY tests ./tests

CMD ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=info", "--concurrency=1"]
