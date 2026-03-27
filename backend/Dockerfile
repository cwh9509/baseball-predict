FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 (psycopg2 빌드, lxml 등)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Poetry 설치
RUN pip install --no-cache-dir poetry==1.8.2

# 의존성만 먼저 설치 (레이어 캐시 활용)
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# 앱 소스 복사
COPY . .

# ml_models 디렉토리 생성
RUN mkdir -p /app/ml_models

EXPOSE 8000
