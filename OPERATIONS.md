# 📋 운영 가이드

Confluence AI 검색 시스템의 일상 운영, 장애 대응, 백업 절차를 안내합니다.

---

## 1. 일일 체크리스트

매일 아침 다음 항목을 확인하세요.

### 서비스 상태 확인

- [ ] **Gradio UI 접속 확인**
  ```bash
  curl -s -o /dev/null -w "%{http_code}" http://localhost:7860
  # 200이면 정상
  ```

- [ ] **Docker 컨테이너 상태**
  ```bash
  ./docker_manager.sh stats
  # 또는
  docker ps --filter name=confluence-ai-search
  ```

- [ ] **Ollama 서버 상태**
  ```bash
  curl http://localhost:11434/api/tags
  ```

### 로그 모니터링

- [ ] **에러 로그 확인**
  ```bash
  # 최근 로그에서 오류 검색
  grep -i "error\|오류\|실패" logs/update_*.log | tail -20
  ```

- [ ] **Docker 로그 확인**
  ```bash
  ./docker_manager.sh logs
  # Ctrl+C로 종료
  ```

- [ ] **디스크 사용량 확인**
  ```bash
  python show_stats.py
  # 디스크 사용률 90% 이상 시 정리 필요
  ```

---

## 2. 주간 작업

매주 월요일 또는 지정된 요일에 수행합니다.

### 2.1 증분 업데이트 실행

- [ ] **업데이트 전 상태 확인**
  ```bash
  python show_stats.py
  ```

- [ ] **증분 업데이트 실행**
  ```bash
  # 로컬 환경
  python weekly_update.py

  # Docker 환경
  ./docker_manager.sh update
  ```

- [ ] **업데이트 결과 확인**
  ```bash
  # 로그 확인
  ls -lt logs/update_*.log | head -1
  # 최신 로그 파일 열기

  # 통계 확인
  python show_stats.py
  ```

### 2.2 업데이트 결과 검증

- [ ] **검색 테스트** (웹 UI에서 2-3개 질문으로 검증)
  - 최근 추가된 문서 내용으로 질문
  - 기존 문서 내용으로 질문
  - 답변 품질과 출처 링크 확인

- [ ] **벡터 DB 통계 확인**
  ```bash
  python show_stats.py --json | python -m json.tool
  ```

### 2.3 백업

- [ ] **주간 백업 실행**
  ```bash
  ./backup.sh
  ```

- [ ] **백업 파일 확인**
  ```bash
  ls -lh backups/backup_*.tar.gz | tail -5
  ```

---

## 3. 월간 작업

매월 첫째 주에 수행합니다.

### 3.1 전체 재구축

월 1회 전체 재구축으로 데이터 정합성을 보장합니다.

- [ ] **전체 재구축 전 백업**
  ```bash
  ./backup.sh
  ```

- [ ] **전체 재구축 실행**
  ```bash
  # 로컬
  python weekly_update.py --full

  # Docker
  ./docker_manager.sh full-update
  ```

- [ ] **재구축 후 검증**
  ```bash
  python show_stats.py
  # 웹 UI에서 검색 테스트
  ```

### 3.2 성능 분석

- [ ] **벡터 DB 크기 추이 확인**
  ```bash
  du -sh confluence_vectordb/
  ```

- [ ] **크롤링 페이지 수 추이 확인**
  ```bash
  python show_stats.py --json | python -c "
  import sys, json
  data = json.load(sys.stdin)
  print(f\"총 페이지: {data['crawl']['total_pages']}\")
  print(f\"총 벡터: {data['vectordb']['total_vectors']}\")
  "
  ```

- [ ] **로그 분석** (에러 패턴 확인)
  ```bash
  # 이번 달 에러 집계
  grep -c "ERROR\|오류" logs/update_*.log | sort -t: -k2 -nr | head -10
  ```

### 3.3 디스크 정리

- [ ] **오래된 로그 정리**
  ```bash
  # 90일 이상 된 로그 삭제
  find logs/ -name "*.log" -mtime +90 -delete
  ```

- [ ] **오래된 백업 정리** (backup.sh가 자동으로 30일 이상 삭제)
  ```bash
  ls -lh backups/
  ```

- [ ] **Docker 리소스 정리**
  ```bash
  ./docker_manager.sh cleanup
  ```

- [ ] **롤백 디렉토리 정리**
  ```bash
  # 2주 이상 된 롤백 데이터 확인 후 삭제
  find backups/ -name "rollback_*" -mtime +14 -type d
  ```

---

## 4. 장애 대응

### 4.1 서비스 다운 시

