# Stage 1: Build Frontend Assets
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python Runner
FROM python:3.12-slim AS runner

WORKDIR /app

# Install system dependencies for OCR & image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# Copy backend code, models, scripts, and vendor catalog data
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY data/ ./data/

# Copy built frontend SPA from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Default port
ENV PORT=8000
EXPOSE 8000

# Start unified FastAPI server (serves both API & Frontend SPA)
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

