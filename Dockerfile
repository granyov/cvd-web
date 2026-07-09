FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CVD_HOST=0.0.0.0 \
    CVD_PORT=8080 \
    CVD_DB_PATH=/app/data/cvd.sqlite3

WORKDIR /app
COPY . /app
RUN mkdir -p /app/data && chown -R 1000:1000 /app/data

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()" || exit 1
CMD ["python", "-m", "cvd_web"]
