FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SDMS_DATA_DIR=/data
WORKDIR /srv

# OCR, classification and summaries live in the separate `ai` service; the API only calls it over HTTP.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --system --uid 10001 sdms && mkdir /data && chown sdms /data
USER sdms
VOLUME /data
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
