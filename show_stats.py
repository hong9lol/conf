"""
시스템 통계 대시보드

크롤링, 벡터 DB, 시스템 정보를 Rich 테이블로 출력합니다.
JSON 내보내기 및 파일 저장을 지원합니다.
"""

import json
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sync_state import load_sync_state

console = Console()

# 파일 경로
VECTORDB_DIR = Path("confluence_vectordb")
BACKUP_JSON = Path("confluence_backup.json")
PROCESSED_JSON = Path("processed_chunks.json")
PAGES_DIR = Path("confluence_pages")
LOGS_DIR = Path("logs")


def get_system_info() -> dict:
    """시스템 정보 수집

    Returns:
        시스템 정보 딕셔너리
    """
    info = {
        "python_version": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "packages": {},
        "disk": {},
    }

    # 주요 패키지 버전 확인
    packages = [
        "playwright", "beautifulsoup4", "markdownify", "langchain",
        "chromadb", "sentence_transformers", "gradio", "rich",
    ]
    for pkg_name in packages:
        try:
            mod = __import__(pkg_name)
            version = getattr(mod, "__version__", "설치됨")
            info["packages"][pkg_name] = version
        except ImportError:
            info["packages"][pkg_name] = "미설치"

    # 디스크 사용량
    usage = shutil.disk_usage(".")
    info["disk"] = {
        "total_gb": round(usage.total / (1024 ** 3), 1),
        "used_gb": round(usage.used / (1024 ** 3), 1),
        "free_gb": round(usage.free / (1024 ** 3), 1),
        "percent": round(usage.used / usage.total * 100, 1),
    }

    return info


def get_crawl_stats() -> dict:
    """크롤링 통계 수집

    Returns:
        크롤링 통계 딕셔너리
    """
    stats = {
        "total_pages": 0,
        "last_full_sync": None,
        "last_incremental_sync": None,
        "sync_history": [],
        "md_files": 0,
    }

    # 동기화 상태에서 정보 로드
    sync_state = load_sync_state()
    stats["total_pages"] = sync_state.get("total_pages", 0)
    stats["last_full_sync"] = sync_state.get("last_full_sync")
    stats["last_incremental_sync"] = sync_state.get("last_incremental_sync")
    stats["sync_history"] = sync_state.get("sync_history", [])

    # Markdown 파일 수
    if PAGES_DIR.exists():
        stats["md_files"] = len(list(PAGES_DIR.glob("*.md")))

    return stats


