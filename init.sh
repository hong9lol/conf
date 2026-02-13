#!/usr/bin/env bash
# ============================================
# Confluence RAG 시스템 - Ubuntu 24.04 초기 설정 스크립트
# 사용법: chmod +x init.sh && sudo ./init.sh
# ============================================

set -euo pipefail

# --- 색상 정의 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[정보]${NC} $1"; }
success() { echo -e "${GREEN}[완료]${NC} $1"; }
error()   { echo -e "${RED}[오류]${NC} $1"; }
warn()    { echo -e "${YELLOW}[경고]${NC} $1"; }
header()  { echo -e "\n${BOLD}========== $1 ==========${NC}\n"; }

# --- root 권한 확인 ---
if [ "$(id -u)" -ne 0 ]; then
    error "이 스크립트는 root 권한이 필요합니다. sudo ./init.sh 로 실행하세요."
    exit 1
fi

# 실제 사용자 확인 (sudo 실행 시 원래 사용자)
REAL_USER="${SUDO_USER:-$(whoami)}"
REAL_HOME=$(eval echo "~${REAL_USER}")

header "Ubuntu 24.04 - Confluence RAG 시스템 초기 설정"
info "사용자: ${REAL_USER}"
info "홈 디렉토리: ${REAL_HOME}"

# ============================================
# 1. 시스템 패키지 업데이트
# ============================================
header "1/7 시스템 패키지 업데이트"
apt-get update -y
apt-get upgrade -y
success "시스템 패키지 업데이트 완료"

# ============================================
# 2. Python 3.12 및 필수 패키지 설치
# ============================================
header "2/7 Python 및 필수 패키지 설치"

# Ubuntu 24.04는 Python 3.12가 기본 포함
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    curl \
    wget \
    git \
    unzip

# Playwright가 사용하는 Chromium 브라우저 시스템 의존성
apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2t64 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2t64 \
    libatspi2.0-0t64 \
    libwayland-client0

PYTHON_VERSION=$(python3 --version 2>&1)
success "Python 설치 완료: ${PYTHON_VERSION}"

# ============================================
# 3. Ollama 설치
# ============================================
header "3/7 Ollama 설치"

if command -v ollama &> /dev/null; then
    info "Ollama가 이미 설치되어 있습니다."
    ollama --version
else
    info "Ollama 설치 중..."
    curl -fsSL https://ollama.com/install.sh | sh
    success "Ollama 설치 완료"
fi

# Ollama 서비스 활성화 및 시작
systemctl enable ollama
systemctl start ollama

# Ollama 서버가 준비될 때까지 대기
info "Ollama 서버 시작 대기 중..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
        success "Ollama 서버 실행 확인"
        break
    fi
    if [ "$i" -eq 30 ]; then
        warn "Ollama 서버 시작 대기 시간 초과. 수동 확인이 필요할 수 있습니다."
    fi
    sleep 1
done

# ============================================
# 4. LLM 모델 다운로드
# ============================================
header "4/7 LLM 모델 다운로드"

MODEL_NAME="anpigon/eeve-korean-10.8b"

if ollama list 2>/dev/null | grep -q "${MODEL_NAME}"; then
    info "모델 ${MODEL_NAME}이 이미 존재합니다."
else
    info "모델 다운로드 중: ${MODEL_NAME} (약 6~7GB, 시간이 소요됩니다)..."
    ollama pull "${MODEL_NAME}"
    success "모델 다운로드 완료: ${MODEL_NAME}"
fi

# ============================================
# 5. 프로젝트 디렉토리 설정
# ============================================
header "5/7 프로젝트 디렉토리 설정"

# 프로젝트 경로 (이 스크립트가 위치한 디렉토리)
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
info "프로젝트 경로: ${PROJECT_DIR}"

cd "${PROJECT_DIR}"

# 필요 디렉토리 생성
mkdir -p confluence_pages confluence_vectordb logs backups
chown -R "${REAL_USER}:${REAL_USER}" confluence_pages confluence_vectordb logs backups
success "프로젝트 디렉토리 생성 완료"

