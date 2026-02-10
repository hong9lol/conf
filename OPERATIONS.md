# 운영 가이드

## 1. 일상 운영 체크리스트

### 매일

```bash
# 1. 환경 상태 확인
./manager.sh check

# 2. Gradio UI 실행 확인
#    check 결과에서 "Gradio UI: 실행 중" 확인
#    중지 상태라면:
./manager.sh start
```

### 매주

```bash
# 1. 증분 업데이트 (변경된 페이지만 처리)
./manager.sh update

# 2. 통계 확인
./manager.sh stats

# 3. 데이터 백업
./manager.sh backup
```

### 매월

```bash
# 1. 전체 재구축 (데이터 정합성 보장)
./manager.sh full-update

# 2. 임시 파일 정리
./manager.sh cleanup

# 3. 환경 전체 점검
python check_setup.py

# 4. 테스트 실행
./manager.sh test
```

## 2. 자동화 (crontab)

```bash
crontab -e
```

### 권장 스케줄

```cron
# 매주 월요일 06:00 - 증분 업데이트
0 6 * * 1 cd /path/to/confluence && ./manager.sh update >> logs/cron_update.log 2>&1

# 매주 월요일 07:00 - 백업
0 7 * * 1 cd /path/to/confluence && ./manager.sh backup >> logs/cron_backup.log 2>&1

# 매월 1일 04:00 - 전체 재구축
0 4 1 * * cd /path/to/confluence && ./manager.sh full-update >> logs/cron_full.log 2>&1

# 매일 00:00 - Gradio 프로세스 확인 및 재시작
0 0 * * * cd /path/to/confluence && ./manager.sh restart >> logs/cron_restart.log 2>&1
```

| 작업 | 주기 | 시간 | 예상 소요 |
|------|------|------|----------|
| 증분 업데이트 | 매주 | 월 06:00 | 5~30분 |
| 백업 | 매주 | 월 07:00 | 1~5분 |
| 전체 재구축 | 매월 | 1일 04:00 | 30분~2시간 |
| Gradio 재시작 | 매일 | 00:00 | 10초 |

## 3. 장애 대응

### 장애 1: Ollama 서버 응답 없음

**증상:**
```
Ollama 서버에 연결할 수 없습니다 (http://localhost:11434)
```

**진단:**
```bash
# Ollama 프로세스 확인
ps aux | grep ollama

# 포트 확인
lsof -i :11434
```

**조치:**
```bash
# Ollama 시작
ollama serve

# 모델 확인
ollama list

# 모델 재다운로드 (필요시)
ollama pull eeve-korean-10.8b
```

### 장애 2: 크롤링 실패 (로그인 오류)

**증상:**
```
로그인 실패 또는 타임아웃
```

**진단:**
```bash
# 최근 업데이트 로그 확인
ls -lt logs/update_*.log | head -5
tail -50 logs/update_*.log
```

**조치:**
1. `.env`에서 `CONFLUENCE_USERNAME`, `CONFLUENCE_PASSWORD` 확인
2. Confluence 웹에서 직접 로그인 가능한지 확인
3. API 토큰 만료 시 재발급:
   - Atlassian → 계정 설정 → 보안 → API 토큰 관리
4. 네트워크 연결 확인

### 장애 3: 벡터 DB 손상

**증상:**
```
ChromaDB 조회 시 에러 또는 검색 결과 없음
```

**진단:**
```bash
# 벡터 DB 통계 확인
./manager.sh stats

# DB 크기 확인
du -sh confluence_vectordb/
```

**조치:**
```bash
# 방법 1: 백업에서 복구
./manager.sh restore backups/backup_YYYYMMDD_HHMMSS.tar.gz

# 방법 2: 전체 재구축
./manager.sh full-update
```

### 장애 4: Gradio UI 접속 불가

**증상:**
```
http://localhost:7860 접속 안 됨
```

**진단:**
```bash
# 프로세스 확인
./manager.sh check

# 로그 확인
tail -30 logs/gradio.log

# 포트 확인
lsof -i :7860
```

**조치:**
```bash
# 재시작
./manager.sh restart

# 로그 확인 후 문제 해결
tail -50 logs/gradio.log

# 포트 충돌 시 .env에서 포트 변경
# GRADIO_SERVER_PORT=7861
```

## 4. 백업 및 복구

### 백업 전략

| 항목 | 포함 | 보관 기간 |
|------|------|----------|
| `confluence_vectordb/` | 전체 벡터 DB | 30일 |
| `confluence_backup.json` | 크롤링 원본 데이터 | 30일 |
| `last_sync.json` | 동기화 상태 | 30일 |
| `processed_chunks.json` | 전처리 청크 데이터 | 30일 |
| `logs/` (최근 30일) | 운영 로그 | 30일 |

