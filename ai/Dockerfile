FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/opt/hf

# Tesseract with English, Hindi and Tamil language packs (the reference package's OCR languages)
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-tam libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch
COPY requirements-service.txt .
RUN pip install -r requirements-service.txt

# Bake the multilingual embedding model into the image; after this build the service needs no internet.
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY app ./app
COPY models /models
RUN useradd --system --uid 10002 sentinel && chown -R sentinel /opt/hf
USER sentinel
ENV MODELS_DIR=/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 9000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
