# 기술 문서

## 1. 시스템 아키텍처

### 3계층 구조

```
┌─────────────────────────────────────────────────────┐
│                 프레젠테이션 계층                      │
│                                                     │
│   app.py (Gradio)  │  show_stats.py  │  check_setup │
└─────────────┬───────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────┐
│                   비즈니스 계층                       │
│                                                     │
│   rag_search.py    │  weekly_update.py              │
│   (질의 → 검색 → 응답)  (크롤링 → 전처리 → 벡터화)    │
└─────────────┬───────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────┐
│                    데이터 계층                        │
│                                                     │
│   confluence_crawler.py  │  preprocess_data.py      │
│   sync_state.py          │  build_vectordb.py       │
│   ChromaDB               │  update_vectordb.py      │
└─────────────────────────────────────────────────────┘
```

### 데이터 흐름

```
Confluence 위키
    │
    ▼ (Playwright 브라우저 로그인 + 재귀 크롤링)
confluence_crawler.py
    │
    ├── confluence_backup.json   (전체 페이지 원본 데이터)
    ├── confluence_pages/*.md    (개별 페이지 Markdown)
    └── last_sync.json           (동기화 상태 추적)
    │
    ▼ (텍스트 청킹 + 메타데이터 부착)
preprocess_data.py
    │
    └── processed_chunks.json    (청크 + 메타데이터)
    │
    ▼ (한국어 임베딩 + ChromaDB 저장)
build_vectordb.py / update_vectordb.py
    │
    └── confluence_vectordb/     (ChromaDB 영구 저장소)
    │
    ▼ (벡터 유사도 검색 + LLM 컨텍스트 생성)
rag_search.py
    │
    ▼ (사용자 질문 → AI 답변 + 출처)
app.py (Gradio 웹 UI)
```

## 2. 증분 업데이트 메커니즘

### 변경 감지 로직

`sync_state.py`가 관리하는 `last_sync.json`에 각 페이지의 상태를 기록합니다.

```json
{
  "total_pages": 42,
  "last_full_sync": "2025-02-09T10:00:00",
  "last_incremental_sync": "2025-02-15T08:30:00",
  "pages": {
    "123456": {
      "title": "배포 가이드",
      "version": 5,
      "last_modified": "2025-02-08T14:30:00",
      "url": "https://..."
    }
  },
  "sync_history": [...]
}
```

### 변경 판단 기준

`confluence_crawler.py`의 `is_page_modified()` 메서드:

```python
def is_page_modified(self, page_id, current_version, current_modified):
    # 1. 전체 크롤링 모드 → 항상 True
    if self.full_crawl:
        return True

    # 2. 새 페이지 (ID가 없음) → True
    if page_id not in self.sync_state["pages"]:
        return True

    # 3. 버전 또는 수정일 비교
    stored = self.sync_state["pages"][page_id]
    return (stored["version"] != current_version or
            stored["last_modified"] != current_modified)
```

### 벡터 DB 증분 업데이트 전략

`update_vectordb.py`의 삭제-재삽입 방식:

1. `identify_changes()` - 변경된 페이지 ID 목록 생성
2. `delete_old_vectors()` - 해당 page_id를 가진 기존 벡터 전부 삭제
3. `add_new_vectors()` - 새로운 청크로 벡터 재생성 후 삽입

이 방식은 부분 업데이트보다 구현이 단순하고 데이터 정합성을 보장합니다.

## 3. RAG 파이프라인

### 임베딩 모델

| 항목 | 값 |
|------|-----|
| 모델 | `jhgan/ko-sroberta-multitask` |
| 차원 | 768 |
| 특화 | 한국어 문장 임베딩 |
| 라이브러리 | `sentence-transformers` |
| 디바이스 | CUDA (자동 감지) → CPU 폴백 |

한국어 문서를 다루므로 다국어 범용 모델 대신 한국어 특화 모델을 선택했습니다.
`ko-sroberta-multitask`는 STS(문장 유사도) 벤치마크에서 한국어 최상위 성능을 보입니다.

### 텍스트 청킹

