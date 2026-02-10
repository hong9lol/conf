"""
크롤러 단위 테스트

ConfluenceCrawler의 개별 메서드를 검증합니다.
외부 의존성(Playwright, Confluence)은 mock으로 대체합니다.
"""

import os
from unittest.mock import patch

import pytest


class TestCrawlerInit:
    """크롤러 초기화 테스트"""

    def test_init_with_valid_env(self, env_vars, tmp_sync_state, monkeypatch):
        """올바른 환경변수로 초기화 성공"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler(full_crawl=False)
            assert crawler.base_url == env_vars["CONFLUENCE_BASE_URL"]
            assert crawler.full_crawl is False

    def test_init_full_crawl_mode(self, env_vars, tmp_sync_state, monkeypatch):
        """전체 크롤링 모드 설정 확인"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler(full_crawl=True)
            assert crawler.full_crawl is True

    def test_init_missing_env_raises(self, tmp_sync_state, monkeypatch):
        """필수 환경변수 누락 시 ValueError 발생"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        empty = {"CONFLUENCE_BASE_URL": "", "CONFLUENCE_USERNAME": "",
                 "CONFLUENCE_PASSWORD": "", "ROOT_PAGE_URL": ""}
        with patch.dict(os.environ, empty, clear=False):
            from confluence_crawler import ConfluenceCrawler
            with pytest.raises(ValueError):
                ConfluenceCrawler()

    def test_initial_stats_zero(self, env_vars, tmp_sync_state, monkeypatch):
        """초기 통계값이 모두 0"""
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            crawler = ConfluenceCrawler()
            for val in crawler.stats.values():
                assert val == 0


class TestPageIdExtraction:
    """페이지 ID 추출 테스트"""

    def test_from_url_path(self, env_vars, tmp_sync_state, monkeypatch):
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            c = ConfluenceCrawler()
            assert c._extract_page_id("https://x.com/wiki/spaces/A/pages/123456/T") == "123456"

    def test_from_query_param(self, env_vars, tmp_sync_state, monkeypatch):
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            c = ConfluenceCrawler()
            assert c._extract_page_id("https://x.com/wiki/pages?pageId=789012") == "789012"

    def test_no_match(self, env_vars, tmp_sync_state, monkeypatch):
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            c = ConfluenceCrawler()
            assert c._extract_page_id("https://example.com/no-id") == ""


class TestPageModificationCheck:
    """페이지 변경 감지 테스트"""

    def _make_crawler(self, env_vars, tmp_sync_state, monkeypatch, full=False):
        monkeypatch.setattr("sync_state.SYNC_STATE_FILE", tmp_sync_state)
        with patch.dict(os.environ, env_vars):
            from confluence_crawler import ConfluenceCrawler
            return ConfluenceCrawler(full_crawl=full)

    def test_full_crawl_always_true(self, env_vars, tmp_sync_state, monkeypatch):
        c = self._make_crawler(env_vars, tmp_sync_state, monkeypatch, full=True)
        assert c.is_page_modified("any", 1, "2025-01-01") is True

    def test_new_page_is_modified(self, env_vars, tmp_sync_state, monkeypatch):
        c = self._make_crawler(env_vars, tmp_sync_state, monkeypatch)
        c.sync_state = {"pages": {}}
        assert c.is_page_modified("new_id", 1, "2025-01-01") is True

    def test_same_version_not_modified(self, env_vars, tmp_sync_state, monkeypatch):
        c = self._make_crawler(env_vars, tmp_sync_state, monkeypatch)
        c.sync_state = {"pages": {"1": {"version": 5, "last_modified": "2025-01-01"}}}
        assert c.is_page_modified("1", 5, "2025-01-01") is False

    def test_different_version_is_modified(self, env_vars, tmp_sync_state, monkeypatch):
        c = self._make_crawler(env_vars, tmp_sync_state, monkeypatch)
        c.sync_state = {"pages": {"1": {"version": 5, "last_modified": "2025-01-01"}}}
        assert c.is_page_modified("1", 6, "2025-01-02") is True
