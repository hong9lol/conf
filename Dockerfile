# ============================================
# Stage 1: 빌더 - 의존성 설치 및 가상환경 생성
# ============================================
FROM python:3.11-slim AS builder

# 빌드에 필요한 시스템 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 가상환경 생성
RUN python -m venv /opt/venv
# 가상환경을 PATH에 추가하여 이후 pip/python이 가상환경 것을 사용
ENV PATH="/opt/venv/bin:$PATH"

# 의존성 파일만 먼저 복사 (레이어 캐싱 최적화)
# 소스 코드가 변경되어도 requirements.txt가 같으면 캐시 재사용
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================
# Stage 2: 런타임 - 최소한의 실행 환경
# ============================================
FROM python:3.11-slim

# 바이트코드 생성 방지 (.pyc 파일 미생성)
ENV PYTHONDONTWRITEBYTECODE=1
# 출력 버퍼링 비활성화 (로그 즉시 출력)
ENV PYTHONUNBUFFERED=1

# 런타임에 필요한 최소 시스템 패키지 설치
# Playwright Chromium 실행에 필요한 라이브러리 포함
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright Chromium 의존성
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    # 헬스체크용
    curl \
    && rm -rf /var/lib/apt/lists/*

# 빌더에서 가상환경 복사 (의존성 포함)
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Playwright Chromium 브라우저 설치
RUN playwright install chromium

# 비root 사용자 생성 (보안 강화)
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

# 작업 디렉토리 설정
WORKDIR /app

# 소스 코드 복사
COPY . .

# 디렉토리 권한 설정 (런타임에 파일 쓰기 필요)
RUN mkdir -p confluence_pages confluence_vectordb logs backups && \
    chown -R appuser:appuser /app

# 비root 사용자로 전환
USER appuser

# Gradio UI 포트 노출
EXPOSE 7860

# 헬스체크: Gradio 서버 응답 확인
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:7860/ || exit 1

# 기본 실행 명령
CMD ["python", "app.py"]
