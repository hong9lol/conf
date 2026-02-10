#!/usr/bin/env bash
# ============================================
# Confluence AI 검색 - 프로젝트 관리 스크립트
# 사용법: ./manager.sh [command]
# ============================================

set -euo pipefail

# --- 색상 정의 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# --- 프로젝트 경로 ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"
PID_FILE="${SCRIPT_DIR}/.gradio.pid"

# --- 유틸리티 함수 ---
info()    { echo -e "${BLUE}[정보]${NC} $1"; }
success() { echo -e "${GREEN}[성공]${NC} $1"; }
error()   { echo -e "${RED}[오류]${NC} $1"; }
warn()    { echo -e "${YELLOW}[경고]${NC} $1"; }
header()  { echo -e "\n${BOLD}===== $1 =====${NC}\n"; }

# --- 가상환경 자동 활성화 ---
activate_venv() {
    if [ -d "${VENV_DIR}" ]; then
        source "${VENV_DIR}/bin/activate"
    else
        error "가상환경이 없습니다. 먼저 './manager.sh setup'을 실행하세요."
        exit 1
    fi
}

# ============================================
# 1. 최초 설정
# ============================================
setup() {
    header "최초 설정"

    # Python 확인
    PYTHON_CMD=""
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        error "Python을 찾을 수 없습니다. Python 3.11 이상을 설치해주세요."
        exit 1
    fi

    PY_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
    info "Python 버전: ${PY_VERSION}"

    # 가상환경 생성
    if [ ! -d "${VENV_DIR}" ]; then
        info "가상환경 생성 중..."
        $PYTHON_CMD -m venv "${VENV_DIR}"
        success "가상환경 생성 완료: ${VENV_DIR}"
    else
        info "가상환경이 이미 존재합니다."
    fi

    # 가상환경 활성화
    source "${VENV_DIR}/bin/activate"

    # 패키지 설치
    info "의존성 패키지 설치 중..."
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    success "패키지 설치 완료"

    # Playwright 브라우저 설치
    info "Playwright Chromium 설치 중..."
    playwright install chromium 2>&1 | tail -1
    success "Playwright 설치 완료"

    # .env 파일 확인
    if [ ! -f ".env" ]; then
        warn ".env 파일이 없습니다. 템플릿에서 복사합니다."
        cp .env.template .env
        warn ".env 파일을 편집하여 실제 값을 입력해주세요:"
        echo -e "  ${DIM}vim .env${NC}"
    else
        info ".env 파일이 이미 존재합니다."
    fi

    # 필요 디렉토리 생성
    mkdir -p confluence_pages confluence_vectordb logs backups

    echo ""
    success "설정 완료! 다음 단계:"
    echo -e "  1. ${DIM}.env 파일 편집${NC}"
    echo -e "  2. ${DIM}ollama serve && ollama pull eeve-korean-10.8b${NC}"
    echo -e "  3. ${DIM}./manager.sh full-update${NC}"
    echo -e "  4. ${DIM}./manager.sh start${NC}"
}

# ============================================
# 2. Gradio UI 시작
# ============================================
start_ui() {
    header "Gradio UI 시작"
    activate_venv

    # 이미 실행 중인지 확인
    if [ -f "${PID_FILE}" ]; then
        old_pid=$(cat "${PID_FILE}")
        if kill -0 "${old_pid}" 2>/dev/null; then
            warn "이미 실행 중입니다 (PID: ${old_pid})"
            info "http://localhost:${GRADIO_PORT:-7860}"
            return
        else
            rm -f "${PID_FILE}"
        fi
    fi

    # Ollama 확인
    check_ollama_silent

    # 백그라운드 실행
    GRADIO_PORT=$(grep -E "^GRADIO_SERVER_PORT=" .env 2>/dev/null | cut -d= -f2 || echo "7860")
    info "Gradio UI를 시작합니다 (포트: ${GRADIO_PORT})..."

    nohup python app.py > logs/gradio.log 2>&1 &
    echo $! > "${PID_FILE}"

    sleep 2

    pid=$(cat "${PID_FILE}")
    if kill -0 "${pid}" 2>/dev/null; then
        success "Gradio UI 시작 완료 (PID: ${pid})"
        echo -e "  ${GREEN}http://localhost:${GRADIO_PORT}${NC}"
        echo -e "  ${DIM}로그: logs/gradio.log${NC}"
    else
        error "Gradio UI 시작 실패. 로그를 확인하세요:"
        echo -e "  ${DIM}tail -20 logs/gradio.log${NC}"
        rm -f "${PID_FILE}"
    fi
}

