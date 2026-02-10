"""
벡터 DB 단위 테스트

build_vectordb.py와 update_vectordb.py의 핵심 기능을 검증합니다.
임베딩 모델 로드가 필요한 테스트는 @pytest.mark.slow로 표시합니다.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestProgressTracking:
    """진행 상황 추적 테스트"""

    def test_save_and_load_progress(self, tmp_path, monkeypatch):
        """진행 상황 저장/로드가 정상 동작해야 합니다"""
        monkeypatch.setattr("build_vectordb.PROGRESS_FILE", tmp_path / ".progress.json")
        from build_vectordb import _save_progress, _load_progress

        _save_progress(42)
        result = _load_progress()

        assert result == 42, f"저장된 배치 인덱스가 42여야 하지만 {result}입니다."

    def test_load_progress_no_file(self, tmp_path, monkeypatch):
        """진행 파일이 없으면 0을 반환해야 합니다"""
        monkeypatch.setattr("build_vectordb.PROGRESS_FILE", tmp_path / ".progress.json")
        from build_vectordb import _load_progress

        result = _load_progress()

        assert result == 0, "진행 파일이 없으면 0을 반환해야 합니다."

    def test_clear_progress(self, tmp_path, monkeypatch):
        """진행 파일을 정상적으로 삭제해야 합니다"""
        monkeypatch.setattr("build_vectordb.PROGRESS_FILE", tmp_path / ".progress.json")
        from build_vectordb import _save_progress, _clear_progress

        _save_progress(10)
        _clear_progress()

        assert not (tmp_path / ".progress.json").exists(), "진행 파일이 삭제되지 않았습니다."


class TestLoadChunks:
    """청크 로드 테스트"""

    def test_load_valid_chunks(self, tmp_path, sample_chunks):
        """유효한 청크 파일을 정상 로드해야 합니다"""
        from build_vectordb import _load_chunks

        path = tmp_path / "chunks.json"
        path.write_text(
            json.dumps({"chunks": sample_chunks}, ensure_ascii=False),
            encoding="utf-8",
        )

        result = _load_chunks(str(path))
        assert len(result) == len(sample_chunks), "로드된 청크 수가 일치하지 않습니다."

    def test_load_missing_file_raises(self):
        """존재하지 않는 파일은 FileNotFoundError"""
        from build_vectordb import _load_chunks

        with pytest.raises(FileNotFoundError):
            _load_chunks("/nonexistent/chunks.json")


class TestEmbeddingModel:
    """임베딩 모델 테스트"""

    @pytest.mark.slow
    def test_model_loads_successfully(self):
        """임베딩 모델이 정상 로드되어야 합니다"""
        from build_vectordb import load_embedding_model

        model = load_embedding_model()
        assert model is not None, "임베딩 모델이 None입니다."

    @pytest.mark.slow
    def test_embed_returns_vector(self):
        """임베딩 결과가 숫자 벡터여야 합니다"""
        from build_vectordb import load_embedding_model

        model = load_embedding_model()
        vector = model.embed_query("테스트 문장")

        assert isinstance(vector, list), "임베딩 결과가 리스트가 아닙니다."
        assert len(vector) > 0, "임베딩 벡터가 비어있습니다."
        assert all(isinstance(v, float) for v in vector), "벡터 요소가 float이 아닙니다."

    @pytest.mark.slow
    def test_similar_texts_have_close_vectors(self):
        """유사한 텍스트는 비슷한 벡터를 가져야 합니다"""
        from build_vectordb import load_embedding_model
        import math

        model = load_embedding_model()
        v1 = model.embed_query("개발 환경 설정 방법")
        v2 = model.embed_query("개발 환경을 설정하는 방법")
        v3 = model.embed_query("오늘 점심 메뉴 추천")

        # 코사인 유사도 계산
        def cosine_sim(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x ** 2 for x in a))
            norm_b = math.sqrt(sum(x ** 2 for x in b))
            return dot / (norm_a * norm_b) if norm_a and norm_b else 0

        sim_similar = cosine_sim(v1, v2)
        sim_different = cosine_sim(v1, v3)

        assert sim_similar > sim_different, \
            f"유사 텍스트 유사도({sim_similar:.3f})가 " \
            f"비유사 텍스트({sim_different:.3f})보다 높아야 합니다."


class TestBuildVectorDB:
    """벡터 DB 구축 테스트"""

    @pytest.mark.slow
    def test_build_creates_db(self, tmp_path, sample_chunks):
        """build_vectordb가 DB를 정상 생성해야 합니다"""
        from build_vectordb import build_vectordb

        chunks_path = tmp_path / "chunks.json"
        chunks_path.write_text(
            json.dumps({"chunks": sample_chunks}, ensure_ascii=False),
            encoding="utf-8",
        )

        persist_dir = str(tmp_path / "vectordb")
        result = build_vectordb(
            input_path=str(chunks_path),
            persist_dir=persist_dir,
            batch_size=10,
        )

        assert result is not None, "결과가 None입니다."
        assert result["total_vectors"] == len(sample_chunks), \
            f"벡터 수가 {len(sample_chunks)}이어야 하지만 {result['total_vectors']}입니다."
        assert Path(persist_dir).exists(), "DB 디렉토리가 생성되지 않았습니다."

    @pytest.mark.slow
    def test_rebuild_clears_existing(self, tmp_path, sample_chunks):
        """--rebuild가 기존 DB를 삭제하고 재구축해야 합니다"""
        from build_vectordb import build_vectordb

        chunks_path = tmp_path / "chunks.json"
        chunks_path.write_text(
            json.dumps({"chunks": sample_chunks}, ensure_ascii=False),
            encoding="utf-8",
        )
        persist_dir = str(tmp_path / "vectordb")

        # 첫 번째 빌드
        build_vectordb(input_path=str(chunks_path), persist_dir=persist_dir, batch_size=10)

        # 재구축
        result = build_vectordb(
            input_path=str(chunks_path),
            persist_dir=persist_dir,
            batch_size=10,
            rebuild=True,
        )

        assert result["total_vectors"] == len(sample_chunks), \
            "재구축 후 벡터 수가 원본 청크 수와 일치해야 합니다."
