#!/usr/bin/env bash
# ============================================
# Confluence AI 검색 - Docker 관리 스크립트
# 사용법: ./docker_manager.sh [command]
# ============================================

set -euo pipefail

# --- 색상 정의 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # 색상 초기화

# --- 프로젝트 설정 ---
PROJECT_NAME="confluence-ai-search"
COMPOSE_FILE="docker-compose.yml"
CONTAINER_NAME="confluence-ai-search"

# --- 유틸리티 함수 ---

info()    { echo -e "${BLUE}[정보]${NC} $1"; }
success() { echo -e "${GREEN}[성공]${NC} $1"; }
error()   { echo -e "${RED}[오류]${NC} $1"; }
warn()    { echo -e "${YELLOW}[경고]${NC} $1"; }
header()  { echo -e "\n${BOLD}===== $1 =====${NC}\n"; }

# docker compose 명령어 확인 (v2 vs v1)
compose_cmd() {
    if docker compose version &> /dev/null; then
        docker compose "$@"
    elif docker-compose version &> /dev/null; then
        docker-compose "$@"
    else
        error "docker compose를 찾을 수 없습니다. Docker를 설치해주세요."
        exit 1
    fi
}

# --- 관리 함수 ---

# 1. 이미지 빌드
build() {
    header "Docker 이미지 빌드"
    info "이미지를 빌드합니다..."
    compose_cmd build --no-cache
    success "이미지 빌드 완료"
}

# 2. 서비스 시작
start() {
    header "서비스 시작"
    info "서비스를 시작합니다..."
    compose_cmd up -d
    success "서비스 시작 완료"
    echo ""
    info "Gradio UI: http://localhost:7860"
    info "상태 확인: ./docker_manager.sh stats"
}

# 3. 서비스 중지
stop() {
    header "서비스 중지"
    info "서비스를 중지합니다..."
    compose_cmd down
    success "서비스 중지 완료"
}

# 4. 서비스 재시작
restart() {
    header "서비스 재시작"
    stop
    start
}

# 5. 로그 확인
logs() {
    header "서비스 로그"
    info "로그를 표시합니다 (Ctrl+C로 종료)..."
    echo ""
    compose_cmd logs -f --tail=100
}

# 6. 증분 업데이트
update() {
    header "증분 업데이트"
    info "컨테이너 내부에서 증분 업데이트를 실행합니다..."

    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        error "컨테이너가 실행 중이지 않습니다. 먼저 start를 실행해주세요."
        exit 1
    fi

    docker exec -it "${CONTAINER_NAME}" python weekly_update.py
    success "증분 업데이트 완료"
}

# 7. 전체 재구축
full_update() {
    header "전체 재구축"
    warn "전체 데이터를 재구축합니다. 시간이 오래 걸릴 수 있습니다."
    read -rp "계속하시겠습니까? (y/N): " confirm
    if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
        info "취소되었습니다."
        return
    fi

    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        error "컨테이너가 실행 중이지 않습니다. 먼저 start를 실행해주세요."
        exit 1
    fi

    docker exec -it "${CONTAINER_NAME}" python weekly_update.py --full
    success "전체 재구축 완료"
}

# 8. 컨테이너 쉘 접속
shell() {
    header "컨테이너 쉘 접속"

    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        error "컨테이너가 실행 중이지 않습니다."
        exit 1
    fi

    info "컨테이너 쉘에 접속합니다 (exit로 종료)..."
    docker exec -it "${CONTAINER_NAME}" /bin/bash
}

# 9. 정리
cleanup() {
    header "Docker 리소스 정리"
    warn "중지된 컨테이너와 미사용 이미지를 삭제합니다."
    read -rp "계속하시겠습니까? (y/N): " confirm
    if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
        info "취소되었습니다."
        return
    fi

    info "중지된 컨테이너 정리..."
    docker container prune -f

    info "미사용 이미지 정리..."
    docker image prune -f

    info "미사용 볼륨 정리..."
    docker volume prune -f

    success "정리 완료"
}

# 10. 통계 확인
stats() {
    header "서비스 상태 및 통계"

    # 컨테이너 상태
    echo -e "${BOLD}[컨테이너 상태]${NC}"
    compose_cmd ps
    echo ""

    # 실행 중인 컨테이너 리소스 사용량
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo -e "${BOLD}[리소스 사용량]${NC}"
        docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" \
            "${CONTAINER_NAME}"
        echo ""

        # 벡터 DB 크기
        if [ -d "confluence_vectordb" ]; then
            db_size=$(du -sh confluence_vectordb 2>/dev/null | cut -f1)
            echo -e "${BOLD}[데이터 통계]${NC}"
            info "벡터 DB 크기: ${db_size}"
        fi

        # 크롤링 페이지 수
        if [ -d "confluence_pages" ]; then
            page_count=$(find confluence_pages -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
            info "크롤링된 페이지: ${page_count}개"
        fi

        # 로그 크기
        if [ -d "logs" ]; then
            log_size=$(du -sh logs 2>/dev/null | cut -f1)
            info "로그 크기: ${log_size}"
        fi
    else
        warn "컨테이너가 실행 중이지 않습니다."
    fi
}

# 11. 백업 실행
backup() {
    header "백업 실행"
    if [ -f "./backup.sh" ]; then
        bash ./backup.sh
    else
        error "backup.sh 파일을 찾을 수 없습니다."
        exit 1
    fi
}

# --- 도움말 ---
show_help() {
    echo -e "${BOLD}Confluence AI 검색 - Docker 관리 스크립트${NC}"
    echo ""
    echo "사용법: ./docker_manager.sh [명령어]"
    echo ""
    echo -e "${BOLD}명령어:${NC}"
    echo "  build        Docker 이미지 빌드"
    echo "  start        서비스 시작"
    echo "  stop         서비스 중지"
    echo "  restart      서비스 재시작"
    echo "  logs         로그 실시간 확인"
    echo "  update       증분 업데이트 실행"
    echo "  full-update  전체 재구축 실행"
    echo "  shell        컨테이너 쉘 접속"
    echo "  cleanup      중지된 컨테이너/이미지 정리"
    echo "  stats        상태 및 통계 확인"
    echo "  backup       데이터 백업"
    echo "  help         이 도움말 표시"
    echo ""
    echo -e "${BOLD}예시:${NC}"
    echo "  ./docker_manager.sh build && ./docker_manager.sh start"
    echo "  ./docker_manager.sh update"
    echo "  ./docker_manager.sh logs"
}

# --- 명령어 라우팅 ---
case "${1:-help}" in
    build)       build ;;
    start)       start ;;
    stop)        stop ;;
    restart)     restart ;;
    logs)        logs ;;
    update)      update ;;
    full-update) full_update ;;
    shell)       shell ;;
    cleanup)     cleanup ;;
    stats)       stats ;;
    backup)      backup ;;
    help|--help|-h) show_help ;;
    *)
        error "알 수 없는 명령어: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
