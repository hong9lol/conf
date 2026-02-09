"""
동기화 상태 관리 유틸리티

last_sync.json 파일을 통해 크롤링 동기화 상태를 관리합니다.
증분 크롤링 시 변경된 페이지만 수집할 수 있도록
마지막 동기화 시점의 페이지 정보를 추적합니다.
"""

import json
from datetime import datetime
from pathlib import Path

# 동기화 상태 파일 경로
SYNC_STATE_FILE = Path("last_sync.json")

# 동기화 이력 최대 보관 개수
MAX_SYNC_HISTORY = 20


def init_sync_state():
    """동기화 상태 파일 초기화

    last_sync.json이 존재하지 않으면 초기 상태로 생성합니다.
    이미 존재하면 아무 작업도 하지 않습니다.

    Returns:
        dict: 현재 동기화 상태
    """
    if SYNC_STATE_FILE.exists():
        return load_sync_state()

    # 초기 상태 구조
    initial_state = {
        "last_full_sync": None,
        "last_incremental_sync": None,
        "total_pages": 0,
        "pages": {},
        "sync_history": [],
    }

    _save_sync_state(initial_state)
    return initial_state


def load_sync_state() -> dict:
    """동기화 상태 파일 로드

    last_sync.json 파일을 읽어 동기화 상태를 반환합니다.
    파일이 없거나 손상된 경우 초기 상태를 반환합니다.

    Returns:
        dict: 동기화 상태 딕셔너리
    """
    if not SYNC_STATE_FILE.exists():
        return init_sync_state()

    try:
        content = SYNC_STATE_FILE.read_text(encoding="utf-8")
        state = json.loads(content)
        return state

    except (json.JSONDecodeError, IOError) as e:
        print(f"[경고] 동기화 상태 파일 로드 실패: {e}")
        print("[정보] 초기 상태로 재생성합니다.")
        return init_sync_state()


def update_sync_state(
    pages: dict,
    sync_record: dict,
    is_full_sync: bool,
    total_pages: int,
):
    """동기화 상태 파일 업데이트

    크롤링 결과를 반영하여 상태 파일을 갱신합니다.
    sync_history는 최근 20개만 유지합니다.

    Args:
        pages: 페이지별 상태 정보 딕셔너리
            {
                'page_id': {
                    'title': '...',
                    'url': '...',
                    'version': 1,
                    'last_modified': '...',
                    'last_crawled': '...'
                }
            }
        sync_record: 이번 동기화 기록
            {
                'timestamp': '...',
                'type': 'full' | 'incremental',
                'added': 5,
                'modified': 3,
                'deleted': 1,
                ...
            }
        is_full_sync: 전체 동기화 여부
        total_pages: 전체 페이지 수
    """
    # 현재 상태 로드
    state = load_sync_state()

    # 동기화 시간 업데이트
    now = datetime.now().isoformat()
    if is_full_sync:
        state["last_full_sync"] = now
    else:
        state["last_incremental_sync"] = now

    # 전체 페이지 수 업데이트
    state["total_pages"] = total_pages

    # 페이지별 상태 업데이트
    state["pages"] = pages

    # 동기화 이력 추가 (최근 20개만 유지)
    history = state.get("sync_history", [])
    history.append(sync_record)
    state["sync_history"] = history[-MAX_SYNC_HISTORY:]

    # 저장
    _save_sync_state(state)


def get_last_sync_time(sync_type: str = "any") -> str | None:
    """마지막 동기화 시간 반환

    Args:
        sync_type: 조회할 동기화 유형
            - 'full': 마지막 전체 동기화 시간
            - 'incremental': 마지막 증분 동기화 시간
            - 'any': 둘 중 더 최근 시간

    Returns:
        ISO 형식 시간 문자열 또는 None (동기화 이력 없음)
    """
    state = load_sync_state()

    if sync_type == "full":
        return state.get("last_full_sync")

    if sync_type == "incremental":
        return state.get("last_incremental_sync")

    # 'any': 둘 중 더 최근 시간 반환
    full_time = state.get("last_full_sync")
    incr_time = state.get("last_incremental_sync")

    if full_time and incr_time:
        return max(full_time, incr_time)
    return full_time or incr_time


def _save_sync_state(state: dict):
    """동기화 상태를 파일에 저장 (내부 함수)

    Args:
        state: 저장할 동기화 상태 딕셔너리
    """
    SYNC_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
