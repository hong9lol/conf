"""
크롤러 단위 테스트

ConfluenceCrawler의 개별 메서드를 검증합니다.
외부 의존성(Playwright, Confluence)은 mock으로 대체합니다.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestCrawlerInit:
    """크롤러 초기화 테스트"""

    def test_init_with_valid_env(self, env_vars, tmp_sync_state, monkeypatch):
        """올바른 환경변수로 초기화 성공"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler(full_crawl=False)

            assert crawler.base_url == env_vars["CONFLUENCE_BASE_URL"], "base_url 불일치"
            assert crawler.full_crawl is False, "full_crawl 설정 불일치"

    def test_init_full_crawl_mode(self, env_vars, tmp_sync_state, monkeypatch):
        """전체 크롤링 모드 설정 확인"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler(full_crawl=True)

            assert crawler.full_crawl is True, "full_crawl=True로 설정되어야 합니다."

    def test_init_missing_env_raises(self, tmp_sync_state, monkeypatch):
        """필수 환경변수 누락 시 ValueError 발생"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        empty_env = {
            "CONFLUENCE_BASE_URL": "",
            "CONFLUENCE_USERNAME": "",
            "CONFLUENCE_PASSWORD": "",
            "ROOT_PAGE_URL": "",
        }
        with patch.dict(os.environ, empty_env, clear=False):
            from confluence_crawler import ConfluenceCrawler
            with pytest.raises(ValueError):
                ConfluenceCrawler()

    def test_initial_stats_are_zero(self, env_vars, tmp_sync_state, monkeypatch):
        """초기 통계값이 모두 0이어야 합니다"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler()

            for key, value in crawler.stats.items():
                assert value == 0, f"초기 stats['{key}']가 0이 아닙니다: {value}"


class TestPageIdExtraction:
    """페이지 ID 추출 테스트"""

    def test_extract_id_from_url_path(self, env_vars, tmp_sync_state, monkeypatch):
        """/pages/123456/ 패턴에서 ID 추출"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler()

            result = crawler._extract_page_id(
                "https://example.atlassian.net/wiki/spaces/DEV/pages/123456/Title"
            )
            assert result == "123456", f"페이지 ID가 '123456'이어야 하지만 '{result}'입니다."

    def test_extract_id_from_query_param(self, env_vars, tmp_sync_state, monkeypatch):
        """pageId=123456 쿼리 파라미터에서 ID 추출"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler()

            result = crawler._extract_page_id(
                "https://example.atlassian.net/wiki/pages?pageId=789012"
            )
            assert result == "789012", f"페이지 ID가 '789012'이어야 하지만 '{result}'입니다."

    def test_extract_id_no_match(self, env_vars, tmp_sync_state, monkeypatch):
        """ID 패턴이 없는 URL은 빈 문자열 반환"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler()

            result = crawler._extract_page_id("https://example.com/no-id-here")
            assert result == "", "ID가 없는 URL은 빈 문자열을 반환해야 합니다."


class TestPageModificationCheck:
    """페이지 변경 감지 테스트"""

    def test_full_crawl_always_modified(self, env_vars, tmp_sync_state, monkeypatch):
        """전체 크롤링 모드에서는 항상 True"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler(full_crawl=True)

            assert crawler.is_page_modified("any", 1, "2025-01-01") is True

    def test_new_page_is_modified(self, env_vars, tmp_sync_state, monkeypatch):
        """신규 페이지는 항상 modified"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler(full_crawl=False)
            crawler.sync_state = {"pages": {}}

            assert crawler.is_page_modified("new_id", 1, "2025-01-01") is True

    def test_same_version_not_modified(self, env_vars, tmp_sync_state, monkeypatch):
        """같은 버전은 not modified"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler(full_crawl=False)
            crawler.sync_state = {
                "pages": {"123": {"version": 5, "last_modified": "2025-01-01"}}
            }

            assert crawler.is_page_modified("123", 5, "2025-01-01") is False

    def test_different_version_is_modified(self, env_vars, tmp_sync_state, monkeypatch):
        """다른 버전은 modified"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler(full_crawl=False)
            crawler.sync_state = {
                "pages": {"123": {"version": 5, "last_modified": "2025-01-01"}}
            }

            assert crawler.is_page_modified("123", 6, "2025-01-02") is True
