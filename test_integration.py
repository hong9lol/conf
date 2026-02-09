"""
통합 테스트

전체 파이프라인의 주요 기능을 검증합니다.
외부 의존성(Confluence, Ollama)은 mock으로 대체합니다.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ============================================
# 마커 정의
# ============================================
pytestmark = [pytest.mark.integration]


# ============================================
# 픽스처
# ============================================

@pytest.fixture
def sample_pages():
    """테스트용 페이지 데이터"""
    return [
        {
            "title": "개발 환경 설정 가이드",
            "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/100001/Setup",
            "page_id": "100001",
            "version": 5,
            "last_modified": "2025-02-01T10:00:00",
            "content": (
                "# 개발 환경 설정\n\n"
                "## Python 설치\n\n"
                "Python 3.11 이상을 설치합니다. "
                "pyenv를 사용하면 여러 버전을 관리할 수 있습니다.\n\n"
                "## 가상환경 생성\n\n"
                "```bash\npython -m venv venv\nsource venv/bin/activate\n```\n\n"
                "가상환경을 활성화한 후 의존성을 설치합니다."
            ),
            "depth": 0,
            "crawled_at": "2025-02-09T11:00:00",
        },
        {
            "title": "배포 프로세스",
            "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/100002/Deploy",
            "page_id": "100002",
            "version": 3,
            "last_modified": "2025-02-05T14:00:00",
            "content": (
                "# 배포 프로세스\n\n"
                "## 스테이징 배포\n\n"
                "PR이 머지되면 자동으로 스테이징 환경에 배포됩니다.\n\n"
                "## 프로덕션 배포\n\n"
                "프로덕션 배포는 릴리즈 태그를 생성하면 자동으로 실행됩니다. "
                "배포 전 QA 팀의 승인이 필요합니다."
            ),
            "depth": 0,
            "crawled_at": "2025-02-09T11:01:00",
        },
    ]


@pytest.fixture
def sample_backup_json(tmp_path, sample_pages):
    """테스트용 backup JSON 파일 생성"""
    backup_data = {
        "crawl_timestamp": "2025-02-09T11:00:00",
        "crawl_type": "full",
        "total_pages": len(sample_pages),
        "pages": sample_pages,
    }
    path = tmp_path / "confluence_backup.json"
    path.write_text(json.dumps(backup_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_sync_state(tmp_path):
    """테스트용 sync state 파일 생성"""
    state = {
        "last_full_sync": "2025-02-01T10:00:00",
        "last_incremental_sync": "2025-02-08T10:00:00",
        "total_pages": 2,
        "pages": {
            "100001": {
                "title": "개발 환경 설정 가이드",
                "url": "https://example.atlassian.net/wiki/spaces/DEV/pages/100001/Setup",
                "version": 4,
                "last_modified": "2025-01-20T10:00:00",
                "last_crawled": "2025-02-01T10:00:00",
            }
        },
        "sync_history": [
            {
                "timestamp": "2025-02-01T10:00:00",
                "type": "full",
                "added": 10,
                "modified": 0,
                "deleted": 0,
            }
        ],
    }
    path = tmp_path / "last_sync.json"
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@pytest.fixture
def mock_ollama():
    """Ollama API mock"""
    with patch("rag_search.Ollama") as mock:
        instance = MagicMock()
        instance.invoke.return_value = (
            "## 핵심 요약\n\n"
            "개발 환경은 Python 3.11 이상이 필요합니다.\n\n"
            "## 상세 설명\n\n"
            "pyenv로 Python을 설치하고 가상환경을 생성합니다."
        )
        mock.return_value = instance
        yield instance


# ============================================
# 1. 환경 테스트
# ============================================

class TestEnvironment:
    """환경 설정 검증"""

    def test_env_template_exists(self):
        """.env.template 파일이 존재해야 합니다"""
        assert Path(".env.template").exists(), \
            ".env.template 파일이 없습니다. 프로젝트 루트를 확인하세요."

    def test_env_template_has_required_vars(self):
        """.env.template에 필수 변수가 포함되어야 합니다"""
        content = Path(".env.template").read_text(encoding="utf-8")
        required_vars = [
            "CONFLUENCE_BASE_URL",
            "CONFLUENCE_USERNAME",
            "CONFLUENCE_PASSWORD",
            "ROOT_PAGE_URL",
            "OLLAMA_HOST",
            "OLLAMA_MODEL",
        ]
        for var in required_vars:
            assert var in content, f".env.template에 {var}가 없습니다."

    def test_required_files_exist(self):
        """필수 스크립트 파일이 존재해야 합니다"""
        required_files = [
            "confluence_crawler.py",
            "sync_state.py",
            "preprocess_data.py",
            "build_vectordb.py",
            "update_vectordb.py",
            "rag_search.py",
            "app.py",
            "weekly_update.py",
        ]
        for filename in required_files:
            assert Path(filename).exists(), f"필수 파일 누락: {filename}"

    def test_gitignore_has_sensitive_entries(self):
        """.gitignore에 민감한 파일이 포함되어야 합니다"""
        content = Path(".gitignore").read_text(encoding="utf-8")
        assert ".env" in content, ".gitignore에 .env가 없습니다."
        assert "venv/" in content, ".gitignore에 venv/가 없습니다."


# ============================================
# 2. 동기화 상태 테스트
# ============================================

class TestSyncState:
    """동기화 상태 관리 검증"""

    def test_init_sync_state_creates_file(self, tmp_path, monkeypatch):
        """init_sync_state()가 파일을 생성해야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_path / "last_sync.json")
        from sync_state import init_sync_state

        state = init_sync_state()

        assert (tmp_path / "last_sync.json").exists(), "last_sync.json이 생성되지 않았습니다."
        assert state["total_pages"] == 0, "초기 페이지 수는 0이어야 합니다."
        assert state["sync_history"] == [], "초기 이력은 비어있어야 합니다."

    def test_load_sync_state_valid_json(self, sample_sync_state, monkeypatch):
        """유효한 JSON을 정상적으로 로드해야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", Path(sample_sync_state))
        from sync_state import load_sync_state

        state = load_sync_state()

        assert state["total_pages"] == 2, "페이지 수가 일치하지 않습니다."
        assert "100001" in state["pages"], "페이지 100001이 없습니다."

    def test_sync_history_max_limit(self, tmp_path, monkeypatch):
        """sync_history가 최대 20개로 제한되어야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_path / "last_sync.json")
        from sync_state import init_sync_state, update_sync_state, load_sync_state

        init_sync_state()

        # 25개 이력 추가
        for i in range(25):
            update_sync_state(
                pages={},
                sync_record={"timestamp": f"2025-01-{i+1:02d}T00:00:00", "type": "incremental"},
                is_full_sync=False,
                total_pages=0,
            )

        state = load_sync_state()
        assert len(state["sync_history"]) <= 20, \
            f"sync_history가 20개를 초과했습니다: {len(state['sync_history'])}개"

    def test_get_last_sync_time(self, sample_sync_state, monkeypatch):
        """마지막 동기화 시간을 정확히 반환해야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", Path(sample_sync_state))
        from sync_state import get_last_sync_time

        full_time = get_last_sync_time("full")
        assert full_time == "2025-02-01T10:00:00", "전체 동기화 시간이 일치하지 않습니다."

        any_time = get_last_sync_time("any")
        assert any_time == "2025-02-08T10:00:00", "최근 동기화 시간이 일치하지 않습니다."


# ============================================
# 3. 크롤러 테스트
# ============================================

class TestCrawler:
    """크롤러 기능 검증"""

    @patch.dict(os.environ, {
        "CONFLUENCE_BASE_URL": "https://test.atlassian.net/wiki",
        "CONFLUENCE_USERNAME": "test@example.com",
        "CONFLUENCE_PASSWORD": "test-token",
        "ROOT_PAGE_URL": "https://test.atlassian.net/wiki/spaces/TEST/pages/1/Root",
    })
    def test_crawler_init(self, tmp_path, monkeypatch):
        """크롤러가 정상적으로 초기화되어야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_path / "last_sync.json")
        from confluence_crawler import ConfluenceCrawler

        crawler = ConfluenceCrawler(full_crawl=True)

        assert crawler.base_url == "https://test.atlassian.net/wiki", "base_url이 올바르지 않습니다."
        assert crawler.full_crawl is True, "full_crawl 모드가 설정되지 않았습니다."
        assert crawler.stats["added"] == 0, "초기 통계가 0이어야 합니다."

    @patch.dict(os.environ, {
        "CONFLUENCE_BASE_URL": "",
        "CONFLUENCE_USERNAME": "",
        "CONFLUENCE_PASSWORD": "",
        "ROOT_PAGE_URL": "",
    })
    def test_crawler_missing_config_raises(self, tmp_path, monkeypatch):
        """필수 환경변수가 없으면 ValueError가 발생해야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_path / "last_sync.json")
        from confluence_crawler import ConfluenceCrawler

        with pytest.raises(ValueError, match="필수 환경변수 누락"):
            ConfluenceCrawler()

    def test_is_page_modified_new_page(self, tmp_path, monkeypatch):
        """신규 페이지는 수정된 것으로 판별해야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_path / "last_sync.json")
        env = {
            "CONFLUENCE_BASE_URL": "https://test.atlassian.net/wiki",
            "CONFLUENCE_USERNAME": "test@example.com",
            "CONFLUENCE_PASSWORD": "test-token",
            "ROOT_PAGE_URL": "https://test.atlassian.net/wiki/spaces/T/pages/1/R",
        }
        with patch.dict(os.environ, env):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler(full_crawl=False)

            result = crawler.is_page_modified("new_page_999", 1, "2025-02-09")
            assert result is True, "신규 페이지는 modified=True여야 합니다."


