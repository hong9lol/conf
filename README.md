# 🔍 Confluence AI 검색 시스템

Confluence 문서를 자동으로 크롤링하고, RAG(Retrieval-Augmented Generation) 기반으로
자연어 질의응답을 제공하는 AI 검색 시스템입니다.

## 📋 목차

- [프로젝트 개요](#-프로젝트-개요)
- [요구사항](#-요구사항)
- [설치 가이드](#-설치-가이드)
- [설정](#-설정)
- [사용법](#-사용법)
- [스크립트 설명](#-스크립트-설명)
- [문제 해결](#-문제-해결)
- [개발 가이드](#-개발-가이드)
- [라이센스](#-라이센스)
- [향후 개선사항](#-향후-개선사항)

---

## 🎯 프로젝트 개요

### 목적

팀의 Confluence 문서가 방대해지면서 원하는 정보를 찾기 어려운 문제를 해결합니다.
AI가 문서를 이해하고, 자연어 질문에 대해 정확한 답변과 출처를 제공합니다.

### 주요 기능

- 🕷️ **자동 크롤링**: Playwright를 이용한 Confluence 페이지 자동 수집
- 🔄 **증분 업데이트**: 변경된 페이지만 감지하여 효율적으로 업데이트
- 🧠 **RAG 검색**: 벡터 유사도 검색 + LLM 답변 생성
- 🌐 **웹 UI**: Gradio 기반 직관적인 검색 인터페이스
- 🐳 **Docker 지원**: 원클릭 배포 및 운영

### 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                    사용자 (웹 브라우저)                      │
│                   http://localhost:7860                   │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│                  Gradio 웹 UI (app.py)                    │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│              RAG 검색 엔진 (rag_search.py)                │
│                                                          │
│   ┌─────────────┐    ┌──────────┐    ┌───────────────┐  │
│   │  임베딩 모델  │    │ ChromaDB │    │  Ollama LLM   │  │
│   │ ko-sroberta  │───▶│ 벡터 검색 │───▶│ 답변 생성      │  │
│   └─────────────┘    └──────────┘    └───────────────┘  │
└──────────────────────────────────────────────────────────┘

┌──────────────────── 데이터 파이프라인 ─────────────────────┐
│                                                          │
│  Confluence ──▶ 크롤러 ──▶ 전처리 ──▶ 임베딩 ──▶ ChromaDB │
│  (웹 페이지)   (Playwright) (청크분할) (벡터변환) (벡터저장)  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 📦 요구사항

### Python 버전

- **Python 3.11** 이상

### 시스템 요구사항

| 항목 | 최소 | 권장 |
|------|------|------|
| RAM | 8GB | 16GB |
| 디스크 | 10GB | 20GB |
| GPU | 불필요 | NVIDIA (VRAM 8GB+) |

### 필수 서비스

- **Ollama**: 로컬 LLM 서버
  ```bash
  # macOS
  brew install ollama

  # Linux
  curl -fsSL https://ollama.com/install.sh | sh

  # 모델 다운로드
  ollama pull eeve-korean-10.8b
  ```

---

## 🚀 설치 가이드

### 방법 1: 로컬 설치

```bash
# 1. 저장소 클론
git clone <repository-url>
cd confluence

# 2. 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. Playwright 브라우저 설치
playwright install chromium

# 5. 환경변수 설정
cp .env.template .env
# .env 파일을 편집하여 실제 값 입력
```

### 방법 2: Docker 설치

```bash
# 1. 환경변수 설정
cp .env.template .env
# .env 파일 편집

# 2. 빌드 및 실행
./docker_manager.sh build
./docker_manager.sh start

# 또는 docker compose 직접 사용
docker compose up -d
```

---

## ⚙️ 설정

### .env 파일 설정

```bash
cp .env.template .env
```

`.env` 파일을 열고 다음 값을 입력하세요:

```env
# Confluence 접속 정보 (필수)
CONFLUENCE_BASE_URL=https://your-company.atlassian.net/wiki
CONFLUENCE_USERNAME=your-email@company.com
CONFLUENCE_PASSWORD=your-api-token

# 크롤링 시작 페이지 (필수)
ROOT_PAGE_URL=https://your-company.atlassian.net/wiki/spaces/TEAM/pages/123456/Root

# Ollama 설정
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=eeve-korean-10.8b
```

### Confluence 접근 권한

1. [Atlassian API 토큰](https://id.atlassian.com/manage-profile/security/api-tokens) 생성
2. `CONFLUENCE_PASSWORD`에 API 토큰 입력 (비밀번호가 아닌 토큰 사용)
3. 크롤링할 페이지의 읽기 권한이 있는지 확인

---

## 📖 사용법

### 최초 실행 (전체 구축)

```bash
# 1. Ollama 시작
ollama serve

# 2. 전체 파이프라인 실행
python weekly_update.py --full
```

이 명령은 다음을 순차적으로 수행합니다:
1. 환경 확인
2. Confluence 전체 크롤링
3. 데이터 전처리 (청크 분할)
4. 벡터 DB 구축
5. 결과 통계 출력

### 주간 업데이트 (증분)

```bash
# 변경된 페이지만 업데이트
python weekly_update.py

# 또는 Docker 환경에서
./docker_manager.sh update
```

### 검색 사용

```bash
# 웹 UI 시작
python app.py
# 브라우저에서 http://localhost:7860 접속

# 또는 Docker 환경에서
./docker_manager.sh start
```

### 통계 확인

```bash
python show_stats.py              # 대시보드
python show_stats.py --json       # JSON 출력
```

---

## 📜 스크립트 설명

| 스크립트 | 용도 | 실행 방법 |
|----------|------|-----------|
| `confluence_crawler.py` | Confluence 페이지 크롤링 | `python confluence_crawler.py [--full]` |
| `sync_state.py` | 동기화 상태 관리 유틸리티 | (다른 스크립트에서 import) |
| `preprocess_data.py` | 데이터 전처리 (청크 분할) | `python preprocess_data.py [--chunk-size 1000]` |
| `build_vectordb.py` | 벡터 DB 구축 | `python build_vectordb.py [--rebuild]` |
| `update_vectordb.py` | 벡터 DB 증분 업데이트 | `python update_vectordb.py [--force]` |
| `rag_search.py` | RAG 검색 엔진 | `python rag_search.py` (테스트 모드) |
| `app.py` | Gradio 웹 UI | `python app.py` |
| `weekly_update.py` | 통합 업데이트 파이프라인 | `python weekly_update.py [--full]` |
| `show_stats.py` | 시스템 통계 대시보드 | `python show_stats.py [--json]` |
| `docker_manager.sh` | Docker 관리 | `./docker_manager.sh [command]` |
| `backup.sh` | 데이터 백업 | `./backup.sh` |
| `restore.sh` | 데이터 복구 | `./restore.sh <백업파일>` |

---

## 🔧 문제 해결

### Ollama 연결 실패

```
❌ Ollama 연결 실패
```

**해결 방법:**
```bash
# Ollama 서비스 시작
ollama serve

# 모델 확인
ollama list

# 모델이 없으면 다운로드
ollama pull eeve-korean-10.8b
```

### Playwright 브라우저 오류

```
BrowserType.launch: Executable doesn't exist
```

**해결 방법:**
```bash
playwright install chromium
```

### 벡터 DB 없음

```
❌ 벡터 DB가 존재하지 않습니다
```

**해결 방법:**
```bash
# 전체 파이프라인 실행
python weekly_update.py --full

# 또는 단계별 실행
python confluence_crawler.py --full
python preprocess_data.py
python build_vectordb.py
```

### CUDA 메모리 부족

```
torch.cuda.OutOfMemoryError
```

**해결 방법:**
- 자동으로 CPU로 전환됩니다
- `--batch-size` 줄이기: `python build_vectordb.py --batch-size 50`

### Confluence 로그인 실패

```
❌ 로그인 시간 초과
```

**해결 방법:**
1. `.env`의 `CONFLUENCE_USERNAME`, `CONFLUENCE_PASSWORD` 확인
2. API 토큰이 만료되지 않았는지 확인
3. Confluence URL이 정확한지 확인

---

## 👨‍💻 개발 가이드

### 프로젝트 구조

```
confluence/
├── confluence_crawler.py     # 크롤러 (데이터 수집)
├── sync_state.py             # 동기화 상태 관리
├── preprocess_data.py        # 전처리 (청크 분할)
├── build_vectordb.py         # 벡터 DB 구축
├── update_vectordb.py        # 벡터 DB 증분 업데이트
├── rag_search.py             # RAG 검색 엔진
├── app.py                    # Gradio 웹 UI
├── weekly_update.py          # 통합 파이프라인
├── show_stats.py             # 통계 대시보드
├── docker_manager.sh         # Docker 관리
├── backup.sh                 # 백업
├── restore.sh                # 복구
├── requirements.txt          # 프로덕션 의존성
├── requirements-dev.txt      # 개발 의존성
├── .env.template             # 환경변수 템플릿
├── .gitignore                # Git 제외 파일
├── .dockerignore             # Docker 제외 파일
├── Dockerfile                # Docker 이미지
├── docker-compose.yml        # Docker Compose
├── README.md                 # 프로젝트 문서
├── TECHNICAL.md              # 기술 문서
└── OPERATIONS.md             # 운영 가이드
```

### 개발 환경 설정

```bash
# 개발 의존성 설치
pip install -r requirements-dev.txt

# 코드 포맷팅
black .

# 린트 검사
flake8

# 테스트 실행
pytest
```

### 기여 방법

1. 이슈를 확인하거나 새 이슈를 생성합니다
2. 기능 브랜치를 생성합니다: `git checkout -b feature/my-feature`
3. 변경사항을 커밋합니다: `git commit -m "Add my feature"`
4. 브랜치를 푸시합니다: `git push origin feature/my-feature`
5. Pull Request를 생성합니다

---

## 📄 라이센스

이 프로젝트는 내부 사용 목적으로 개발되었습니다.

---

## 🚀 향후 개선사항

- [ ] **API 기반 크롤링**: Playwright 대신 Confluence REST API 활용
- [ ] **다중 스페이스 지원**: 여러 Confluence 스페이스 동시 크롤링
- [ ] **검색 로그 분석**: 인기 검색어, 검색 품질 모니터링
- [ ] **답변 피드백**: 사용자 피드백으로 검색 품질 개선
- [ ] **Slack 통합**: Slack 봇으로 검색 기능 제공
- [ ] **다국어 지원**: 영문 문서 검색 최적화
- [ ] **이미지 처리**: 다이어그램, 스크린샷 내용 인식
- [ ] **자동 스케줄링**: cron 기반 주기적 업데이트
- [ ] **클러스터링**: 대규모 문서에 대한 분산 처리
- [ ] **캐싱 레이어**: 자주 묻는 질문 캐싱으로 응답 속도 개선
