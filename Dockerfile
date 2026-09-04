FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN rm -rf dist && npm run build

FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . ./
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

CMD ["sh", "-c", "python -m uvicorn src.web_api:app --host 0.0.0.0 --port ${PORT}"]