```python
RecursiveCharacterTextSplitter(
    chunk_size=1000,      # 청크당 최대 1000자
    chunk_overlap=200,    # 앞뒤 200자 겹침
    separators=[
        "\n## ",          # H2 헤더
        "\n### ",         # H3 헤더
        "\n\n",           # 빈 줄 (단락 구분)
        "\n",             # 줄바꿈
        "다. ",           # 한국어 문장 끝
        "요. ",           # 한국어 문장 끝
        "죠. ",           # 한국어 문장 끝
        ". ",             # 영문 문장 끝
        " ",              # 공백
    ]
)
```

**설계 근거:**
- `chunk_size=1000`: 한국어 평균 문단 길이(200~500자)를 고려하여 2~3개 문단 단위
- `chunk_overlap=200`: 문맥 연결이 끊기지 않도록 20% 겹침
- 한국어 문장 종결 어미("다. ", "요. ")를 분리자로 추가하여 문장 중간 분할 방지

### LLM 프롬프트 설계

```python
prompt = f"""당신은 회사 내부 문서 기반 질의응답 어시스턴트입니다.

아래 참고 문서를 바탕으로 질문에 답변하세요.

규칙:
1. 참고 문서에 있는 정보만 사용하세요.
2. 답을 모르면 "해당 정보를 찾을 수 없습니다"라고 답하세요.
3. 출처(페이지 제목)를 반드시 명시하세요.
4. 한국어로 답변하세요.

참고 문서:
{context}

질문: {query}

답변:"""
```

**핵심 원칙:**
- 할루시네이션 방지: 문서에 없는 정보 생성을 명시적으로 금지
- 출처 추적: 답변의 근거를 확인할 수 있도록 페이지 제목 명시
- 언어 일관성: 한국어 질문에 한국어로 답변

### 검색 파이프라인

```
사용자 질문
    │
    ▼ (임베딩)
ko-sroberta-multitask로 질문 벡터화 (768차원)
    │
    ▼ (유사도 검색)
ChromaDB에서 상위 k개 (기본 5) 유사 청크 검색
    │
    ▼ (컨텍스트 구성)
검색된 청크들을 하나의 컨텍스트 문자열로 결합
각 청크에 출처(페이지 제목, URL) 표시
    │
    ▼ (LLM 호출)
Ollama API로 프롬프트 + 컨텍스트 전송
    │
    ▼ (응답 구성)
AI 답변 + 참고 문서 목록 (제목, URL) 반환
```

## 4. 성능 최적화

### 배치 임베딩 처리

`build_vectordb.py`는 대량 청크를 배치 단위로 처리합니다.

```python
# 기본 배치 크기: 100
for i in range(0, total, batch_size):
    batch = chunks[i:i+batch_size]
    embeddings = model.encode([c["content"] for c in batch])
    collection.add(
        ids=[...],
        embeddings=embeddings.tolist(),
        documents=[...],
        metadatas=[...]
    )
```

### 빌드 진행 상태 저장 (크래시 복구)

`.vectordb_progress.json`에 처리 진행 상태를 저장합니다.
중단 후 재실행 시 마지막 배치부터 이어서 처리합니다.

```json
{
  "last_batch_index": 150,
  "total_chunks": 500,
  "timestamp": "2025-02-09T10:30:00"
}
```

### CUDA OOM 자동 폴백

```python
try:
    model = SentenceTransformer(model_name, device="cuda")
except RuntimeError:  # CUDA out of memory
    model = SentenceTransformer(model_name, device="cpu")
```

GPU 메모리 부족 시 자동으로 CPU로 전환하여 처리를 계속합니다.

## 5. 크롤러 상세

### 로그인 처리

Playwright의 Headless Chromium으로 Confluence에 로그인합니다.

```python
# 1. 로그인 페이지 접속
page.goto(f"{base_url}/login.action")

# 2. 자격 증명 입력
page.fill("#os_username", username)
page.fill("#os_password", password)
page.click("#loginButton")

# 3. 로그인 완료 대기
page.wait_for_load_state("networkidle")
```

### 재귀 크롤링

