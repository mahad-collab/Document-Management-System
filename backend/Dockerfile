# Python 3.12 to match local dev (see backend/.venv) — Debian slim base so
# `apt-get install tesseract-ocr` (needed by app/ocr/service.py) is a single
# straightforward step, unlike Alpine where Tesseract's dependency chain is
# more painful to build.
FROM python:3.12-slim

# poppler-utils isn't required by this app (PyMuPDF handles PDF rendering
# without it) — only tesseract-ocr itself, plus its English language pack.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets $PORT at runtime; default to 8000 for local `docker run` testing.
ENV PORT=8000
EXPOSE 8000

# Migrations run as a separate Render "pre-deploy command" (see render.yaml),
# not baked into the image start command — a failed migration should block
# the deploy from going live, not run silently inside the same process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
