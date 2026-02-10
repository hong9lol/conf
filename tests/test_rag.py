"""
RAG 검색 엔진 단위 테스트

ConfluenceRAG의 검색, 포맷팅 기능을 검증합니다.
Ollama는 mock으로 대체합니다.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestFormatResponse:
    """응답 포맷팅 테스트"""

    def test_format_includes_answer_section(self):
        """포맷된 응답에 '답변' 섹션이 있어야 합니다"""
        from rag_search import ConfluenceRAG

        rag = ConfluenceRAG.__new__(ConfluenceRAG)
        result = {
            "answer": "테스트 답변입니다.",
            "sources": [],
            "query": "질문",
            "elapsed": 1.0,
        }

        formatted = rag.format_response(result)
        assert "## 답변" in formatted, "답변 섹션이 없습니다."
        assert "테스트 답변입니다." in formatted, "답변 내용이 없습니다."

    def test_format_includes_sources(self):
        """출처가 있으면 '참고 문서' 섹션이 있어야 합니다"""
        from rag_search import ConfluenceRAG

        rag = ConfluenceRAG.__new__(ConfluenceRAG)
        result = {
            "answer": "답변",
            "sources": [
                {"title": "페이지A", "url": "https://a.com", "page_id": "1", "relevance": 0.95},
                {"title": "페이지B", "url": "https://b.com", "page_id": "2", "relevance": 0.80},
            ],
            "query": "질문",
            "elapsed": 1.5,
        }

        formatted = rag.format_response(result)
        assert "## 참고 문서" in formatted, "참고 문서 섹션이 없습니다."
        assert "페이지A" in formatted, "첫 번째 출처가 없습니다."
        assert "페이지B" in formatted, "두 번째 출처가 없습니다."
        assert "95%" in formatted, "관련도 퍼센트가 없습니다."

    def test_format_no_sources(self):
        """출처가 없으면 '참고 문서' 섹션이 없어야 합니다"""
        from rag_search import ConfluenceRAG

        rag = ConfluenceRAG.__new__(ConfluenceRAG)
        result = {
            "answer": "답변",
            "sources": [],
            "query": "질문",
            "elapsed": 0.5,
        }

        formatted = rag.format_response(result)
        assert "## 참고 문서" not in formatted, "출처가 없으면 참고 문서 섹션이 없어야 합니다."

    def test_format_includes_elapsed(self):
        """소요 시간이 표시되어야 합니다"""
        from rag_search import ConfluenceRAG

        rag = ConfluenceRAG.__new__(ConfluenceRAG)
        result = {
            "answer": "답변",
            "sources": [],
            "query": "질문",
            "elapsed": 2.34,
        }

        formatted = rag.format_response(result)
        assert "2.34초" in formatted, "소요 시간이 표시되지 않았습니다."


class TestBuildContext:
    """컨텍스트 구성 테스트"""

    def test_context_includes_all_docs(self):
        """모든 문서가 컨텍스트에 포함되어야 합니다"""
        from rag_search import ConfluenceRAG

        rag = ConfluenceRAG.__new__(ConfluenceRAG)

        documents = ["문서 A 내용", "문서 B 내용", "문서 C 내용"]
        metadatas = [
            {"title": "A", "chunk_index": 0, "total_chunks": 1},
            {"title": "B", "chunk_index": 0, "total_chunks": 1},
            {"title": "C", "chunk_index": 0, "total_chunks": 1},
        ]

        context = rag._build_context(documents, metadatas)

        assert "문서 A 내용" in context, "문서 A가 컨텍스트에 없습니다."
        assert "문서 B 내용" in context, "문서 B가 컨텍스트에 없습니다."
        assert "문서 C 내용" in context, "문서 C가 컨텍스트에 없습니다."

    def test_context_includes_titles(self):
        """컨텍스트에 문서 제목이 포함되어야 합니다"""
        from rag_search import ConfluenceRAG

        rag = ConfluenceRAG.__new__(ConfluenceRAG)

        documents = ["내용"]
        metadatas = [{"title": "개발 가이드", "chunk_index": 2, "total_chunks": 5}]

        context = rag._build_context(documents, metadatas)

        assert "개발 가이드" in context, "문서 제목이 컨텍스트에 없습니다."
        assert "3/5" in context, "청크 번호(3/5)가 표시되지 않았습니다."


class TestSearchIntegration:
    """검색 통합 테스트"""

    @pytest.mark.slow
    def test_search_end_to_end(self, tmp_path, sample_chunks, mock_ollama):
        """전체 검색 파이프라인이 정상 동작해야 합니다"""
        from build_vectordb import build_vectordb, load_embedding_model
        from rag_search import ConfluenceRAG

        # 벡터 DB 준비
        chunks_path = tmp_path / "chunks.json"
        chunks_path.write_text(
            json.dumps({"chunks": sample_chunks}, ensure_ascii=False),
            encoding="utf-8",
        )
        persist_dir = str(tmp_path / "vectordb")
        build_vectordb(input_path=str(chunks_path), persist_dir=persist_dir, batch_size=10)

        # RAG 엔진 수동 구성 (Ollama mock)
        rag = ConfluenceRAG.__new__(ConfluenceRAG)
        rag.persist_dir = persist_dir
        rag.collection = rag._load_vectordb()
        rag.embeddings = load_embedding_model()
        rag.llm = mock_ollama

        # 검색 실행
        result = rag.search("테스트 질문", k=2)

        # 결과 형식 검증
        assert isinstance(result, dict), "결과가 딕셔너리가 아닙니다."
        assert "answer" in result, "결과에 answer가 없습니다."
        assert "sources" in result, "결과에 sources가 없습니다."
        assert result["elapsed"] > 0, "소요 시간이 0보다 커야 합니다."

        # LLM이 호출되었는지 확인
        mock_ollama.invoke.assert_called_once()

    @pytest.mark.slow
    def test_search_deduplicates_sources(self, tmp_path, mock_ollama):
        """출처 URL 중복이 제거되어야 합니다"""
        from build_vectordb import build_vectordb, load_embedding_model
        from rag_search import ConfluenceRAG

        # 같은 URL의 청크 여러 개 생성
        chunks = [
            {
                "content": f"청크 {i} 내용입니다.",
                "metadata": {
                    "page_id": "1",
                    "title": "같은 페이지",
                    "url": "https://same-url.com",
                    "chunk_index": i,
                    "total_chunks": 3,
                },
            }
            for i in range(3)
        ]

        chunks_path = tmp_path / "chunks.json"
        chunks_path.write_text(
            json.dumps({"chunks": chunks}, ensure_ascii=False),
            encoding="utf-8",
        )
        persist_dir = str(tmp_path / "vectordb")
        build_vectordb(input_path=str(chunks_path), persist_dir=persist_dir, batch_size=10)

        rag = ConfluenceRAG.__new__(ConfluenceRAG)
        rag.persist_dir = persist_dir
        rag.collection = rag._load_vectordb()
        rag.embeddings = load_embedding_model()
        rag.llm = mock_ollama

        result = rag.search("테스트", k=3)

        # 같은 URL이므로 출처는 1개만
        assert len(result["sources"]) == 1, \
            f"중복 URL 제거 후 출처가 1개여야 하지만 {len(result['sources'])}개입니다."
