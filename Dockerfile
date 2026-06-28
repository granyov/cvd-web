FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CVD_HOST=0.0.0.0 \
    CVD_PORT=8080 \
    CVD_DB_PATH=/app/data/cvd.sqlite3

WORKDIR /app
COPY . /app
RUN mkdir -p /app/data

EXPOSE 8080
CMD ["python", "-m", "cvd_web"]
