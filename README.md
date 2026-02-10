# Confluence AI 검색 시스템

Confluence 위키 페이지를 자동 수집하고, 벡터 DB에 저장하여
자연어로 질문하면 관련 문서를 찾아 AI가 답변하는 RAG 시스템입니다.

```
┌─────────────────────────────────────────────────────┐
│                    사용자 질문                        │
│               "배포 절차가 어떻게 돼?"                 │
└───────────────┬─────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────┐
│        Gradio 웹 UI          │  ← app.py (포트 7860)
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│    RAG 검색 엔진              │  ← rag_search.py
│  ┌──────────┐  ┌───────────┐ │
│  │ 벡터 검색 │  │  LLM 응답  │ │
│  │ ChromaDB │  │  Ollama   │ │
│  └──────────┘  └───────────┘ │
└───────────────────────────────┘
                ▲
                │ 데이터 파이프라인
┌───────────────┴───────────────┐
│  크롤링 → 전처리 → 벡터화     │
│  Playwright   Chunk   Embed  │
└───────────────────────────────┘
```

## 요구사항

| 항목 | 최소 요구사항 |
|------|-------------|
| Python | 3.8 이상 (3.11+ 권장) |
| OS | macOS / Linux / Windows (WSL) |
| RAM | 8GB 이상 (임베딩 모델 로드용) |
| 디스크 | 5GB 이상 여유 공간 |
| Ollama | 설치 및 모델 다운로드 필요 |

## 빠른 시작

### 1. 최초 설정

```bash
# 프로젝트 클론
git clone <repository-url>
cd confluence

# 자동 설정 (가상환경 + 패키지 + Playwright)
./manager.sh setup

# .env 파일 편집 (Confluence 접속 정보 입력)
vim .env

# Ollama LLM 모델 다운로드
ollama serve                      # 터미널 1
ollama pull eeve-korean-10.8b     # 터미널 2

# 환경 점검
./manager.sh check
```

### 2. 최초 데이터 구축

```bash
# 전체 크롤링 → 전처리 → 벡터 DB 구축
./manager.sh full-update
```

### 3. 검색 UI 시작

```bash
# Gradio 웹 UI 시작 (백그라운드)
./manager.sh start

# 브라우저에서 접속
# http://localhost:7860
```

### 4. 주간 운영

```bash
# 변경된 페이지만 업데이트
./manager.sh update

# 통계 확인
./manager.sh stats

# 데이터 백업
./manager.sh backup
```

## 환경 설정 (.env)

`.env.template`을 `.env`로 복사하고 실제 값을 입력합니다.

| 변수 | 설명 | 예시 |
|------|------|------|
| `CONFLUENCE_BASE_URL` | Confluence 기본 URL | `https://company.atlassian.net/wiki` |
| `CONFLUENCE_USERNAME` | 로그인 이메일 | `user@company.com` |
| `CONFLUENCE_PASSWORD` | API 토큰 또는 비밀번호 | `xxxxxxxxxxx` |
| `ROOT_PAGE_URL` | 크롤링 시작 페이지 URL | `https://company.atlassian.net/wiki/spaces/TEAM/pages/123456/Root` |
| `OLLAMA_HOST` | Ollama 서버 주소 | `http://localhost:11434` |
| `OLLAMA_MODEL` | LLM 모델명 | `eeve-korean-10.8b` |
| `GRADIO_SERVER_PORT` | 웹 UI 포트 | `7860` |
| `LOG_LEVEL` | 로그 레벨 | `INFO` |

## 관리 스크립트 (manager.sh)

모든 작업은 `./manager.sh` 명령어 하나로 관리합니다.

```bash
./manager.sh [명령어]
```

### 설정

| 명령어 | 설명 |
|--------|------|
| `setup` | 최초 설정 (가상환경, 패키지, Playwright 설치) |
| `check` | 환경 상태 확인 (.env, Ollama, 벡터DB, Gradio) |

### 서비스

| 명령어 | 설명 |
|--------|------|
| `start` | Gradio 웹 UI 시작 (백그라운드, PID 관리) |
| `stop` | Gradio 웹 UI 중지 |
| `restart` | Gradio 웹 UI 재시작 |

### 데이터

| 명령어 | 설명 |
|--------|------|
| `update` | 증분 업데이트 (변경된 페이지만 처리) |
| `full-update` | 전체 재구축 (크롤링부터 벡터DB까지) |
| `stats` | 시스템 통계 대시보드 (Rich 테이블) |

### 유지보수

| 명령어 | 설명 |
|--------|------|
| `test` | 테스트 실행 (pytest) |
| `backup` | 벡터DB + 동기화 상태 백업 (tar.gz + SHA256) |
| `restore FILE` | 백업 파일에서 복구 |
| `cleanup` | 캐시, 오래된 로그, 임시 파일 정리 |

