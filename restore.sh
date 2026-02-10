#!/usr/bin/env bash
# ============================================
# Confluence AI 검색 - 복구 스크립트
# 사용법: ./restore.sh <백업 파일 경로>
# ============================================

set -euo pipefail

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

echo -e "\n${BOLD}===== 복구 =====${NC}\n"

# --- 매개변수 확인 ---
BACKUP_FILE="${1:-}"
if [ -z "${BACKUP_FILE}" ]; then
    error "백업 파일 경로를 지정해주세요."
    echo ""
    echo "사용법: ./restore.sh <백업 파일>"
    echo "예시:   ./restore.sh backups/backup_20250209_100000.tar.gz"
    echo ""
    if [ -d "backups" ]; then
        echo "사용 가능한 백업:"
        find backups -name "backup_*.tar.gz" -exec ls -lh {} \; 2>/dev/null | \
            awk '{print "  " $NF " (" $5 ")"}'
    fi
    exit 1
fi

if [ ! -f "${BACKUP_FILE}" ]; then
    error "파일을 찾을 수 없습니다: ${BACKUP_FILE}"
    exit 1
fi

info "백업 파일: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | cut -f1))"

# --- 체크섬 검증 ---
CHECKSUM_FILE="${BACKUP_FILE%.tar.gz}.sha256"
if [ -f "${CHECKSUM_FILE}" ]; then
    info "체크섬 검증 중..."
    if command -v sha256sum &> /dev/null; then
        sha256sum -c "${CHECKSUM_FILE}" --quiet 2>/dev/null && success "체크섬 통과" || {
            error "체크섬 불일치!"
            read -rp "계속하시겠습니까? (y/N): " fc
            [[ "${fc}" != "y" && "${fc}" != "Y" ]] && exit 1
        }
    elif command -v shasum &> /dev/null; then
        shasum -a 256 -c "${CHECKSUM_FILE}" --quiet 2>/dev/null && success "체크섬 통과" || {
            error "체크섬 불일치!"
            read -rp "계속하시겠습니까? (y/N): " fc
            [[ "${fc}" != "y" && "${fc}" != "Y" ]] && exit 1
        }
    else
        warn "체크섬 도구 없음. 검증 건너뜀."
    fi
else
    warn "체크섬 파일 없음. 검증 건너뜀."
fi

# --- 복구 확인 ---
warn "현재 데이터가 덮어씌워집니다."
read -rp "복구를 진행하시겠습니까? (y/N): " confirm
[[ "${confirm}" != "y" && "${confirm}" != "Y" ]] && { info "취소됨"; exit 0; }

# --- 기존 데이터 백업 ---
ROLLBACK_DIR=".restore_rollback_$(date +%Y%m%d_%H%M%S)"
mkdir -p "${ROLLBACK_DIR}"
for item in confluence_vectordb confluence_backup.json last_sync.json processed_chunks.json; do
    [ -e "${item}" ] && cp -r "${item}" "${ROLLBACK_DIR}/" && info "보관: ${item}"
done

# --- 압축 해제 ---
info "복원 중..."
if ! tar -xzf "${BACKUP_FILE}" 2>/dev/null; then
    error "압축 해제 실패. 롤백합니다."
    for item in "${ROLLBACK_DIR}"/*; do
        base=$(basename "${item}")
        rm -rf "${base}" && cp -r "${item}" "${base}"
    done
    rm -rf "${ROLLBACK_DIR}"
    error "롤백 완료"
    exit 1
fi

success "복원 완료"

# --- 결과 확인 ---
echo ""
echo -e "${BOLD}복구 결과:${NC}"
for item in confluence_vectordb confluence_backup.json last_sync.json processed_chunks.json; do
    if [ -e "${item}" ]; then
        [ -d "${item}" ] && size=$(du -sh "${item}" | cut -f1) || size=$(du -h "${item}" | cut -f1)
        echo -e "  ${GREEN}✓${NC} ${item} (${size})"
    else
        echo -e "  ${YELLOW}✗${NC} ${item}"
    fi
done

echo ""
info "롤백 데이터: ${ROLLBACK_DIR}/"
read -rp "롤백 데이터를 삭제할까요? (y/N): " del
[[ "${del}" == "y" || "${del}" == "Y" ]] && rm -rf "${ROLLBACK_DIR}" && info "삭제 완료"

echo ""
success "복구 완료!"
