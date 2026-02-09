#!/usr/bin/env bash
# ============================================
# Confluence AI 검색 - 복구 스크립트
# 사용법: ./restore.sh <백업 파일 경로>
# 예시:   ./restore.sh backups/backup_20250209_100000.tar.gz
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
success() { echo -e "${GREEN}[성공]${NC} $1"; }
error()   { echo -e "${RED}[오류]${NC} $1"; }
warn()    { echo -e "${YELLOW}[경고]${NC} $1"; }

echo -e "\n${BOLD}===== Confluence AI 검색 - 복구 =====${NC}\n"

# --- 매개변수 확인 ---
BACKUP_FILE="${1:-}"
if [ -z "${BACKUP_FILE}" ]; then
    error "백업 파일 경로를 지정해주세요."
    echo ""
    echo "사용법: ./restore.sh <백업 파일 경로>"
    echo "예시:   ./restore.sh backups/backup_20250209_100000.tar.gz"
    echo ""
    echo "사용 가능한 백업 파일:"
    if [ -d "backups" ]; then
        find backups -name "backup_*.tar.gz" -exec ls -lh {} \; 2>/dev/null | \
            awk '{print "  " $NF " (" $5 ")"}'
    else
        echo "  (백업 디렉토리가 없습니다)"
    fi
    exit 1
fi

# --- 1단계: 백업 파일 존재 확인 ---
if [ ! -f "${BACKUP_FILE}" ]; then
    error "백업 파일을 찾을 수 없습니다: ${BACKUP_FILE}"
    exit 1
fi

backup_size=$(du -h "${BACKUP_FILE}" | cut -f1)
info "백업 파일: ${BACKUP_FILE} (${backup_size})"

# --- 2단계: 체크섬 검증 ---
CHECKSUM_FILE="${BACKUP_FILE%.tar.gz}.sha256"

if [ -f "${CHECKSUM_FILE}" ]; then
    info "체크섬 검증 중..."

    if command -v sha256sum &> /dev/null; then
        if sha256sum -c "${CHECKSUM_FILE}" --quiet 2>/dev/null; then
            success "체크섬 검증 통과"
        else
            error "체크섬 검증 실패! 백업 파일이 손상되었을 수 있습니다."
            read -rp "그래도 계속하시겠습니까? (y/N): " force_confirm
            if [[ "${force_confirm}" != "y" && "${force_confirm}" != "Y" ]]; then
                info "복구를 취소합니다."
                exit 1
            fi
        fi
    elif command -v shasum &> /dev/null; then
        if shasum -a 256 -c "${CHECKSUM_FILE}" --quiet 2>/dev/null; then
            success "체크섬 검증 통과"
        else
            error "체크섬 검증 실패! 백업 파일이 손상되었을 수 있습니다."
            read -rp "그래도 계속하시겠습니까? (y/N): " force_confirm
            if [[ "${force_confirm}" != "y" && "${force_confirm}" != "Y" ]]; then
                info "복구를 취소합니다."
                exit 1
            fi
        fi
    else
        warn "체크섬 도구를 찾을 수 없어 검증을 건너뜁니다."
    fi
else
    warn "체크섬 파일이 없습니다. 검증을 건너뜁니다."
fi

# --- 3단계: 백업 내용 미리보기 ---
info "백업 내용:"
tar -tzf "${BACKUP_FILE}" | head -20
echo "..."
echo ""

# --- 4단계: 복구 확인 ---
warn "복구를 진행하면 현재 데이터가 덮어씌워집니다."
warn "복구 대상: 벡터 DB, 동기화 상태, 백업 JSON, 청크 데이터"
echo ""
read -rp "복구를 진행하시겠습니까? (y/N): " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    info "복구를 취소합니다."
    exit 0
fi

# --- 5단계: 기존 데이터 백업 (.old 폴더) ---
ROLLBACK_DIR=".restore_rollback_$(date +%Y%m%d_%H%M%S)"
info "기존 데이터를 백업합니다: ${ROLLBACK_DIR}/"

mkdir -p "${ROLLBACK_DIR}"

# 기존 파일/디렉토리를 롤백 폴더로 이동
for item in confluence_vectordb confluence_backup.json last_sync.json processed_chunks.json; do
    if [ -e "${item}" ]; then
        cp -r "${item}" "${ROLLBACK_DIR}/"
        info "  보관: ${item}"
    fi
done

success "기존 데이터 백업 완료"

# --- 6단계: 백업 파일 압축 해제 ---
info "백업 파일을 복원합니다..."

if ! tar -xzf "${BACKUP_FILE}" 2>/dev/null; then
    error "압축 해제 실패! 기존 데이터를 복원합니다."

    # 롤백: 백업해둔 기존 데이터 복원
    for item in "${ROLLBACK_DIR}"/*; do
        base_name=$(basename "${item}")
        rm -rf "${base_name}"
        cp -r "${item}" "${base_name}"
    done

    error "롤백 완료. 원래 상태로 복원되었습니다."
    rm -rf "${ROLLBACK_DIR}"
    exit 1
fi

success "백업 파일 복원 완료"

# --- 7단계: 서비스 재시작 ---
info "서비스 재시작 확인..."

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "confluence-ai-search"; then
    info "실행 중인 컨테이너를 재시작합니다..."

    if [ -f "docker_manager.sh" ]; then
        bash docker_manager.sh restart
    else
        docker restart confluence-ai-search
    fi
    success "서비스 재시작 완료"
else
    info "실행 중인 컨테이너가 없습니다. 수동으로 시작해주세요:"
    echo "  ./docker_manager.sh start"
fi

# --- 8단계: 복구 결과 확인 ---
echo ""
echo -e "${BOLD}===== 복구 결과 =====${NC}"

# 복원된 파일 확인
for item in confluence_vectordb confluence_backup.json last_sync.json processed_chunks.json; do
    if [ -e "${item}" ]; then
        if [ -d "${item}" ]; then
            size=$(du -sh "${item}" | cut -f1)
        else
            size=$(du -h "${item}" | cut -f1)
        fi
        echo -e "  ${GREEN}✓${NC} ${item} (${size})"
    else
        echo -e "  ${YELLOW}✗${NC} ${item} (백업에 포함되지 않음)"
    fi
done

echo ""
info "롤백 데이터: ${ROLLBACK_DIR}/"
info "문제 발생 시 롤백 데이터로 수동 복원 가능합니다."
echo ""

# 롤백 데이터 삭제 확인
read -rp "복구가 정상적으로 완료되었나요? 롤백 데이터를 삭제할까요? (y/N): " cleanup_confirm
if [[ "${cleanup_confirm}" == "y" || "${cleanup_confirm}" == "Y" ]]; then
    rm -rf "${ROLLBACK_DIR}"
    info "롤백 데이터 삭제 완료"
else
    info "롤백 데이터를 유지합니다: ${ROLLBACK_DIR}/"
fi

echo ""
success "복구 완료!"