# ============================================
# 4. 전처리 테스트
# ============================================

class TestPreprocessing:
    """데이터 전처리 검증"""

    def test_split_into_chunks(self, sample_pages):
        """청크 분할이 정상적으로 수행되어야 합니다"""
        from preprocess_data import split_into_chunks

        chunks = split_into_chunks(sample_pages, chunk_size=200, chunk_overlap=50)

        assert len(chunks) > 0, "청크가 생성되지 않았습니다."
        assert len(chunks) >= len(sample_pages), "페이지 수 이상의 청크가 생성되어야 합니다."

    def test_chunk_has_metadata(self, sample_pages):
        """각 청크에 메타데이터가 포함되어야 합니다"""
        from preprocess_data import split_into_chunks

        chunks = split_into_chunks(sample_pages, chunk_size=200, chunk_overlap=50)

        for chunk in chunks:
            assert "content" in chunk, "청크에 content가 없습니다."
            assert "metadata" in chunk, "청크에 metadata가 없습니다."

            meta = chunk["metadata"]
            assert "page_id" in meta, "메타데이터에 page_id가 없습니다."
            assert "title" in meta, "메타데이터에 title이 없습니다."
            assert "url" in meta, "메타데이터에 url이 없습니다."
            assert "chunk_index" in meta, "메타데이터에 chunk_index가 없습니다."
            assert "total_chunks" in meta, "메타데이터에 total_chunks가 없습니다."

    def test_chunk_size_respected(self, sample_pages):
        """청크 크기 제한이 준수되어야 합니다"""
        from preprocess_data import split_into_chunks

        chunk_size = 300
        chunks = split_into_chunks(sample_pages, chunk_size=chunk_size, chunk_overlap=50)

        for chunk in chunks:
            assert len(chunk["content"]) <= chunk_size * 1.1, \
                f"청크가 최대 크기를 초과했습니다: {len(chunk['content'])}자 (제한: {chunk_size})"

    def test_metadata_add(self):
        """add_metadata가 올바른 형식을 반환해야 합니다"""
        from preprocess_data import add_metadata

        chunks = add_metadata(
            chunks=["첫 번째 청크", "두 번째 청크"],
            page_id="12345",
            title="테스트 페이지",
            url="https://example.com/page",
        )

        assert len(chunks) == 2, "청크 수가 일치하지 않습니다."
        assert chunks[0]["metadata"]["chunk_index"] == 0, "첫 번째 청크 인덱스는 0이어야 합니다."
        assert chunks[1]["metadata"]["chunk_index"] == 1, "두 번째 청크 인덱스는 1이어야 합니다."
        assert chunks[0]["metadata"]["total_chunks"] == 2, "total_chunks가 2여야 합니다."

    def test_empty_content_skipped(self):
        """빈 콘텐츠 페이지는 건너뛰어야 합니다"""
        from preprocess_data import split_into_chunks

        pages = [{"content": "", "page_id": "1", "title": "빈 페이지", "url": ""}]
        chunks = split_into_chunks(pages)

        assert len(chunks) == 0, "빈 콘텐츠에서 청크가 생성되면 안 됩니다."

    def test_load_and_save_chunks(self, sample_backup_json, tmp_path):
        """로드 → 분할 → 저장 파이프라인이 정상 동작해야 합니다"""
        from preprocess_data import load_backup_data, split_into_chunks, save_processed_chunks

        pages = load_backup_data(sample_backup_json)
        chunks = split_into_chunks(pages, chunk_size=200, chunk_overlap=50)

        output_path = str(tmp_path / "processed_chunks.json")
        save_processed_chunks(chunks, output_path)

        # 저장된 파일 검증
        saved = json.loads(Path(output_path).read_text(encoding="utf-8"))
        assert saved["total_chunks"] == len(chunks), "저장된 청크 수가 일치하지 않습니다."
        assert len(saved["chunks"]) == len(chunks), "청크 배열 길이가 일치하지 않습니다."