### 백업 실행

```bash
# manager.sh를 통한 백업
./manager.sh backup

# 또는 직접 실행
./backup.sh
```

백업 파일 구성:
- `backups/backup_YYYYMMDD_HHMMSS.tar.gz` - 압축 데이터
- `backups/backup_YYYYMMDD_HHMMSS.sha256` - 체크섬 파일

### 복구 절차

```bash
# 1. 사용 가능한 백업 확인
ls -lh backups/backup_*.tar.gz

# 2. 복구 실행
./manager.sh restore backups/backup_20250209_100000.tar.gz

# 복구 과정:
# - 체크섬 검증 (SHA256)
# - 현재 데이터를 .restore_rollback_*/ 에 보관
# - 백업 데이터 압축 해제
# - 실패 시 자동 롤백
```

### 수동 복구 (스크립트 없이)

```bash
# 1. 현재 데이터 보관
cp -r confluence_vectordb confluence_vectordb.old

# 2. 백업 해제
tar -xzf backups/backup_20250209_100000.tar.gz

# 3. 확인
./manager.sh stats
```

## 5. 모니터링

### 핵심 지표

| 지표 | 정상 범위 | 확인 방법 |
|------|----------|----------|
| 벡터 DB 크기 | 10MB ~ 5GB | `./manager.sh stats` |
| 총 페이지 수 | > 0 | `./manager.sh stats` |
| Ollama 응답 | 실행 중 | `./manager.sh check` |
| 디스크 여유 | > 5GB | `./manager.sh check` |
| Gradio 프로세스 | 실행 중 | `./manager.sh check` |
| 마지막 동기화 | 7일 이내 | `./manager.sh stats` |

### 상세 통계 확인

```bash
# Rich 대시보드 (터미널)
./manager.sh stats

# JSON 형식 출력
python show_stats.py --json

# 파일로 저장
python show_stats.py --export stats_$(date +%Y%m%d).json
```

### 로그 확인

```bash
# 최근 업데이트 로그
ls -lt logs/update_*.log | head -5

# Gradio 로그
tail -f logs/gradio.log

# 특정 날짜 로그 검색
grep "ERROR" logs/update_20250209_*.log
```

## 6. 디스크 관리

### 공간 사용 항목

| 항목 | 예상 크기 | 경로 |
|------|----------|------|
| 벡터 DB | 50MB ~ 2GB | `confluence_vectordb/` |
| 크롤링 데이터 | 10MB ~ 500MB | `confluence_pages/`, `confluence_backup.json` |
| 임베딩 모델 | 1~2GB | `~/.cache/torch/sentence_transformers/` |
| Ollama 모델 | 4~8GB | `~/.ollama/models/` |
| 백업 파일 | 50MB ~ 2GB | `backups/` |
| 로그 | 10MB ~ 100MB | `logs/` |
| Playwright | 200~400MB | `~/.cache/ms-playwright/` |

### 정리 명령어

```bash
# 캐시 + 오래된 로그 + 임시 파일 정리
./manager.sh cleanup

# 정리 대상:
# - __pycache__/ 디렉토리
# - *.pyc, *.pyo 파일
# - .pytest_cache/
# - .vectordb_progress.json
# - 90일 초과 로그 파일
# - 14일 초과 롤백 디렉토리
```

### 디스크 부족 시 대응

```bash
# 1. 현재 사용량 확인
du -sh confluence_vectordb/ confluence_pages/ backups/ logs/

# 2. 오래된 백업 수동 삭제
ls -lt backups/ | tail -5
rm backups/backup_2025MMDD_*.tar.gz backups/backup_2025MMDD_*.sha256

# 3. 오래된 로그 삭제
find logs/ -name "*.log" -mtime +30 -delete

# 4. 임시 파일 정리
./manager.sh cleanup
```

## 7. manager.sh 명령어 요약

```
./manager.sh setup         # 최초 설정
./manager.sh check         # 환경 상태 확인
./manager.sh start         # Gradio UI 시작
./manager.sh stop          # Gradio UI 중지
./manager.sh restart       # Gradio UI 재시작
./manager.sh update        # 증분 업데이트
./manager.sh full-update   # 전체 재구축
./manager.sh stats         # 통계 대시보드
./manager.sh test          # 테스트 실행
./manager.sh backup        # 백업
./manager.sh restore FILE  # 복구
./manager.sh cleanup       # 임시 파일 정리
./manager.sh help          # 도움말
```