## 전체 스크립트 목록

| 스크립트 | 설명 | 직접 실행 |
|----------|------|-----------|
| `manager.sh` | 프로젝트 관리 통합 스크립트 | `./manager.sh [명령어]` |
| `check_setup.py` | 환경 점검 (9개 항목 검사) | `python check_setup.py` |
| `show_stats.py` | 시스템 통계 대시보드 | `python show_stats.py [--json]` |
| `confluence_crawler.py` | Confluence 페이지 크롤러 | `weekly_update.py`에서 호출 |
| `sync_state.py` | 동기화 상태 관리 | 내부 모듈 |
| `preprocess_data.py` | 텍스트 전처리 + 청킹 | `python preprocess_data.py` |
| `build_vectordb.py` | 벡터 DB 구축 | `python build_vectordb.py` |
| `update_vectordb.py` | 벡터 DB 증분 업데이트 | `python update_vectordb.py` |
| `rag_search.py` | RAG 검색 엔진 | 내부 모듈 |
| `app.py` | Gradio 웹 UI | `python app.py` |
| `weekly_update.py` | 통합 업데이트 파이프라인 | `python weekly_update.py [--full]` |
| `backup.sh` | 데이터 백업 | `./backup.sh` |
| `restore.sh` | 데이터 복구 | `./restore.sh <백업파일>` |

## 프로젝트 구조

```
confluence/
├── .env.template              # 환경변수 템플릿
├── .env                       # 환경변수 (비공개)
├── .gitignore                 # Git 제외 목록
├── requirements.txt           # 운영 의존성
├── requirements-dev.txt       # 개발 의존성
├── pytest.ini                 # pytest 설정
│
├── manager.sh                 # 프로젝트 관리 스크립트 (통합)
├── backup.sh                  # 백업 스크립트
├── restore.sh                 # 복구 스크립트
│
├── confluence_crawler.py      # Confluence 크롤러
├── sync_state.py              # 동기화 상태 관리
├── preprocess_data.py         # 텍스트 전처리
├── build_vectordb.py          # 벡터 DB 구축
├── update_vectordb.py         # 벡터 DB 증분 업데이트
├── rag_search.py              # RAG 검색 엔진
├── app.py                     # Gradio 웹 UI
├── weekly_update.py           # 통합 업데이트 파이프라인
├── show_stats.py              # 시스템 통계
├── check_setup.py             # 환경 점검
│
├── conftest.py                # pytest 공용 fixture
├── test_integration.py        # 통합 테스트
├── tests/                     # 단위 테스트
│   ├── conftest.py            # 테스트 fixture
│   ├── test_crawler.py        # 크롤러 테스트
│   ├── test_preprocessing.py  # 전처리 테스트
│   ├── test_vectordb.py       # 벡터DB 테스트
│   └── test_rag.py            # RAG 테스트
│
├── confluence_pages/          # 크롤링된 MD 파일 (자동 생성)
├── confluence_vectordb/       # ChromaDB 데이터 (자동 생성)
├── logs/                      # 로그 파일 (자동 생성)
└── backups/                   # 백업 파일 (자동 생성)
```

## 트러블슈팅

### Ollama 연결 실패

```
Ollama 서버에 연결할 수 없습니다
```

Ollama 서버가 실행 중인지 확인합니다.

```bash
ollama serve          # 서버 시작
ollama list           # 설치된 모델 확인
ollama pull eeve-korean-10.8b  # 모델 다운로드
```

### Playwright 브라우저 에러

```
Executable doesn't exist at ...
```

Chromium 브라우저를 설치합니다.

```bash
playwright install chromium
```

### 벡터 DB 구축 중 메모리 부족

CUDA OOM 발생 시 자동으로 CPU로 전환됩니다. 배치 크기를 줄여볼 수도 있습니다.

```bash
python build_vectordb.py --batch-size 50
```

### 환경 전체 점검

모든 환경 요소를 한번에 검사합니다.

```bash
python check_setup.py
```

9개 항목(Python, 가상환경, 패키지, .env, Playwright, Ollama, 디렉토리, 동기화 상태, 포트)을 확인하고 문제 해결 방법을 안내합니다.

### 포트 충돌 (7860)

`.env` 파일에서 포트를 변경합니다.

```bash
GRADIO_SERVER_PORT=7861
```

## 향후 개선사항

1. Confluence REST API 직접 활용 (Playwright 대체)
2. 다중 Space 동시 크롤링
3. 사용자별 접근 권한 반영
4. 검색 결과 피드백 수집 및 랭킹 개선
5. 임베딩 모델 Fine-tuning (도메인 특화)
6. 검색 히스토리 및 분석 대시보드
7. Slack/Teams 연동 (챗봇)
8. 페이지 변경 알림 (Webhook)
9. 다국어 문서 지원
10. GPU 가속 최적화 (배치 임베딩)