**증상:** 웹 UI 접속 불가 (http://localhost:7860)

**진단 순서:**

```bash
# 1. 컨테이너 상태 확인
docker ps -a --filter name=confluence-ai-search

# 2. 컨테이너 로그 확인
docker logs confluence-ai-search --tail 50

# 3. 헬스체크 상태
docker inspect confluence-ai-search --format='{{.State.Health.Status}}'
```

**조치:**

```bash
# 컨테이너 재시작
./docker_manager.sh restart

# 그래도 안되면 재빌드
./docker_manager.sh build
./docker_manager.sh start
```

### 4.2 업데이트 실패 시

**증상:** `weekly_update.py` 실행 중 오류 발생

**진단:**

```bash
# 최신 로그 확인
cat logs/update_*.log | tail -50

# 각 단계별 확인
# 크롤링 실패?
python confluence_crawler.py --full 2>&1 | tail -20

# 전처리 실패?
python preprocess_data.py 2>&1 | tail -20

# 벡터화 실패?
python build_vectordb.py 2>&1 | tail -20
```

**조치:**

| 실패 단계 | 조치 |
|-----------|------|
| 환경 확인 | `.env` 파일, Ollama 서버 확인 |
| 크롤링 | Confluence 접속 정보 확인, 네트워크 상태 확인 |
| 전처리 | `confluence_backup.json` 파일 존재 여부 확인 |
| 벡터화 | 메모리 확인, `--batch-size` 줄이기 |

**자동 롤백 확인:**

```bash
# weekly_update.py가 자동으로 롤백했는지 확인
ls -lt backups/rollback_*
```

### 4.3 검색 오류 시

**증상:** 검색 결과가 부정확하거나 "문서에서 찾을 수 없습니다" 반복

**진단:**

```bash
# 벡터 DB 상태 확인
python show_stats.py

# 벡터 수가 0이면 재구축 필요
# 청크 수 대비 벡터 수가 적으면 임베딩 오류 가능
```

**조치:**

```bash
# 1. 벡터 DB 검증
python -c "
from build_vectordb import verify_vectordb
verify_vectordb()
"

# 2. 벡터 DB 재구축
python build_vectordb.py --rebuild

# 3. 전체 파이프라인 재실행
python weekly_update.py --full
```

### 4.4 Ollama 오류 시

**증상:** "Ollama 연결 실패" 메시지

```bash
# Ollama 프로세스 확인
pgrep -f ollama

# Ollama 재시작
ollama serve &

# 모델 확인
ollama list

# 모델 재다운로드
ollama pull eeve-korean-10.8b
```

---

## 5. 모니터링

### 주요 메트릭

| 메트릭 | 정상 범위 | 경고 임계값 | 확인 방법 |
|--------|----------|------------|-----------|
| UI 응답 시간 | < 1초 | > 3초 | 브라우저에서 체감 |
| 검색 응답 시간 | < 10초 | > 30초 | 검색 결과의 "소요 시간" |
| 디스크 사용률 | < 70% | > 90% | `python show_stats.py` |
| 벡터 DB 크기 | - | > 5GB | `du -sh confluence_vectordb/` |
| 컨테이너 메모리 | < 2GB | > 4GB | `docker stats` |
| 크롤링 실패율 | 0% | > 10% | 로그의 failed 카운트 |

### 간이 모니터링 스크립트

다음을 crontab에 등록하여 자동 모니터링할 수 있습니다:

```bash
# crontab -e
# 매 5분마다 서비스 상태 확인
*/5 * * * * curl -sf http://localhost:7860 > /dev/null || echo "$(date) Confluence AI 서비스 다운" >> /path/to/logs/monitor.log

# 매주 월요일 오전 6시에 증분 업데이트
0 6 * * 1 cd /path/to/confluence && python weekly_update.py >> logs/cron_update.log 2>&1

# 매일 자정에 백업
0 0 * * * cd /path/to/confluence && ./backup.sh >> logs/cron_backup.log 2>&1
```

### 알림 설정 (선택사항)

Slack 웹훅을 활용한 알림 예시:

```bash
# 서비스 다운 시 Slack 알림
SLACK_WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

if ! curl -sf http://localhost:7860 > /dev/null; then
    curl -X POST "$SLACK_WEBHOOK" \
        -H 'Content-type: application/json' \
        -d '{"text":"⚠️ Confluence AI 검색 서비스가 응답하지 않습니다."}'
fi
```

---

## 6. 백업 및 복구

### 백업 주기

| 백업 유형 | 주기 | 보관 기간 | 실행 방법 |
|-----------|------|----------|-----------|
| 자동 백업 | 매일 | 30일 | crontab + `backup.sh` |
| 수동 백업 | 업데이트 전 | 영구 | `./backup.sh` |
| 롤백 백업 | 업데이트 시 자동 | 14일 | `weekly_update.py` 자동 |

### 백업 항목

```
backups/backup_YYYYMMDD_HHMMSS.tar.gz
├── confluence_vectordb/     # 벡터 데이터베이스
├── confluence_backup.json   # 크롤링 원본 데이터
├── last_sync.json           # 동기화 상태
├── processed_chunks.json    # 전처리된 청크
└── logs/                    # 최근 30일 로그
```

### 복구 절차

```bash
# 1. 사용 가능한 백업 목록 확인
ls -lh backups/backup_*.tar.gz

# 2. 체크섬 검증 (자동)
# 3. 기존 데이터 보관 (자동)
# 4. 복구 실행
./restore.sh backups/backup_20250209_100000.tar.gz

# 5. 복구 후 검증
python show_stats.py
# 웹 UI에서 검색 테스트
```

### 복구 테스트 (분기별 권장)

분기 1회 이상 복구 절차를 테스트하여 백업 무결성을 확인합니다:

- [ ] 최신 백업 파일 선택
- [ ] 테스트 디렉토리에 복구 시도
  ```bash
  mkdir /tmp/restore_test && cd /tmp/restore_test
  tar -xzf /path/to/backups/backup_latest.tar.gz
  ls -la  # 파일 존재 확인
  ```
- [ ] 체크섬 일치 확인
- [ ] 벡터 DB 무결성 확인 (파일 손상 여부)
- [ ] 테스트 디렉토리 정리
  ```bash
  rm -rf /tmp/restore_test
  ```
