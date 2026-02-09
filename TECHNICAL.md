# 🛠️ 기술 문서

Confluence AI 검색 시스템의 아키텍처, 설계 결정, 성능 최적화 전략을 설명합니다.

---

## 1. 시스템 아키텍처

### 컴포넌트 다이어그램

```
┌──────────────────────────────────────────────────────────────────┐
│                        데이터 수집 레이어                          │
│                                                                  │
│  ┌──────────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │ ConfluenceCrawler │───▶│  sync_state  │───▶│ last_sync.json│  │
│  │  (Playwright)     │    │  (상태 관리)  │    │  (변경 추적)   │  │
│  └────────┬─────────┘    └──────────────┘    └───────────────┘  │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────┐                                           │
│  │confluence_backup  │                                           │
│  │    .json          │                                           │
│  └────────┬─────────┘                                           │
└───────────┼─────────────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────────────────────────────────┐
│                        데이터 처리 레이어                           │
│                                                                   │
│  ┌──────────────────┐    ┌──────────────────┐                    │
│  │  preprocess_data  │───▶│ processed_chunks │                    │
│  │  (청크 분할)       │    │     .json        │                    │
│  └──────────────────┘    └────────┬─────────┘                    │
│                                   │                               │
│           ┌───────────────────────┘                               │
│           ▼                                                       │
│  ┌──────────────────┐    ┌──────────────────┐                    │
│  │  build_vectordb   │───▶│  ChromaDB        │                    │
│  │  (임베딩 + 저장)   │    │  (벡터 저장소)    │                    │
│  └──────────────────┘    └────────┬─────────┘                    │
└────────────────────────────────────┼────────────────────────────┘
                                     │
                                     ▼
┌───────────────────────────────────────────────────────────────────┐
│                        서비스 레이어                                │
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────┐   │
│  │ Gradio 웹 UI │───▶│ ConfluenceRAG│───▶│   Ollama LLM      │   │
│  │  (app.py)    │    │ (rag_search) │    │ (eeve-korean-10.8b│   │
│  └──────────────┘    └──────────────┘    └───────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

### 데이터 흐름

```
[Confluence 웹] ──(Playwright 크롤링)──▶ [HTML]
                                           │
                              (BeautifulSoup + markdownify)
                                           │
                                           ▼
                                      [Markdown]
                                           │
                            (RecursiveCharacterTextSplitter)
                                           │
                                           ▼
                                   [텍스트 청크 배열]
                                           │
                              (ko-sroberta-multitask 임베딩)
                                           │
                                           ▼
                                     [벡터 배열]
                                           │
                                    (ChromaDB 저장)
                                           │
                                           ▼
                                   [벡터 데이터베이스]
                                           │
                           (사용자 질문 → 유사도 검색)
                                           │
                                           ▼
                                  [관련 문서 Top-K]
                                           │
                              (Ollama LLM 컨텍스트 주입)
                                           │
                                           ▼
                                     [자연어 답변]
```

---

## 2. 증분 업데이트 로직

### 변경 감지 방법

시스템은 `last_sync.json`에 각 페이지의 스냅샷을 유지합니다:

```json
{
  "pages": {
    "123456": {
      "title": "개발 가이드",
      "version": 15,
      "last_modified": "2025-02-09T10:00:00",
      "last_crawled": "2025-02-09T11:00:00"
    }
  }
}
```

**변경 판별 우선순위:**

1. **신규 페이지**: `page_id`가 `last_sync.json`에 없으면 → 신규
2. **버전 비교**: `version` 값이 다르면 → 수정됨
3. **수정일 비교**: `last_modified` 값이 다르면 → 수정됨
4. **판단 불가**: 위 정보가 없으면 → 수정된 것으로 간주 (안전 우선)

```python
# confluence_crawler.py의 핵심 로직
def is_page_modified(self, page_id, version, last_modified):
    if self.full_crawl:
        return True  # 전체 모드: 항상 수집

    prev = self.sync_state["pages"].get(page_id)
    if prev is None:
        return True  # 신규 페이지

    if version > 0 and prev.get("version", 0) > 0:
        return version != prev["version"]

    if last_modified and prev.get("last_modified"):
        return last_modified != prev["last_modified"]

    return True  # 안전 우선
```

### 벡터 업데이트 전략

증분 업데이트는 **삭제 후 재삽입** 전략을 사용합니다:

```
1. 변경된 페이지 식별
2. 해당 페이지의 기존 벡터 전부 삭제 (page_id 기준)
3. 변경된 페이지를 새로 청크 분할
4. 새 청크를 벡터로 변환하여 삽입
```

이 전략의 장점:
- 청크 경계가 변경되어도 안전하게 처리
- 페이지 내 부분 수정도 정확하게 반영
- 고아 벡터(orphan vector) 발생 방지

---

## 3. RAG 파이프라인

### 임베딩 모델 선택: `jhgan/ko-sroberta-multitask`

| 후보 모델 | 한국어 성능 | 모델 크기 | 선택 이유 |
|-----------|------------|----------|-----------|
| `jhgan/ko-sroberta-multitask` | ⭐⭐⭐⭐⭐ | 350MB | **한국어 STS 벤치마크 1위급** |
| `sentence-transformers/all-MiniLM-L6-v2` | ⭐⭐ | 80MB | 영문 특화, 한국어 성능 부족 |
| `intfloat/multilingual-e5-large` | ⭐⭐⭐⭐ | 2.2GB | 성능 우수하나 크기가 큼 |

**선택 근거:**
- 한국어 문장 유사도 태스크에 최적화
- KorSTS, KorNLI 벤치마크에서 높은 성능
- 350MB로 적절한 크기 (CPU에서도 실용적)
- normalize_embeddings으로 코사인 유사도 최적화

### 청크 크기 최적화

```python
# 한국어에 최적화된 분할 설정
KOREAN_SEPARATORS = [
    "\n\n",    # 단락 (최우선)
    "\n",      # 줄바꿈
    "다. ",    # 한국어 종결어미
    "요. ",    # 한국어 종결어미
    ". ",      # 영문 마침표
    ", ",      # 쉼표
    " ",       # 공백
    "",        # 문자 단위 (최후 수단)
]

