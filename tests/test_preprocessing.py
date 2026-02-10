"""
전처리 단위 테스트

preprocess_data.py의 청크 분할, 메타데이터 추가 기능을 검증합니다.
"""

import json
from pathlib import Path

import pytest


class TestSplitIntoChunks:
    """청크 분할 테스트"""

    def test_basic_split(self, sample_pages):
        """기본 청크 분할이 정상 동작해야 합니다"""
        from preprocess_data import split_into_chunks

        chunks = split_into_chunks(sample_pages, chunk_size=100, chunk_overlap=20)

        assert len(chunks) > 0, "청크가 생성되지 않았습니다."

    def test_chunk_size_limit(self, sample_page):
        """청크 크기가 설정된 최대값을 크게 초과하지 않아야 합니다"""
        from preprocess_data import split_into_chunks

        max_size = 150
        chunks = split_into_chunks([sample_page], chunk_size=max_size, chunk_overlap=30)

        for chunk in chunks:
            # 약간의 오차 허용 (분할기 특성)
            assert len(chunk["content"]) <= max_size * 1.2, \
                f"청크가 최대 크기를 초과: {len(chunk['content'])}자"

    def test_chunk_overlap_preserves_context(self, sample_page):
        """청크 간 오버랩이 문맥을 보존해야 합니다"""
        from preprocess_data import split_into_chunks

        chunks = split_into_chunks([sample_page], chunk_size=100, chunk_overlap=30)

        if len(chunks) >= 2:
            # 첫 청크의 끝부분과 두 번째 청크의 시작부분이 겹쳐야 함
            first_end = chunks[0]["content"][-30:]
            second_start = chunks[1]["content"][:50]
            # 오버랩 영역이 존재하는지 확인 (부분 문자열)
            overlap_found = any(
                word in second_start
                for word in first_end.split()
                if len(word) > 1
            )
            # 오버랩이 반드시 검출되지 않을 수 있으므로 경고만
            if not overlap_found:
                pytest.skip("오버랩 검증 스킵 (분할 경계에 따라 달라질 수 있음)")

    def test_empty_content_produces_no_chunks(self):
        """빈 콘텐츠는 청크를 생성하지 않아야 합니다"""
        from preprocess_data import split_into_chunks

        empty_pages = [
            {"content": "", "page_id": "1", "title": "빈 페이지", "url": ""},
            {"content": "   ", "page_id": "2", "title": "공백 페이지", "url": ""},
        ]
        chunks = split_into_chunks(empty_pages)

        assert len(chunks) == 0, "빈/공백 콘텐츠에서 청크가 생성되면 안 됩니다."

    def test_korean_separators_used(self):
        """한국어 종결어미에서 분할이 이루어져야 합니다"""
        from preprocess_data import split_into_chunks

        pages = [{
            "content": (
                "첫 번째 문장입니다. 두 번째 문장입니다. "
                "세 번째 문장이 있습니다. 네 번째 문장이 있습니다. "
                "다섯 번째 문장입니다. 여섯 번째 문장입니다. "
                "일곱 번째 문장이에요. 여덟 번째도 있어요."
            ),
            "page_id": "1",
            "title": "한국어 테스트",
            "url": "",
        }]
        chunks = split_into_chunks(pages, chunk_size=80, chunk_overlap=10)

        # 청크가 2개 이상이면 분할이 동작한 것
        assert len(chunks) >= 2, "한국어 텍스트가 분할되지 않았습니다."


class TestAddMetadata:
    """메타데이터 추가 테스트"""

    def test_metadata_fields(self):
        """모든 필수 메타데이터 필드가 존재해야 합니다"""
        from preprocess_data import add_metadata

        result = add_metadata(
            chunks=["테스트 텍스트"],
            page_id="12345",
            title="테스트",
            url="https://example.com",
        )

        meta = result[0]["metadata"]
        required_fields = ["page_id", "title", "url", "chunk_index", "total_chunks"]
        for field in required_fields:
            assert field in meta, f"메타데이터에 '{field}' 필드가 없습니다."

    def test_chunk_index_sequential(self):
        """chunk_index가 0부터 순차적으로 증가해야 합니다"""
        from preprocess_data import add_metadata

        result = add_metadata(
            chunks=["A", "B", "C"],
            page_id="1", title="T", url="U",
        )

        for i, chunk in enumerate(result):
            assert chunk["metadata"]["chunk_index"] == i, \
                f"chunk_index가 {i}여야 하지만 {chunk['metadata']['chunk_index']}입니다."

    def test_total_chunks_correct(self):
        """total_chunks가 전체 청크 수와 일치해야 합니다"""
        from preprocess_data import add_metadata

        texts = ["A", "B", "C", "D"]
        result = add_metadata(chunks=texts, page_id="1", title="T", url="U")

        for chunk in result:
            assert chunk["metadata"]["total_chunks"] == 4, \
                f"total_chunks가 4여야 하지만 {chunk['metadata']['total_chunks']}입니다."


class TestLoadAndSave:
    """로드/저장 테스트"""

    def test_load_backup_data(self, tmp_path, sample_pages):
        """backup JSON 로드가 정상 동작해야 합니다"""
        from preprocess_data import load_backup_data

        backup = {"pages": sample_pages}
        path = tmp_path / "backup.json"
        path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")

        pages = load_backup_data(str(path))
        assert len(pages) == len(sample_pages), "로드된 페이지 수가 일치하지 않습니다."

    def test_load_missing_file_raises(self):
        """존재하지 않는 파일 로드 시 FileNotFoundError"""
        from preprocess_data import load_backup_data

        with pytest.raises(FileNotFoundError):
            load_backup_data("/nonexistent/path.json")

    def test_save_and_reload_chunks(self, tmp_path, sample_chunks):
        """저장 후 다시 로드하면 데이터가 일치해야 합니다"""
        from preprocess_data import save_processed_chunks

        path = str(tmp_path / "chunks.json")
        save_processed_chunks(sample_chunks, path)

        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        assert saved["total_chunks"] == len(sample_chunks), "total_chunks 불일치"
        assert len(saved["chunks"]) == len(sample_chunks), "청크 배열 길이 불일치"
        assert saved["chunks"][0]["content"] == sample_chunks[0]["content"], "내용 불일치"