# ============================================
# 3. Gradio UI 중지
# ============================================
stop_ui() {
    header "Gradio UI 중지"

    if [ -f "${PID_FILE}" ]; then
        pid=$(cat "${PID_FILE}")
        if kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}"
            sleep 1
            # 강제 종료 확인
            if kill -0 "${pid}" 2>/dev/null; then
                kill -9 "${pid}" 2>/dev/null || true
            fi
            success "Gradio UI 중지 완료 (PID: ${pid})"
        else
            info "프로세스가 이미 종료되었습니다."
        fi
        rm -f "${PID_FILE}"
    else
        # PID 파일이 없으면 프로세스 검색
        pids=$(pgrep -f "python app.py" 2>/dev/null || true)
        if [ -n "${pids}" ]; then
            echo "${pids}" | xargs kill 2>/dev/null || true
            success "Gradio 프로세스 종료 완료"
        else
            info "실행 중인 Gradio 프로세스가 없습니다."
        fi
    fi
}

# ============================================
# 4. 주간 증분 업데이트
# ============================================
update() {
    header "증분 업데이트"
    activate_venv

    check_ollama_silent

    info "증분 업데이트를 시작합니다..."
    python weekly_update.py
    success "증분 업데이트 완료"
}

# ============================================
# 5. 전체 재구축
# ============================================
full_update() {
    header "전체 재구축"
    activate_venv

    warn "전체 데이터를 재구축합니다. 시간이 오래 걸릴 수 있습니다."
    read -rp "계속하시겠습니까? (y/N): " confirm
    if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
        info "취소되었습니다."
        return
    fi

    check_ollama_silent

    info "전체 재구축을 시작합니다..."
    python weekly_update.py --full
    success "전체 재구축 완료"
}

# ============================================
# 6. 통계 확인
# ============================================
stats() {
    header "시스템 통계"
    activate_venv

    python show_stats.py "$@"
}

# ============================================
# 7. 테스트 실행
# ============================================
run_test() {
    header "테스트 실행"
    activate_venv

    info "pytest를 실행합니다..."
    echo ""
    python -m pytest tests/ test_integration.py -v -k "not slow" "$@"
}

# ============================================
# 8. 백업
# ============================================
backup() {
    header "백업"

    if [ -f "./backup.sh" ]; then
        bash ./backup.sh
    else
        error "backup.sh 파일을 찾을 수 없습니다."
        exit 1
    fi
}

# ============================================
# 9. 복구
# ============================================
restore() {
    local backup_file="${1:-}"

    if [ -f "./restore.sh" ]; then
        bash ./restore.sh "${backup_file}"
    else
        error "restore.sh 파일을 찾을 수 없습니다."
        exit 1
    fi
}

# ============================================
# 10. 임시 파일 정리
# ============================================
cleanup() {
    header "임시 파일 정리"

    local cleaned=0

    # Python 캐시
    if find . -type d -name "__pycache__" 2>/dev/null | grep -q .; then
        find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        info "__pycache__ 디렉토리 삭제"
        cleaned=$((cleaned + 1))
    fi

    # .pyc 파일
    pyc_count=$(find . -name "*.pyc" -o -name "*.pyo" 2>/dev/null | wc -l | tr -d ' ')
    if [ "${pyc_count}" -gt 0 ]; then
        find . -name "*.pyc" -o -name "*.pyo" -delete 2>/dev/null || true
        info "${pyc_count}개 .pyc/.pyo 파일 삭제"
        cleaned=$((cleaned + 1))
    fi

    # pytest 캐시
    if [ -d ".pytest_cache" ]; then
        rm -rf .pytest_cache
        info ".pytest_cache 삭제"
        cleaned=$((cleaned + 1))
    fi

    # 벡터DB 빌드 진행 파일
    if [ -f ".vectordb_progress.json" ]; then
        rm -f .vectordb_progress.json
        info ".vectordb_progress.json 삭제"
        cleaned=$((cleaned + 1))
    fi

    # 90일 이상 오래된 로그
    old_logs=$(find logs/ -name "*.log" -mtime +90 2>/dev/null | wc -l | tr -d ' ')
    if [ "${old_logs}" -gt 0 ]; then
        find logs/ -name "*.log" -mtime +90 -delete 2>/dev/null || true
        info "오래된 로그 ${old_logs}개 삭제 (90일 초과)"
        cleaned=$((cleaned + 1))
    fi

    # 오래된 롤백 디렉토리
    old_rollbacks=$(find . -maxdepth 1 -name ".restore_rollback_*" -mtime +14 -type d 2>/dev/null | wc -l | tr -d ' ')
    if [ "${old_rollbacks}" -gt 0 ]; then
        find . -maxdepth 1 -name ".restore_rollback_*" -mtime +14 -type d -exec rm -rf {} + 2>/dev/null || true
        info "오래된 롤백 디렉토리 ${old_rollbacks}개 삭제"
        cleaned=$((cleaned + 1))
    fi

    if [ "${cleaned}" -eq 0 ]; then
        info "정리할 파일이 없습니다."
    else
        success "정리 완료 (${cleaned}개 항목)"
    fi
}