# ============================================
# 6. Python 가상환경 및 의존성 설치
# ============================================
header "6/7 Python 가상환경 및 의존성 설치"

VENV_DIR="${PROJECT_DIR}/venv"

# 가상환경 생성 (일반 사용자 권한으로)
if [ ! -d "${VENV_DIR}" ]; then
    info "가상환경 생성 중..."
    sudo -u "${REAL_USER}" python3 -m venv "${VENV_DIR}"
    success "가상환경 생성 완료"
else
    info "가상환경이 이미 존재합니다."
fi

# pip 업그레이드 및 패키지 설치 (일반 사용자 권한으로)
info "pip 업그레이드 및 패키지 설치 중..."
sudo -u "${REAL_USER}" bash -c "
    source '${VENV_DIR}/bin/activate'
    pip install --upgrade pip --quiet
    pip install -r '${PROJECT_DIR}/requirements.txt' --quiet
    pip install -r '${PROJECT_DIR}/requirements-dev.txt' --quiet
"
success "Python 패키지 설치 완료"

# Playwright 브라우저 설치 (일반 사용자 권한으로)
info "Playwright Chromium 브라우저 설치 중..."
sudo -u "${REAL_USER}" bash -c "
    source '${VENV_DIR}/bin/activate'
    playwright install chromium
"
success "Playwright Chromium 설치 완료"

# ============================================
# 7. .env 파일 설정
# ============================================
header "7/7 환경 설정 파일 확인"

if [ ! -f "${PROJECT_DIR}/.env" ]; then
    if [ -f "${PROJECT_DIR}/.env.template" ]; then
        cp "${PROJECT_DIR}/.env.template" "${PROJECT_DIR}/.env"
        chown "${REAL_USER}:${REAL_USER}" "${PROJECT_DIR}/.env"
        warn ".env 파일이 템플릿에서 생성되었습니다. 반드시 편집하세요:"
        echo -e "  ${YELLOW}nano ${PROJECT_DIR}/.env${NC}"
    else
        warn ".env.template 파일이 없습니다. 수동으로 .env를 생성하세요."
    fi
else
    info ".env 파일이 이미 존재합니다."
fi

# 셸 스크립트 실행 권한 부여
chmod +x "${PROJECT_DIR}/manager.sh"
chmod +x "${PROJECT_DIR}/backup.sh"
chmod +x "${PROJECT_DIR}/restore.sh"
chmod +x "${PROJECT_DIR}/init.sh"

# ============================================
# 설치 결과 요약
# ============================================
header "설치 완료 - 요약"

echo -e "${GREEN}[시스템]${NC}"
echo "  OS:      $(lsb_release -ds 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
echo "  Python:  $(python3 --version 2>&1)"
echo "  Ollama:  $(ollama --version 2>&1 || echo 'N/A')"
echo "  모델:    ${MODEL_NAME}"
echo ""

echo -e "${GREEN}[프로젝트]${NC}"
echo "  경로:    ${PROJECT_DIR}"
echo "  가상환경: ${VENV_DIR}"
echo ""

echo -e "${BOLD}${YELLOW}다음 단계:${NC}"
echo ""
echo "  1. .env 파일을 편집하여 Confluence 접속 정보를 입력하세요:"
echo -e "     ${BLUE}nano ${PROJECT_DIR}/.env${NC}"
echo ""
echo "  2. 전체 데이터 구축 (크롤링 + 벡터DB):"
echo -e "     ${BLUE}cd ${PROJECT_DIR} && ./manager.sh full-update${NC}"
echo ""
echo "  3. 웹 UI 시작:"
echo -e "     ${BLUE}./manager.sh start${NC}"
echo ""
echo "  4. 환경 상태 확인:"
echo -e "     ${BLUE}./manager.sh check${NC}"
echo ""
success "Ubuntu 24.04 초기 설정이 완료되었습니다!"