chunk_size = 1000      # 한글 1000자 ≈ 영문 2000자
chunk_overlap = 200    # 20% 오버랩으로 문맥 연속성 보장
```

**chunk_size=1000의 근거:**
- 한글 1자 = 영문 약 2자의 정보량
- 임베딩 모델의 최대 토큰(512)에 적합한 길이
- 너무 작으면 문맥 손실, 너무 크면 검색 정밀도 저하
- 1000자는 Confluence 문서의 1개 섹션에 해당

**chunk_overlap=200의 근거:**
- 청크 경계에서의 문맥 단절 방지
- 20% 오버랩은 정보 손실과 저장 효율의 최적 지점

### 프롬프트 엔지니어링

```python
RAG_PROMPT_TEMPLATE = """다음은 Confluence 문서에서 검색된 관련 내용입니다:

{context}

위 내용을 바탕으로 다음 질문에 답변해주세요:
{question}

답변 형식:
1. 핵심 요약 (2-3문장)
2. 상세 설명
3. 필요시 예시 또는 단계별 설명

답변은 명확하고 구체적으로, 한국어로 작성해주세요.
문서에서 관련 내용을 찾을 수 없는 경우,
솔직하게 "해당 내용을 문서에서 찾을 수 없습니다"라고 답변해주세요."""
```

**프롬프트 설계 원칙:**
1. **구조화된 답변**: 핵심 → 상세 → 예시 순서로 가독성 확보
2. **환각 방지**: "찾을 수 없습니다" 응답을 명시적으로 유도
3. **한국어 지정**: 답변 언어를 명확히 지시
4. **컨텍스트 우선**: 문서 내용을 질문보다 앞에 배치

---

## 4. 성능 최적화

### 배치 처리

임베딩과 DB 저장을 배치 단위로 처리하여 효율성을 높입니다:

```python
# build_vectordb.py
BATCH_SIZE = 100  # 기본 배치 크기

for batch_idx in range(total_batches):
    batch = chunks[start:end]

    # 배치 단위 임베딩 (GPU 활용 극대화)
    vectors = embeddings.embed_documents(texts)

    # ChromaDB upsert (배치 삽입)
    collection.upsert(
        ids=ids,
        embeddings=vectors,
        documents=texts,
        metadatas=metadatas,
    )

    # 진행 상황 저장 (중단 시 재개)
    _save_progress(batch_idx)
```

**배치 크기 가이드:**
- GPU (8GB VRAM): `batch_size=100` (기본값)
- GPU (4GB VRAM): `batch_size=50`
- CPU Only: `batch_size=30`

### 중단 재개 메커니즘

```python
# .vectordb_progress.json으로 진행 상황 추적
{"last_completed_batch": 42}

# 재실행 시 자동으로 42번째 배치부터 재개
start_batch = _load_progress()
```

### 메모리 관리

```python
# CUDA OOM 자동 감지 및 CPU 전환
try:
    embeddings = HuggingFaceEmbeddings(
        model_kwargs={"device": "cuda"}
    )
except torch.cuda.OutOfMemoryError:
    torch.cuda.empty_cache()
    embeddings = HuggingFaceEmbeddings(
        model_kwargs={"device": "cpu"}
    )
```

---

## 5. 확장 가능성

### 다른 문서 소스 추가

크롤러 인터페이스를 확장하여 다양한 소스를 지원할 수 있습니다:

```python
# 예시: Notion 크롤러 추가
class NotionCrawler:
    def __init__(self):
        self.api_key = os.getenv("NOTION_API_KEY")

    def crawl_page(self, page_id):
        # Notion API로 페이지 수집
        ...

    def run(self):
        # 동일한 출력 형식 (confluence_backup.json과 호환)
        ...
```

전처리(`preprocess_data.py`)와 벡터화(`build_vectordb.py`)는 입력 JSON 형식만 맞으면
어떤 소스의 데이터든 처리할 수 있습니다.

### 다른 LLM 사용

`rag_search.py`의 LLM 초기화 부분만 수정하면 됩니다:

```python
# Ollama 모델 변경
OLLAMA_MODEL=llama3        # .env에서 변경

# OpenAI API 사용 (코드 수정 필요)
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY"))
```

---

## 6. 보안 고려사항

### 인증 정보 관리

| 항목 | 저장 위치 | 보호 방법 |
|------|----------|-----------|
| Confluence 계정 | `.env` | `.gitignore`에 등록, Git 추적 제외 |
| API 토큰 | `.env` | 환경변수로만 주입, 코드에 하드코딩 금지 |
| Docker 시크릿 | `docker-compose.yml` | `env_file`로 분리, 이미지에 포함하지 않음 |

**주의사항:**
- `.env` 파일은 절대 Git에 커밋하지 않기 (`.gitignore`에 포함됨)
- `.env.template`에는 실제 값을 입력하지 않기
- API 토큰은 주기적으로 갱신하기
- Docker 이미지에 인증 정보가 포함되지 않았는지 확인

### 데이터 보안

- 크롤링된 데이터는 로컬에만 저장 (외부 전송 없음)
- Ollama LLM은 로컬 실행 (데이터가 외부 API로 전송되지 않음)
- 벡터 DB는 암호화되지 않으므로 디스크 수준 암호화 권장
- Docker 컨테이너는 비root 사용자로 실행