# ============================================
# 5. 벡터 DB 테스트
# ============================================

class TestVectorDB:
    """벡터 DB 검증"""

    @pytest.mark.slow
    def test_embedding_model_loads(self):
        """임베딩 모델이 정상적으로 로드되어야 합니다"""
        from build_vectordb import load_embedding_model

        embeddings = load_embedding_model()
        result = embeddings.embed_query("테스트 쿼리")

        assert isinstance(result, list), "임베딩 결과가 리스트가 아닙니다."
        assert len(result) > 0, "임베딩 벡터가 비어있습니다."

    @pytest.mark.slow
    def test_build_and_verify_vectordb(self, sample_pages, tmp_path):
        """벡터 DB 구축 및 검증"""
        from preprocess_data import split_into_chunks, save_processed_chunks
        from build_vectordb import build_vectordb, verify_vectordb

        # 청크 생성 및 저장
        chunks = split_into_chunks(sample_pages, chunk_size=200, chunk_overlap=50)
        chunks_path = str(tmp_path / "processed_chunks.json")
        save_processed_chunks(chunks, chunks_path)

        persist_dir = str(tmp_path / "test_vectordb")

        # 벡터 DB 구축
        result = build_vectordb(
            input_path=chunks_path,
            persist_dir=persist_dir,
            batch_size=10,
        )

        assert result is not None, "build_vectordb 결과가 None입니다."
        assert result["total_vectors"] > 0, "벡터가 생성되지 않았습니다."
        assert result["processed_chunks"] == len(chunks), "처리된 청크 수가 일치하지 않습니다."

        # 검증
        verify_result = verify_vectordb(persist_dir)
        assert verify_result is not None, "verify_vectordb 결과가 None입니다."
        assert verify_result["total_vectors"] == result["total_vectors"], "벡터 수가 불일치합니다."