# ============================================
# 11. Ollama 상태 확인
# ============================================
check_ollama() {
    header "환경 확인"

    # .env 파일
    if [ -f ".env" ]; then
        success ".env 파일: 존재"
    else
        error ".env 파일: 없음"
    fi

    # 가상환경
    if [ -d "${VENV_DIR}" ]; then
        success "가상환경: 존재 (${VENV_DIR})"
    else
        error "가상환경: 없음 → ./manager.sh setup 실행 필요"
    fi

    # Ollama 서버
    OLLAMA_HOST=$(grep -E "^OLLAMA_HOST=" .env 2>/dev/null | cut -d= -f2 || echo "http://localhost:11434")
    if curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; then
        success "Ollama 서버: 실행 중 (${OLLAMA_HOST})"

        # 모델 확인 (ollama list 명령어 사용)
        OLLAMA_MODEL=$(grep -E "^OLLAMA_MODEL=" .env 2>/dev/null | cut -d= -f2 || echo "eeve-korean-10.8b")
        if ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL}"; then
            success "LLM 모델: ${OLLAMA_MODEL} (설치됨)"
        else
            warn "LLM 모델: ${OLLAMA_MODEL} (미설치)"
            echo -e "  ${DIM}ollama pull ${OLLAMA_MODEL}${NC}"
        fi
    else
        error "Ollama 서버: 응답 없음"
        echo -e "  ${DIM}ollama serve${NC}"
    fi

    # Gradio UI
    if [ -f "${PID_FILE}" ] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
        GRADIO_PORT=$(grep -E "^GRADIO_SERVER_PORT=" .env 2>/dev/null | cut -d= -f2 || echo "7860")
        success "Gradio UI: 실행 중 (http://localhost:${GRADIO_PORT})"
    else
        info "Gradio UI: 중지됨"
    fi

    # 벡터 DB
    if [ -d "confluence_vectordb" ]; then
        db_size=$(du -sh confluence_vectordb 2>/dev/null | cut -f1)
        success "벡터 DB: 존재 (${db_size})"
    else
        warn "벡터 DB: 없음 → ./manager.sh full-update 실행 필요"
    fi

    # 디스크 여유 공간
    free_space=$(df -h . | awk 'NR==2 {print $4}')
    info "디스크 여유 공간: ${free_space}"
}

# Ollama 확인 (출력 없이, 경고만)
check_ollama_silent() {
    OLLAMA_HOST=$(grep -E "^OLLAMA_HOST=" .env 2>/dev/null | cut -d= -f2 || echo "http://localhost:11434")
    if ! curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; then
        warn "Ollama 서버가 응답하지 않습니다: ${OLLAMA_HOST}"
        warn "크롤링/전처리만 실행될 수 있습니다."
    fi
}

# ============================================
# 도움말
# ============================================
show_help() {
    echo -e "${BOLD}🔍 Confluence AI 검색 - 프로젝트 관리${NC}"
    echo ""
    echo "사용법: ./manager.sh [명령어]"
    echo ""
    echo -e "${BOLD}설정:${NC}"
    echo "  setup         최초 설정 (가상환경, 패키지, Playwright)"
    echo "  check         환경 상태 확인 (Ollama, 벡터DB 등)"
    echo ""
    echo -e "${BOLD}서비스:${NC}"
    echo "  start         Gradio 웹 UI 시작 (백그라운드)"
    echo "  stop          Gradio 웹 UI 중지"
    echo "  restart       Gradio 웹 UI 재시작"
    echo ""
    echo -e "${BOLD}데이터:${NC}"
    echo "  update        증분 업데이트 (변경분만)"
    echo "  full-update   전체 재구축 (크롤링부터 벡터DB까지)"
    echo "  stats         시스템 통계 대시보드"
    echo ""
    echo -e "${BOLD}유지보수:${NC}"
    echo "  test          테스트 실행 (pytest)"
    echo "  backup        데이터 백업"
    echo "  restore FILE  백업에서 복구"
    echo "  cleanup       임시 파일 정리"
    echo ""
    echo -e "${BOLD}예시:${NC}"
    echo "  ./manager.sh setup                  # 최초 1회"
    echo "  ./manager.sh full-update             # 최초 데이터 구축"
    echo "  ./manager.sh start                   # UI 시작"
    echo "  ./manager.sh update                  # 주간 업데이트"
    echo "  ./manager.sh restore backups/backup_20250209.tar.gz"
}

# ============================================
# 명령어 라우팅
# ============================================
case "${1:-help}" in
    setup)       setup ;;
    start)       start_ui ;;
    stop)        stop_ui ;;
    restart)     stop_ui; sleep 1; start_ui ;;
    update)      update ;;
    full-update) full_update ;;
    stats)       shift; stats "$@" ;;
    test)        shift; run_test "$@" ;;
    backup)      backup ;;
    restore)     shift; restore "$@" ;;
    cleanup)     cleanup ;;
    check)       check_ollama ;;
    help|--help|-h) show_help ;;
    *)
        error "알 수 없는 명령어: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
