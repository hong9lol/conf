FROM python:3.11-slim

WORKDIR /app

# Playwright Chromium 실행에 필요한 시스템 의존성 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    curl \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libexpat1 \
    libxcb1 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium 브라우저 설치
RUN playwright install chromium && playwright install-deps chromium

# 소스 코드 복사 (venv 제외)
COPY *.py ./
COPY .env.template ./

# 데이터 디렉토리 생성
RUN mkdir -p confluence_pages confluence_vectordb logs backups

EXPOSE 5000

CMD ["python", "app.py"]