# ============================================
# 6. RAG 검색 테스트
# ============================================

class TestRAGSearch:
    """RAG 검색 기능 검증"""

    @pytest.mark.slow
    def test_search_returns_valid_format(self, sample_pages, tmp_path, mock_ollama):
        """검색 결과가 올바른 형식을 가져야 합니다"""
        from preprocess_data import split_into_chunks, save_processed_chunks
        from build_vectordb import build_vectordb

        # 벡터 DB 준비
        chunks = split_into_chunks(sample_pages, chunk_size=200, chunk_overlap=50)
        chunks_path = str(tmp_path / "chunks.json")
        save_processed_chunks(chunks, chunks_path)
        persist_dir = str(tmp_path / "test_vectordb")
        build_vectordb(input_path=chunks_path, persist_dir=persist_dir, batch_size=10)

        # RAG 엔진 초기화 (Ollama mock)
        from rag_search import ConfluenceRAG
        with patch.dict(os.environ, {"OLLAMA_HOST": "http://localhost:11434", "OLLAMA_MODEL": "test"}):
            rag = ConfluenceRAG.__new__(ConfluenceRAG)
            rag.persist_dir = persist_dir
            rag.collection = rag._load_vectordb()
            from build_vectordb import load_embedding_model
            rag.embeddings = load_embedding_model()
            rag.llm = mock_ollama

            # 검색 실행
            result = rag.search("개발 환경 설정 방법", k=3)

        assert "answer" in result, "결과에 answer가 없습니다."
        assert "sources" in result, "결과에 sources가 없습니다."
        assert "query" in result, "결과에 query가 없습니다."
        assert "elapsed" in result, "결과에 elapsed가 없습니다."
        assert len(result["answer"]) > 0, "답변이 비어있습니다."

    @pytest.mark.slow
    def test_format_response_markdown(self, mock_ollama):
        """format_response가 Markdown 형식을 반환해야 합니다"""
        from rag_search import ConfluenceRAG

        rag = ConfluenceRAG.__new__(ConfluenceRAG)

        result = {
            "answer": "테스트 답변입니다.",
            "sources": [
                {"title": "페이지1", "url": "https://example.com/1", "page_id": "1", "relevance": 0.95},
            ],
            "query": "테스트 질문",
            "elapsed": 1.23,
        }

        formatted = rag.format_response(result)

        assert "## 답변" in formatted, "Markdown에 답변 제목이 없습니다."
        assert "## 참고 문서" in formatted, "Markdown에 참고 문서 제목이 없습니다."
        assert "페이지1" in formatted, "출처 제목이 없습니다."