def get_vectordb_stats() -> dict:
    """벡터 DB 통계 수집

    Returns:
        벡터 DB 통계 딕셔너리
    """
    stats = {
        "exists": VECTORDB_DIR.exists(),
        "total_vectors": 0,
        "total_chunks": 0,
        "db_size_mb": 0,
        "avg_chunk_size": 0,
    }

    if not VECTORDB_DIR.exists():
        return stats

    # DB 크기 계산
    db_bytes = sum(f.stat().st_size for f in VECTORDB_DIR.rglob("*") if f.is_file())
    stats["db_size_mb"] = round(db_bytes / (1024 * 1024), 2)

    # ChromaDB에서 벡터 수 조회
    try:
        from chromadb import PersistentClient
        from chromadb.config import Settings
        client = PersistentClient(
            path=str(VECTORDB_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        collection = client.get_collection(name="confluence_pages")
        stats["total_vectors"] = collection.count()
    except Exception:
        pass

    # 청크 통계
    if PROCESSED_JSON.exists():
        try:
            with open(PROCESSED_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            chunks = data.get("chunks", [])
            stats["total_chunks"] = len(chunks)
            if chunks:
                total_len = sum(len(c.get("content", "")) for c in chunks)
                stats["avg_chunk_size"] = round(total_len / len(chunks))
        except Exception:
            pass

    return stats


def _format_time(iso_str: str | None) -> str:
    """ISO 시간 문자열을 읽기 좋은 형태로 변환"""
    if not iso_str:
        return "[dim]없음[/dim]"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso_str


def _status_color(value, warn_threshold, error_threshold, reverse=False) -> str:
    """값에 따라 색상 지정"""
    if reverse:
        if value <= error_threshold:
            return "red"
        if value <= warn_threshold:
            return "yellow"
        return "green"
    else:
        if value >= error_threshold:
            return "red"
        if value >= warn_threshold:
            return "yellow"
        return "green"


def display_system_info(info: dict):
    """시스템 정보 테이블 출력"""
    table = Table(title="시스템 정보", show_header=True, header_style="bold cyan")
    table.add_column("항목", style="bold")
    table.add_column("값", justify="right")

    table.add_row("Python 버전", info["python_version"])
    table.add_row("플랫폼", info["platform"])

    # 디스크
    disk = info["disk"]
    disk_color = _status_color(disk["percent"], 70, 90)
    table.add_row(
        "디스크 사용량",
        f"[{disk_color}]{disk['used_gb']}GB / {disk['total_gb']}GB ({disk['percent']}%)[/{disk_color}]",
    )
    table.add_row("디스크 여유", f"{disk['free_gb']}GB")

    console.print(table)

    # 패키지 테이블
    pkg_table = Table(title="패키지 버전", show_header=True, header_style="bold cyan")
    pkg_table.add_column("패키지", style="bold")
    pkg_table.add_column("버전", justify="right")

    for pkg, ver in info["packages"].items():
        color = "green" if ver != "미설치" else "red"
        pkg_table.add_row(pkg, f"[{color}]{ver}[/{color}]")

    console.print(pkg_table)


def display_crawl_stats(stats: dict):
    """크롤링 통계 테이블 출력"""
    table = Table(title="크롤링 통계", show_header=True, header_style="bold cyan")
    table.add_column("항목", style="bold")
    table.add_column("값", justify="right")

    page_color = "green" if stats["total_pages"] > 0 else "yellow"
    table.add_row("총 페이지 수", f"[{page_color}]{stats['total_pages']}[/{page_color}]")
    table.add_row("Markdown 파일 수", str(stats["md_files"]))
    table.add_row("마지막 전체 크롤링", _format_time(stats["last_full_sync"]))
    table.add_row("마지막 증분 업데이트", _format_time(stats["last_incremental_sync"]))

    console.print(table)

    # 동기화 이력 테이블
    history = stats["sync_history"]
    if history:
        hist_table = Table(title="최근 동기화 이력", show_header=True, header_style="bold cyan")
        hist_table.add_column("시간", style="dim")
        hist_table.add_column("유형", justify="center")
        hist_table.add_column("추가", justify="right", style="green")
        hist_table.add_column("수정", justify="right", style="yellow")
        hist_table.add_column("삭제", justify="right", style="red")

        # 최근 10개만 표시 (최신순)
        for record in reversed(history[-10:]):
            sync_type = "전체" if record.get("type") == "full" else "증분"
            hist_table.add_row(
                _format_time(record.get("timestamp")),
                sync_type,
                str(record.get("added", 0)),
                str(record.get("modified", 0)),
                str(record.get("deleted", 0)),
            )

        console.print(hist_table)
    else:
        console.print("[dim]동기화 이력이 없습니다.[/dim]")


def display_vectordb_stats(stats: dict):
    """벡터 DB 통계 테이블 출력"""
    table = Table(title="벡터 DB 통계", show_header=True, header_style="bold cyan")
    table.add_column("항목", style="bold")
    table.add_column("값", justify="right")

    if not stats["exists"]:
        table.add_row("상태", "[red]미생성[/red]")
        console.print(table)
        console.print("[yellow]벡터 DB를 먼저 구축해주세요: python build_vectordb.py[/yellow]")
        return

    table.add_row("상태", "[green]정상[/green]")
    table.add_row("총 벡터 수", f"{stats['total_vectors']:,}")
    table.add_row("총 청크 수", f"{stats['total_chunks']:,}")
    table.add_row("DB 크기", f"{stats['db_size_mb']:.2f} MB")

    if stats["avg_chunk_size"] > 0:
        table.add_row("평균 청크 크기", f"{stats['avg_chunk_size']:,}자")

    console.print(table)


def display_search_stats():
    """검색 통계 (구현 예정) 플레이스홀더"""
    table = Table(title="검색 통계", show_header=True, header_style="bold cyan")
    table.add_column("항목", style="bold")
    table.add_column("값", justify="right")

    table.add_row("오늘 검색 수", "[dim]구현 예정[/dim]")
    table.add_row("인기 검색어", "[dim]구현 예정[/dim]")

    console.print(table)


def collect_all_stats() -> dict:
    """전체 통계 수집

    Returns:
        모든 통계를 포함하는 딕셔너리
    """
    return {
        "timestamp": datetime.now().isoformat(),
        "system": get_system_info(),
        "crawl": get_crawl_stats(),
        "vectordb": get_vectordb_stats(),
    }


# ============================================
# CLI 진입점
# ============================================
@click.command()
@click.option(
    "--json-output", "as_json",
    is_flag=True,
    default=False,
    help="JSON 형식으로 출력",
)
@click.option(
    "--export", "export_path",
    default=None,
    type=str,
    help="통계를 파일로 저장 (예: stats.json)",
)
def main(as_json: bool, export_path: str | None):
    """Confluence RAG 시스템 통계 대시보드

    시스템 정보, 크롤링 통계, 벡터 DB 통계를 출력합니다.

    \b
    사용 예시:
        python show_stats.py              # 대시보드 출력
        python show_stats.py --json       # JSON 형식 출력
        python show_stats.py --export stats.json  # 파일로 저장
    """
    all_stats = collect_all_stats()

    # JSON 출력 모드
    if as_json:
        # Rich 포맷 제거를 위해 직접 print
        print(json.dumps(all_stats, ensure_ascii=False, indent=2, default=str))
        return

    # 파일 내보내기
    if export_path:
        Path(export_path).write_text(
            json.dumps(all_stats, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        console.print(f"[green]통계 저장 완료: {export_path}[/green]")
        return

    # --- 대시보드 출력 ---
    console.print()
    console.print(Panel(
        f"[bold]Confluence RAG 시스템 통계[/bold]\n"
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
        border_style="magenta",
    ))
    console.print()

    # 1. 시스템 정보
    display_system_info(all_stats["system"])
    console.print()

    # 2. 크롤링 통계
    display_crawl_stats(all_stats["crawl"])
    console.print()

    # 3. 벡터 DB 통계
    display_vectordb_stats(all_stats["vectordb"])
    console.print()

    # 4. 검색 통계 (구현 예정)
    display_search_stats()
    console.print()


if __name__ == "__main__":
    main()
