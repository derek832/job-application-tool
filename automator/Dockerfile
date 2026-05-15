# syntax=docker/dockerfile:1

# ── Stage 1: build dependencies ──────────────────────────────────────────────
FROM python:3.11.9-slim@sha256:3b6efc048405b61ba4baa60f7ccb1f8e131e8ce4ca3b6ebb5108084f68c86c4d AS builder

WORKDIR /build

# Copy pinned requirements and install into a prefix we can copy later
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Install Playwright to the default location so we can run the CLI,
# then download Chromium into the prefix directory for the runtime stage.
RUN pip install --no-cache-dir playwright==1.59.0 && \
    PLAYWRIGHT_BROWSERS_PATH=/install/ms-playwright \
    python -m playwright install chromium --with-deps


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11.9-slim@sha256:3b6efc048405b61ba4baa60f7ccb1f8e131e8ce4ca3b6ebb5108084f68c86c4d AS runtime

# Security: run as non-root
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy Playwright browsers
COPY --from=builder /install/ms-playwright /ms-playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install Playwright system dependencies (shared libs needed by Chromium)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libwayland-client0 && \
    rm -rf /var/lib/apt/lists/*

# Copy application source
COPY src/ ./src/

# Data directory (mounted volume at runtime)
RUN mkdir -p /app/data/logs /app/data/traces /app/data/backups && \
    chown -R appuser:appuser /app/data

USER appuser

EXPOSE 7432

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "7432"]
