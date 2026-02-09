"""
공통 픽스처 모음

모든 테스트에서 공유하는 픽스처를 정의합니다.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_page():
    """단일 테스트용 페이지 데이터"""
    return {
        "title": "테스트 페이지",
        "url": "https://example.atlassian.net/wiki/spaces/TEST/pages/99999/Test",
        "page_id": "99999",
        "version": 1,
        "last_modified": "2025-02-09T10:00:00",
        "content": (
            "# 테스트 문서\n\n"
            "이것은 테스트 문서입니다. "
            "테스트를 위한 충분한 길이의 텍스트가 필요합니다.\n\n"
            "## 섹션 1\n\n"
            "첫 번째 섹션의 내용입니다. "
            "여러 문장을 포함하여 청크 분할을 테스트합니다.\n\n"
            "## 섹션 2\n\n"
            "두 번째 섹션의 내용입니다. "
            "이 섹션은 다른 주제를 다룹니다."
        ),
        "depth": 0,
        "crawled_at": "2025-02-09T11:00:00",
    }


@pytest.fixture
def sample_pages(sample_page):
    """여러 개의 테스트용 페이지 데이터"""
    page2 = {
        **sample_page,
        "title": "두 번째 페이지",
        "page_id": "99998",
        "content": "# 두 번째 문서\n\n간단한 내용입니다.",
    }
    return [sample_page, page2]


@pytest.fixture
def sample_chunks():
    """테스트용 청크 데이터"""
    return [
        {
            "content": "첫 번째 청크 내용입니다.",
            "metadata": {
                "page_id": "99999",
                "title": "테스트 페이지",
                "url": "https://example.com/page",
                "chunk_index": 0,
                "total_chunks": 2,
            },
        },
        {
            "content": "두 번째 청크 내용입니다.",
            "metadata": {
                "page_id": "99999",
                "title": "테스트 페이지",
                "url": "https://example.com/page",
                "chunk_index": 1,
                "total_chunks": 2,
            },
        },
    ]


@pytest.fixture
def tmp_sync_state(tmp_path):
    """임시 sync state 파일 경로 및 monkeypatch 적용"""
    return tmp_path / "last_sync.json"


@pytest.fixture
def env_vars():
    """테스트용 환경변수"""
    return {
        "CONFLUENCE_BASE_URL": "https://test.atlassian.net/wiki",
        "CONFLUENCE_USERNAME": "test@example.com",
        "CONFLUENCE_PASSWORD": "test-token",
        "ROOT_PAGE_URL": "https://test.atlassian.net/wiki/spaces/T/pages/1/Root",
        "OLLAMA_HOST": "http://localhost:11434",
        "OLLAMA_MODEL": "test-model",
    }


@pytest.fixture
def mock_ollama():
    """Ollama LLM mock"""
    mock = MagicMock()
    mock.invoke.return_value = "테스트 답변입니다."
    return mock
