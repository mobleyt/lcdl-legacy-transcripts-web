FROM python:3.12-slim

# pdfplumber/pdfminer need no system libs for text extraction, but keep the
# image lean and predictable.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY aviary_sync.py convert.py ./
COPY webapp ./webapp

# Job working dirs and output zips live here (mount a volume in compose).
ENV DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
