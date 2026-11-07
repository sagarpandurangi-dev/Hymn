# Production image for the Hymn API (used by Railway; works on any Docker host).
FROM python:3.11-slim

WORKDIR /app

# emergentintegrations is only published on Emergent's private index and is
# imported lazily, so it is left out of the image.
COPY requirements.txt .
RUN grep -v '^emergentintegrations' requirements.txt > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY . .

ENV HYMN_RUNTIME_MODE=production
# Railway sets PORT; default to 8000 elsewhere.
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