```python
def crawl_page(self, url, depth=0):
    # 1. 페이지 접속 + 메타데이터 추출
    page_id = self._extract_page_id(url)
    metadata = self._extract_metadata(page)

    # 2. 변경 여부 확인 (증분 모드)
    if not self.is_page_modified(page_id, version, modified):
        return  # 건너뜀

    # 3. 콘텐츠 추출 + 저장
    content = self._extract_content(page)
    self._save_page(page_id, title, content, metadata)

    # 4. 하위 페이지 재귀 탐색
    children = self._extract_children(page)
    for child_url in children:
        self.crawl_page(child_url, depth + 1)
```

### 안정성

- **최대 3회 재시도**: 네트워크 오류, 타임아웃 발생 시
- **404 감지**: 삭제된 페이지 자동 건너뛰기
- **타임아웃**: 페이지 로드 30초 제한
- **진행 상태 저장**: 크롤링 중 동기화 상태 실시간 업데이트

## 6. 모니터링 도구

### check_setup.py (환경 점검)

9개 항목을 검사하고 결과를 ✅/❌/⚠️ 로 표시합니다.

| # | 검사 항목 | 설명 |
|---|----------|------|
| 1 | Python 버전 | 3.8 이상 확인 |
| 2 | 가상환경 | venv 존재 및 활성화 여부 |
| 3 | 필수 패키지 | 11개 패키지 설치 확인 |
| 4 | .env 파일 | 4개 필수 변수 설정 확인 |
| 5 | Playwright | Chromium 브라우저 설치 확인 |
| 6 | Ollama | 서버 실행 + 모델 설치 확인 |
| 7 | 디렉토리 | 4개 필수 디렉토리 존재 확인 |
| 8 | 동기화 상태 | last_sync.json 유효성 확인 |
| 9 | 네트워크 포트 | Gradio 포트(7860) 사용 가능 확인 |

실행: `python check_setup.py` 또는 `./manager.sh check` (간이 점검)

### show_stats.py (통계 대시보드)

4개 섹션의 Rich 테이블 대시보드를 출력합니다.

| 섹션 | 표시 내용 |
|------|----------|
| 시스템 정보 | Python 버전, 디스크 사용량, 패키지 버전 |
| 크롤링 통계 | 총 페이지 수, 마지막 동기화, 동기화 이력 |
| 벡터 DB 통계 | 벡터 수, 청크 수, DB 크기, 평균 청크 크기 |
| 서비스 상태 | Ollama 실행/모델 설치, Gradio 실행 상태 |

```bash
python show_stats.py              # 대시보드 출력
python show_stats.py --json       # JSON 형식 출력
python show_stats.py --export stats.json  # 파일 저장
```

## 7. 테스트 구조

### 테스트 레이어

```
conftest.py (루트)          ← 공용 fixture (sample_pages, env_vars, mock_ollama)
├── test_integration.py    ← 통합 테스트 (7개 클래스)
└── tests/
    ├── conftest.py        ← 테스트 fixture (tmp_sync_state)
    ├── test_crawler.py    ← 크롤러 단위 테스트
    ├── test_preprocessing.py  ← 전처리 단위 테스트
    ├── test_vectordb.py   ← 벡터DB 단위 테스트
    └── test_rag.py        ← RAG 단위 테스트
```

### 실행 방법

```bash
# 빠른 테스트 (slow 마커 제외)
./manager.sh test

# 전체 테스트 (임베딩 모델 필요)
python -m pytest tests/ test_integration.py -v

# 특정 파일만
python -m pytest tests/test_crawler.py -v
```

### 커스텀 마커

| 마커 | 설명 |
|------|------|
| `@pytest.mark.slow` | 임베딩 모델 다운로드 필요, CI에서 건너뛸 수 있음 |
| `@pytest.mark.integration` | 외부 서비스 연동 테스트 |

## 8. 보안 고려사항

- `.env` 파일은 `.gitignore`에 포함되어 버전 관리에서 제외
- Confluence 비밀번호/API 토큰은 환경변수로만 관리
- 크롤링된 데이터(`confluence_pages/`, `confluence_vectordb/`)도 `.gitignore`에 포함
- Playwright는 Headless 모드로 실행 (UI 노출 없음)
- Gradio UI는 기본적으로 localhost에서만 접근 가능
