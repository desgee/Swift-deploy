# ── build stage ────────────────────────────────────────────────
FROM python:3.12-alpine AS builder

WORKDIR /build
COPY app/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── runtime stage ──────────────────────────────────────────────
FROM python:3.12-alpine

# non-root user
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

# copy installed packages from builder
COPY --from=builder /install /usr/local

# copy app source
COPY app/ .

# log directory owned by appuser
RUN mkdir -p /var/log/app && chown appuser:appgroup /var/log/app

USER appuser

ENV MODE=stable \
    APP_VERSION=1.0.0 \
    APP_PORT=3000

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/healthz')" || exit 1

CMD ["gunicorn", \
     "--bind", "0.0.0.0:3000", \
     "--workers", "2", \
     "--threads", "4", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "main:app"]