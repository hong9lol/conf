#!/usr/bin/env bash
# ============================================
# Confluence AI 검색 - Docker 관리 스크립트
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

# --- 유틸리티 함수 ---
info()    { echo -e "${BLUE}[정보]${NC} $1"; }
success() { echo -e "${GREEN}[성공]${NC} $1"; }
error()   { echo -e "${RED}[오류]${NC} $1"; }
warn()    { echo -e "${YELLOW}[경고]${NC} $1"; }
header()  { echo -e "\n${BOLD}===== $1 =====${NC}\n"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

get_server_port() {
    grep -E "^SERVER_PORT=" .env 2>/dev/null | cut -d= -f2 || echo "5000"
}

require_docker() {
    if ! command -v docker &> /dev/null; then
        error "Docker가 설치되어 있지 않습니다."
        exit 1
    fi
}

# Docker 볼륨 마운트 전 JSON 파일 초기화
# 파일이 없으면 Docker가 디렉토리로 생성하므로 반드시 선행 실행 필요
ensure_data_files() {
    for json_file in confluence_backup.json processed_chunks.json; do
        if [ -d "${SCRIPT_DIR}/${json_file}" ]; then
            warn "${json_file}이 디렉토리로 존재합니다. 삭제 후 파일로 재생성합니다."
            rm -rf "${SCRIPT_DIR}/${json_file}"
        fi
        if [ ! -f "${SCRIPT_DIR}/${json_file}" ]; then
            echo "[]" > "${SCRIPT_DIR}/${json_file}"
            info "${json_file} 초기화"
        fi
    done
}

# ============================================
# 1. 이미지 빌드
# ============================================
build() {
    header "Docker 이미지 빌드"
    require_docker
    info "Docker 이미지를 빌드합니다..."
    docker compose build
    success "빌드 완료"
}

# ============================================
# 2. 서버 시작
# ============================================
start() {
    header "Docker 서버 시작"
    require_docker

    local profile_flag=""
    if [[ "${1:-}" == "--with-ollama" ]]; then
        profile_flag="--profile with-ollama"
        info "Ollama 컨테이너도 함께 시작합니다."
    fi

    ensure_data_files
    docker compose ${profile_flag} up -d

    SERVER_PORT=$(get_server_port)
    success "서버 시작 완료"
    echo -e "  ${GREEN}http://localhost:${SERVER_PORT}${NC}"
    echo -e "  ${DIM}로그 확인: ./manager.sh logs${NC}"
}

# ============================================
# 3. 서버 중지
# ============================================
stop() {
    header "Docker 서버 중지"
    require_docker
    docker compose down
    success "서버 중지 완료"
}

# ============================================
# 4. 서버 재시작
# ============================================
restart() {
    header "Docker 서버 재시작"
    require_docker
    docker compose restart
    success "재시작 완료"
}

# ============================================
# 5. 로그 확인
# ============================================
logs() {
    require_docker
    docker compose logs -f "${1:-app}"
}

# ============================================
# 6. 크롤링 실행
# ============================================
crawl() {
    header "Confluence 크롤링"
    require_docker

    local full_flag=""
    if [[ "${1:-}" == "--full" ]]; then
        full_flag="--full"
        warn "전체 크롤링 모드로 실행합니다."
    else
        info "증분 크롤링 모드로 실행합니다."
    fi

    ensure_data_files
    docker compose run --rm app python confluence_crawler.py ${full_flag}
    success "크롤링 완료"
}

# ============================================
# 7. 벡터 DB 업데이트
# ============================================
update() {
    header "데이터 업데이트"
    require_docker

    local full_flag=""
    if [[ "${1:-}" == "--full" ]]; then
        full_flag="--full"
        warn "전체 재구축 모드로 실행합니다."
        read -rp "계속하시겠습니까? (y/N): " confirm
        if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
            info "취소되었습니다."
            return
        fi
    fi

    ensure_data_files
    docker compose run --rm app python weekly_update.py ${full_flag}
    success "업데이트 완료"
}

# ============================================
# 8. 백업
# ============================================
backup() {
    header "데이터 백업"
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
# 10. 생성 데이터 전체 삭제
# ============================================
clean() {
    header "생성 데이터 전체 삭제"

    echo -e "${RED}아래 항목을 모두 삭제합니다:${NC}"
    echo "  - confluence_vectordb/  (벡터 DB)"
    echo "  - confluence_pages/     (크롤링 페이지)"
    echo "  - confluence_backup.json"
    echo "  - processed_chunks.json"
    echo "  - search_history.json"
    echo "  - logs/*.log"
    echo ""
    read -rp "계속하시겠습니까? (y/N): " confirm
    if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
        info "취소되었습니다."
        return
    fi

    docker compose down 2>/dev/null || true

    rm -rf confluence_vectordb
    info "confluence_vectordb/ 삭제"

    rm -rf confluence_pages
    info "confluence_pages/ 삭제"

    rm -f confluence_backup.json processed_chunks.json search_history.json
    info "JSON 데이터 파일 삭제"

    rm -f logs/*.log
    info "로그 파일 삭제"

    success "정리 완료"
}

# ============================================
# 11. 임시 파일 정리
# ============================================
cleanup() {
    header "임시 파일 정리"

    local cleaned=0

    if find . -type d -name "__pycache__" -not -path "./.git/*" 2>/dev/null | grep -q .; then
        find . -type d -name "__pycache__" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
        info "__pycache__ 디렉토리 삭제"
        cleaned=$((cleaned + 1))
    fi

    pyc_count=$(find . -name "*.pyc" -o -name "*.pyo" 2>/dev/null | wc -l | tr -d ' ')
    if [ "${pyc_count}" -gt 0 ]; then
        find . -name "*.pyc" -o -name "*.pyo" -delete 2>/dev/null || true
        info "${pyc_count}개 .pyc/.pyo 파일 삭제"
        cleaned=$((cleaned + 1))
    fi

    if [ -f ".vectordb_progress.json" ]; then
        rm -f .vectordb_progress.json
        info ".vectordb_progress.json 삭제"
        cleaned=$((cleaned + 1))
    fi

    if [ "${cleaned}" -eq 0 ]; then
        info "정리할 파일이 없습니다."
    else
        success "정리 완료 (${cleaned}개 항목)"
    fi
}

# ============================================
# 12. 상태 확인
# ============================================
check() {
    header "환경 확인"
    require_docker

    if [ -f ".env" ]; then
        success ".env 파일: 존재"
    else
        error ".env 파일: 없음 → cp .env.template .env 후 편집하세요"
    fi

    if docker compose ps 2>/dev/null | grep -q "confluence-rag"; then
        success "앱 컨테이너: 실행 중"
        SERVER_PORT=$(get_server_port)
        echo -e "  ${GREEN}http://localhost:${SERVER_PORT}${NC}"
    else
        info "앱 컨테이너: 중지됨"
    fi

    if docker compose ps 2>/dev/null | grep -q "confluence-ollama"; then
        success "Ollama 컨테이너: 실행 중"
    else
        info "Ollama 컨테이너: 중지됨"
    fi

    if [ -d "confluence_vectordb" ] && [ "$(ls -A confluence_vectordb 2>/dev/null)" ]; then
        db_size=$(du -sh confluence_vectordb 2>/dev/null | cut -f1)
        success "벡터 DB: 존재 (${db_size})"
    else
        warn "벡터 DB: 없음 → ./manager.sh crawl --full 후 ./manager.sh update --full"
    fi

    free_space=$(df -h . | awk 'NR==2 {print $4}')
    info "디스크 여유 공간: ${free_space}"
}

# ============================================
# 도움말
# ============================================
show_help() {
    echo -e "${BOLD}Confluence AI 검색 - Docker 관리${NC}"
    echo ""
    echo "사용법: ./manager.sh [명령어]"
    echo ""
    echo -e "${BOLD}서비스:${NC}"
    echo "  build              Docker 이미지 빌드"
    echo "  start              서버 시작"
    echo "  start --with-ollama  Ollama 컨테이너 포함 시작"
    echo "  stop               서버 중지"
    echo "  restart            서버 재시작"
    echo "  logs [service]     컨테이너 로그 스트리밍 (기본: app)"
    echo "  check              상태 확인"
    echo ""
    echo -e "${BOLD}데이터:${NC}"
    echo "  crawl              증분 크롤링"
    echo "  crawl --full       전체 크롤링"
    echo "  update             증분 업데이트 (크롤링 + 벡터 DB)"
    echo "  update --full      전체 재구축"
    echo ""
    echo -e "${BOLD}유지보수:${NC}"
    echo "  backup             데이터 백업"
    echo "  restore FILE       백업에서 복구"
    echo "  clean              생성 데이터 전체 삭제"
    echo "  cleanup            임시 파일 정리 (__pycache__ 등)"
    echo ""
    echo -e "${BOLD}일반적인 사용 순서:${NC}"
    echo "  1. cp .env.template .env  # .env 편집"
    echo "  2. ./manager.sh build"
    echo "  3. ./manager.sh crawl --full"
    echo "  4. ./manager.sh update --full"
    echo "  5. ./manager.sh start"
}

# ============================================
# 명령어 라우팅
# ============================================
case "${1:-help}" in
    build)           build ;;
    start)           shift; start "$@" ;;
    stop)            stop ;;
    restart)         restart ;;
    logs)            shift; logs "$@" ;;
    crawl)           shift; crawl "$@" ;;
    update)          shift; update "$@" ;;
    backup)          backup ;;
    restore)         shift; restore "$@" ;;
    clean)           clean ;;
    cleanup)         cleanup ;;
    check)           check ;;
    help|--help|-h)  show_help ;;
    *)
        error "알 수 없는 명령어: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
