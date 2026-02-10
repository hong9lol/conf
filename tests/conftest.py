"""
tests/ 디렉토리 전용 conftest

공통 픽스처는 루트 conftest.py에 정의되어 있습니다.
이 파일에는 단위 테스트 전용 픽스처만 추가합니다.
"""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_sync_state(tmp_path):
    """임시 sync state 파일 경로"""
    return tmp_path / "last_sync.json"
