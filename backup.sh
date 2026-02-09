#!/usr/bin/env bash
# ============================================
# Confluence AI 검색 - 백업 스크립트
# 사용법: ./backup.sh
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

echo -e "\n${BOLD}===== Confluence AI 검색 - 백업 =====${NC}\n"

# --- 설정 ---
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="backups"
BACKUP_NAME="backup_${TIMESTAMP}"
BACKUP_FILE="${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
CHECKSUM_FILE="${BACKUP_DIR}/${BACKUP_NAME}.sha256"
RETENTION_DAYS=30           # 백업 보관 기간 (일)
MIN_DISK_SPACE_MB=500       # 최소 디스크 여유 공간 (MB)

# --- 1단계: 디스크 공간 확인 ---
info "디스크 공간 확인 중..."
available_mb=$(df -m . | awk 'NR==2 {print $4}')

if [ "${available_mb}" -lt "${MIN_DISK_SPACE_MB}" ]; then
    error "디스크 공간이 부족합니다. (사용 가능: ${available_mb}MB, 필요: ${MIN_DISK_SPACE_MB}MB)"
    exit 1
fi
info "디스크 여유 공간: ${available_mb}MB"

# --- 2단계: 백업 디렉토리 생성 ---
mkdir -p "${BACKUP_DIR}"

# --- 3단계: 백업 대상 파일 목록 구성 ---
info "백업 대상 파일 확인 중..."
BACKUP_TARGETS=()

# 벡터 DB 디렉토리
if [ -d "confluence_vectordb" ]; then
    BACKUP_TARGETS+=("confluence_vectordb")
    info "  포함: confluence_vectordb/"
else
    warn "  없음: confluence_vectordb/ (건너뜀)"
fi

# 크롤링 백업 JSON
if [ -f "confluence_backup.json" ]; then
    BACKUP_TARGETS+=("confluence_backup.json")
    info "  포함: confluence_backup.json"
fi

# 동기화 상태 파일
if [ -f "last_sync.json" ]; then
    BACKUP_TARGETS+=("last_sync.json")
    info "  포함: last_sync.json"
fi

# 전처리된 청크 데이터
if [ -f "processed_chunks.json" ]; then
    BACKUP_TARGETS+=("processed_chunks.json")
    info "  포함: processed_chunks.json"
fi

# 로그 파일 (최근 30일)
if [ -d "logs" ]; then
    # 최근 30일 로그만 임시 디렉토리에 복사 후 백업
    TEMP_LOGS=$(mktemp -d)
    find logs -name "*.log" -mtime -30 -exec cp {} "${TEMP_LOGS}/" \; 2>/dev/null || true
    log_count=$(find "${TEMP_LOGS}" -name "*.log" 2>/dev/null | wc -l | tr -d ' ')
    if [ "${log_count}" -gt 0 ]; then
        BACKUP_TARGETS+=("${TEMP_LOGS}")
        info "  포함: 최근 30일 로그 (${log_count}개)"
    fi
fi

# 백업할 대상 확인
if [ ${#BACKUP_TARGETS[@]} -eq 0 ]; then
    warn "백업할 파일이 없습니다."
    exit 0
fi

# --- 4단계: 압축 ---
info "백업 파일 생성 중: ${BACKUP_FILE}"

# tar 생성 (임시 로그 디렉토리는 logs/로 이름 변경하여 포함)
TAR_ARGS=()
for target in "${BACKUP_TARGETS[@]}"; do
    if [[ "${target}" == /tmp/* ]]; then
        # 임시 로그 디렉토리를 logs 이름으로 변환
        TAR_ARGS+=("--transform=s|${target#/}|logs|" "${target}")
    else
        TAR_ARGS+=("${target}")
    fi
done

if ! tar -czf "${BACKUP_FILE}" "${TAR_ARGS[@]}" 2>/dev/null; then
    error "압축 실패! 백업 파일을 삭제합니다."
    rm -f "${BACKUP_FILE}"
    # 임시 디렉토리 정리
    [ -n "${TEMP_LOGS:-}" ] && rm -rf "${TEMP_LOGS}"
    exit 1
fi

# 임시 디렉토리 정리
[ -n "${TEMP_LOGS:-}" ] && rm -rf "${TEMP_LOGS}"

# --- 5단계: 체크섬 생성 ---
info "체크섬 파일 생성 중..."
if command -v sha256sum &> /dev/null; then
    sha256sum "${BACKUP_FILE}" > "${CHECKSUM_FILE}"
elif command -v shasum &> /dev/null; then
    shasum -a 256 "${BACKUP_FILE}" > "${CHECKSUM_FILE}"
else
    warn "sha256sum/shasum을 찾을 수 없어 체크섬을 건너뜁니다."
fi

# --- 6단계: 오래된 백업 삭제 ---
info "오래된 백업 정리 중 (${RETENTION_DAYS}일 이상)..."
deleted_count=0
while IFS= read -r old_file; do
    rm -f "${old_file}"
    # 대응하는 체크섬 파일도 삭제
    rm -f "${old_file%.tar.gz}.sha256"
    deleted_count=$((deleted_count + 1))
done < <(find "${BACKUP_DIR}" -name "backup_*.tar.gz" -mtime +${RETENTION_DAYS} 2>/dev/null)

if [ "${deleted_count}" -gt 0 ]; then
    info "${deleted_count}개 오래된 백업 삭제됨"
fi

# --- 7단계: 결과 출력 ---
backup_size=$(du -h "${BACKUP_FILE}" | cut -f1)
total_backups=$(find "${BACKUP_DIR}" -name "backup_*.tar.gz" 2>/dev/null | wc -l | tr -d ' ')

echo ""
echo -e "${BOLD}===== 백업 결과 =====${NC}"
echo -e "  백업 파일:   ${GREEN}${BACKUP_FILE}${NC}"
echo -e "  체크섬 파일: ${CHECKSUM_FILE}"
echo -e "  파일 크기:   ${backup_size}"
echo -e "  총 백업 수:  ${total_backups}개"
echo -e "  보관 기간:   ${RETENTION_DAYS}일"
echo ""
success "백업 완료!"