# ============================================
# 7. 증분 업데이트 테스트
# ============================================

class TestIncrementalUpdate:
    """증분 업데이트 로직 검증"""

    def test_identify_new_pages(self, sample_backup_json, sample_sync_state, monkeypatch):
        """신규 페이지를 정확히 식별해야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", Path(sample_sync_state))
        from update_vectordb import identify_changes

        changes = identify_changes(sample_backup_json)

        # 100002는 sync_state에 없으므로 신규
        added_ids = [p.get("page_id") for p in changes["added"]]
        assert "100002" in added_ids, "신규 페이지 100002가 감지되지 않았습니다."

    def test_identify_modified_pages(self, sample_backup_json, sample_sync_state, monkeypatch):
        """수정된 페이지를 정확히 식별해야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", Path(sample_sync_state))
        from update_vectordb import identify_changes

        changes = identify_changes(sample_backup_json)

        # 100001은 version 4→5로 변경됨
        modified_ids = [p.get("page_id") for p in changes["modified"]]
        assert "100001" in modified_ids, "수정된 페이지 100001이 감지되지 않았습니다."

    def test_identify_deleted_pages(self, tmp_path, monkeypatch):
        """삭제된 페이지를 정확히 식별해야 합니다"""
        # 백업에는 100001만 존재
        backup = {
            "pages": [
                {"page_id": "100001", "title": "A", "version": 1, "last_modified": "2025-01-01"}
            ]
        }
        backup_path = tmp_path / "backup.json"
        backup_path.write_text(json.dumps(backup), encoding="utf-8")

        # sync_state에는 100001, 100002 모두 존재
        state = {
            "last_full_sync": None,
            "last_incremental_sync": None,
            "total_pages": 2,
            "pages": {
                "100001": {"version": 1, "last_modified": "2025-01-01"},
                "100002": {"version": 1, "last_modified": "2025-01-01"},
            },
            "sync_history": [],
        }
        state_path = tmp_path / "last_sync.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", state_path)
        from update_vectordb import identify_changes

        changes = identify_changes(str(backup_path))

        assert "100002" in changes["deleted"], "삭제된 페이지 100002가 감지되지 않았습니다."
