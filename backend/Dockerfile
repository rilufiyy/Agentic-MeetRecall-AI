FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        git \
        curl \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# CPU wheels (much smaller image than the CUDA build). Torch gets its own
# layer so editing requirements.txt does not download it again.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --retries 10 --timeout 180 \
        torch torchaudio --index-url ${TORCH_INDEX_URL}

COPY requirements.txt .
# pip's download cache lives in a BuildKit cache mount (outside the image), so a
# requirements.txt change only downloads the packages that are new or changed.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 180 -r requirements.txt

COPY . .
RUN mkdir -p /app/data/meetings /app/data/faiss /app/uploads
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]