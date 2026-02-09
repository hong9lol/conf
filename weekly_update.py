"""
주간 업데이트 통합 스크립트

크롤링 → 전처리 → 벡터 DB 업데이트의 전체 파이프라인을
하나의 명령으로 실행합니다. 각 단계의 실패를 감지하여
롤백하고, 상세한 로그를 기록합니다.
"""

import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import click
import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

load_dotenv()

console = Console()

# ============================================
# 디렉토리 및 파일 경로
# ============================================
LOGS_DIR = Path("logs")
BACKUP_DIR = Path("backups")
VECTORDB_DIR = Path("confluence_vectordb")
BACKUP_JSON = Path("confluence_backup.json")
PROCESSED_JSON = Path("processed_chunks.json")
SYNC_STATE_FILE = Path("last_sync.json")


def _setup_logger(log_path: Path) -> logging.Logger:
    """파일 + 콘솔 로거 설정

    Args:
        log_path: 로그 파일 경로

    Returns:
        설정된 Logger 인스턴스
    """
    logger = logging.getLogger("weekly_update")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # 파일 핸들러
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(file_handler)

    # 콘솔 핸들러 (Rich)
    console_handler = RichHandler(
        console=console,
        show_path=False,
        rich_tracebacks=True,
    )
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    return logger


def _create_backup(logger: logging.Logger) -> dict:
    """현재 상태 백업 (롤백용)

    벡터 DB, 동기화 상태, 백업 JSON의 스냅샷을 저장합니다.

    Args:
        logger: 로거

    Returns:
        백업 경로 정보 딕셔너리
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rollback_dir = BACKUP_DIR / f"rollback_{timestamp}"
    rollback_dir.mkdir(parents=True, exist_ok=True)

    backup_info = {"rollback_dir": str(rollback_dir), "files": []}

    # 동기화 상태 백업
    try:
        if SYNC_STATE_FILE.exists():
            dest = rollback_dir / SYNC_STATE_FILE.name
            shutil.copy2(SYNC_STATE_FILE, dest)
            backup_info["files"].append(str(dest))
            logger.debug(f"백업: {SYNC_STATE_FILE} → {dest}")
    except Exception as e:
        logger.error(f"동기화 상태 백업 실패: {e}")
    
    # 백업 JSON 백업
    if BACKUP_JSON.exists():
        dest = rollback_dir / BACKUP_JSON.name
        shutil.copy2(BACKUP_JSON, dest)
        backup_info["files"].append(str(dest))
        logger.debug(f"백업: {BACKUP_JSON} → {dest}")

    # 벡터 DB 디렉토리 백업 (존재 시)
    if VECTORDB_DIR.exists():
        dest = rollback_dir / "confluence_vectordb"
        shutil.copytree(VECTORDB_DIR, dest)
        backup_info["vectordb_backup"] = str(dest)
        logger.debug(f"백업: {VECTORDB_DIR} → {dest}")

    logger.info(f"롤백 백업 생성 완료: {rollback_dir}")
    return backup_info


def _rollback(backup_info: dict, logger: logging.Logger):
    """실패 시 이전 상태로 롤백

    Args:
        backup_info: _create_backup 반환값
        logger: 로거
    """
    logger.warning("롤백을 시작합니다...")
    rollback_dir = Path(backup_info["rollback_dir"])

    try:
        # 동기화 상태 복원
        sync_backup = rollback_dir / SYNC_STATE_FILE.name
        if sync_backup.exists():
            shutil.copy2(sync_backup, SYNC_STATE_FILE)
            logger.info(f"복원: {SYNC_STATE_FILE}")

        # 백업 JSON 복원
        json_backup = rollback_dir / BACKUP_JSON.name
        if json_backup.exists():
            shutil.copy2(json_backup, BACKUP_JSON)
            logger.info(f"복원: {BACKUP_JSON}")

        # 벡터 DB 복원
        vectordb_backup = backup_info.get("vectordb_backup")
        if vectordb_backup and Path(vectordb_backup).exists():
            if VECTORDB_DIR.exists():
                shutil.rmtree(VECTORDB_DIR)
            shutil.copytree(vectordb_backup, VECTORDB_DIR)
            logger.info(f"복원: {VECTORDB_DIR}")

        logger.info("롤백 완료")

    except Exception as e:
        logger.error(f"롤백 실패: {e}")
        logger.error(f"수동 복원 필요: {rollback_dir}")


# ============================================
# 파이프라인 단계별 함수
# ============================================

def step_check_environment(logger: logging.Logger) -> bool:
    """1단계: 환경 확인

    .env 파일, Ollama 서버, 필수 디렉토리를 검증합니다.

    Returns:
        환경 준비 완료 여부
    """
    errors = []

    # .env 파일 확인
    if not Path(".env").exists():
        errors.append(".env 파일이 존재하지 않습니다. (.env.template 참고)")

    # 필수 환경변수 확인
    required_vars = ["CONFLUENCE_BASE_URL", "CONFLUENCE_USERNAME", "CONFLUENCE_PASSWORD", "ROOT_PAGE_URL"]
    for var in required_vars:
        if not os.getenv(var):
            errors.append(f"환경변수 미설정: {var}")

    # Ollama 서버 확인
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    try:
        resp = requests.get(f"{ollama_host}/api/tags", timeout=5)
        if resp.status_code == 200:
            logger.info(f"Ollama 서버 정상: {ollama_host}")
        else:
            errors.append(f"Ollama 서버 응답 이상: {resp.status_code}")
    except requests.ConnectionError:
        errors.append(f"Ollama 서버에 연결할 수 없습니다: {ollama_host}")
    except Exception as e:
        errors.append(f"Ollama 서버 확인 실패: {e}")

    # 필요 디렉토리 생성
    for d in [LOGS_DIR, BACKUP_DIR, Path("confluence_pages")]:
        d.mkdir(exist_ok=True)

    if errors:
        for err in errors:
            logger.error(err)
        return False

    logger.info("환경 확인 완료")
    return True


def step_crawl(full: bool, logger: logging.Logger) -> bool:
    """2단계: Confluence 크롤링

    Args:
        full: 전체 크롤링 여부
        logger: 로거

    Returns:
        성공 여부
    """
    from confluence_crawler import ConfluenceCrawler

    crawl_type = "전체" if full else "증분"
    logger.info(f"{crawl_type} 크롤링 시작")

    try:
        crawler = ConfluenceCrawler(full_crawl=full)
        crawler.run()

        logger.info(
            f"크롤링 완료 - "
            f"추가: {crawler.stats['added']}, "
            f"수정: {crawler.stats['modified']}, "
            f"삭제: {crawler.stats['deleted']}, "
            f"건너뜀: {crawler.stats['skipped']}"
        )
        return True

    except Exception as e:
        logger.error(f"크롤링 실패: {e}")
        return False


def step_check_changes(logger: logging.Logger) -> bool:
    """3단계: 변경사항 확인

    크롤링 결과에 변경된 페이지가 있는지 확인합니다.

    Returns:
        변경사항 존재 여부
    """
    if not BACKUP_JSON.exists():
        logger.warning("백업 파일이 없습니다. 크롤링이 실패했을 수 있습니다.")
        return False

    try:
        with open(BACKUP_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        page_count = len(data.get("pages", []))

        if page_count == 0:
            logger.info("변경된 페이지가 없습니다.")
            return False

        logger.info(f"변경된 페이지: {page_count}개")
        return True

    except Exception as e:
        logger.error(f"변경사항 확인 실패: {e}")
        return False


def step_preprocess(logger: logging.Logger) -> bool:
    """4단계: 데이터 전처리

    Returns:
        성공 여부
    """
    from preprocess_data import load_backup_data, split_into_chunks, save_processed_chunks

    logger.info("데이터 전처리 시작")

    try:
        pages = load_backup_data(str(BACKUP_JSON))
        chunks = split_into_chunks(pages)
        save_processed_chunks(chunks, str(PROCESSED_JSON))
        logger.info(f"전처리 완료 - {len(pages)}개 페이지 → {len(chunks)}개 청크")
        return True

    except Exception as e:
        logger.error(f"전처리 실패: {e}")
        return False


def step_vectorize(full: bool, logger: logging.Logger) -> bool:
    """5단계: 벡터 DB 업데이트

    Args:
        full: 전체 재구축 여부
        logger: 로거

    Returns:
        성공 여부
    """
    if full:
        from build_vectordb import build_vectordb, verify_vectordb
        logger.info("벡터 DB 전체 재구축 시작")

        try:
            result = build_vectordb(rebuild=True)
            if result:
                verify_vectordb()
                logger.info(f"벡터 DB 재구축 완료 - {result['total_vectors']}개 벡터")
            return True

        except Exception as e:
            logger.error(f"벡터 DB 재구축 실패: {e}")
            return False
    else:
        from update_vectordb import update_process
        logger.info("벡터 DB 증분 업데이트 시작")

        try:
            result = update_process()
            if result:
                logger.info(
                    f"증분 업데이트 완료 - "
                    f"삭제: {result['deleted_vectors']}, "
                    f"추가: {result['added_vectors']}, "
                    f"총: {result['final_total']}"
                )
            return True

        except Exception as e:
            logger.error(f"벡터 DB 증분 업데이트 실패: {e}")
            return False


# ============================================
# 통합 파이프라인
# ============================================

STEPS = [
    {"name": "환경 확인", "icon": "🔧"},
    {"name": "크롤링", "icon": "🕷️"},
    {"name": "변경사항 확인", "icon": "🔍"},
    {"name": "전처리", "icon": "⚙️"},
    {"name": "벡터 업데이트", "icon": "📦"},
    {"name": "완료", "icon": "✅"},
]


@click.command()
@click.option("--full", is_flag=True, default=False, help="전체 재구축 (크롤링 + 벡터 DB)")
@click.option("--skip-crawl", is_flag=True, default=False, help="크롤링 건너뛰기")
@click.option("--skip-vectorize", is_flag=True, default=False, help="벡터화 건너뛰기")
def main(full: bool, skip_crawl: bool, skip_vectorize: bool):
    """Confluence RAG 주간 업데이트

    크롤링 → 전처리 → 벡터 DB 업데이트 파이프라인을 실행합니다.

    \b
    사용 예시:
        python weekly_update.py              # 증분 업데이트
        python weekly_update.py --full       # 전체 재구축
        python weekly_update.py --skip-crawl # 크롤링 건너뛰기
    """
    start_time = time.time()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "전체 재구축" if full else "증분 업데이트"

    # 로그 디렉토리 생성
    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f"update_{timestamp}.log"

    # 로거 설정
    logger = _setup_logger(log_path)

    # --- 헤더 출력 ---
    console.print()
    console.print(Panel(
        f"[bold]모드:[/bold] {mode}\n"
        f"[bold]시작:[/bold] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"[bold]로그:[/bold] {log_path}",
        title="[bold magenta]🚀 Confluence RAG 주간 업데이트[/bold magenta]",
        border_style="magenta",
    ))
    console.print()

    logger.info(f"=== 주간 업데이트 시작 ({mode}) ===")

    # 롤백용 백업 생성
    backup_info = _create_backup(logger)
    current_step = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}[/bold blue]"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:

        task = progress.add_task("업데이트 진행 중...", total=len(STEPS))

        try:
            # --- 1단계: 환경 확인 ---
            current_step = 0
            progress.update(task, description=f"{STEPS[0]['icon']} {STEPS[0]['name']}")

            if not step_check_environment(logger):
                console.print("[red]환경 확인 실패. 업데이트를 중단합니다.[/red]")
                logger.error("환경 확인 실패로 업데이트 중단")
                return

            progress.advance(task)

            # --- 2단계: 크롤링 ---
            current_step = 1
            progress.update(task, description=f"{STEPS[1]['icon']} {STEPS[1]['name']}")

            if skip_crawl:
                logger.info("크롤링 건너뛰기 (--skip-crawl)")
                console.print("[yellow]크롤링 건너뜀[/yellow]")
            else:
                if not step_crawl(full, logger):
                    raise RuntimeError("크롤링 실패")

            progress.advance(task)

            # --- 3단계: 변경사항 확인 ---
            current_step = 2
            progress.update(task, description=f"{STEPS[2]['icon']} {STEPS[2]['name']}")

            if not skip_crawl and not step_check_changes(logger):
                console.print("\n[green]변경된 페이지가 없습니다. 업데이트를 종료합니다.[/green]")
                logger.info("변경사항 없음 - 업데이트 종료")
                progress.update(task, completed=len(STEPS))
                _print_summary(start_time, logger, skipped=True)
                return

            progress.advance(task)

            # --- 4단계: 전처리 ---
            current_step = 3
            progress.update(task, description=f"{STEPS[3]['icon']} {STEPS[3]['name']}")

            if not step_preprocess(logger):
                raise RuntimeError("전처리 실패")

            progress.advance(task)

            # --- 5단계: 벡터 업데이트 ---
            current_step = 4
            progress.update(task, description=f"{STEPS[4]['icon']} {STEPS[4]['name']}")

            if skip_vectorize:
                logger.info("벡터화 건너뛰기 (--skip-vectorize)")
                console.print("[yellow]벡터화 건너뜀[/yellow]")
            else:
                if not step_vectorize(full, logger):
                    raise RuntimeError("벡터 DB 업데이트 실패")

            progress.advance(task)

            # --- 6단계: 완료 ---
            progress.update(task, description=f"{STEPS[5]['icon']} {STEPS[5]['name']}")
            progress.advance(task)

            logger.info("=== 주간 업데이트 정상 완료 ===")

        except RuntimeError as e:
            logger.error(f"파이프라인 실패 (단계 {current_step + 1}: {STEPS[current_step]['name']}): {e}")
            console.print(f"\n[red]❌ 실패: {STEPS[current_step]['name']}[/red]")
            _rollback(backup_info, logger)
            _print_summary(start_time, logger, failed_step=STEPS[current_step]["name"])
            return

        except KeyboardInterrupt:
            logger.warning("사용자에 의해 중단됨")
            console.print("\n[yellow]사용자에 의해 중단되었습니다.[/yellow]")
            _rollback(backup_info, logger)
            return

        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}", exc_info=True)
            console.print(f"\n[red]❌ 예상치 못한 오류: {e}[/red]")
            _rollback(backup_info, logger)
            _print_summary(start_time, logger, failed_step="알 수 없음")
            return

    # 결과 요약
    _print_summary(start_time, logger)
    console.print(f"\n[dim]로그 파일: {log_path}[/dim]\n")


def _print_summary(
    start_time: float,
    logger: logging.Logger,
    skipped: bool = False,
    failed_step: str = None,
):
    """업데이트 결과 요약 출력

    Args:
        start_time: 시작 시간
        logger: 로거
        skipped: 변경사항 없어서 건너뛴 경우
        failed_step: 실패한 단계명 (없으면 성공)
    """
    elapsed = time.time() - start_time
    minutes, seconds = divmod(int(elapsed), 60)

    table = Table(title="업데이트 결과 요약")
    table.add_column("항목", style="cyan")
    table.add_column("값", justify="right", style="bold")

    # 상태
    if failed_step:
        table.add_row("상태", f"[red]실패 ({failed_step})[/red]")
    elif skipped:
        table.add_row("상태", "[yellow]변경사항 없음[/yellow]")
    else:
        table.add_row("상태", "[green]성공[/green]")

    table.add_row("소요 시간", f"{minutes}분 {seconds}초")

    # 크롤링 통계 (백업 파일에서)
    if BACKUP_JSON.exists():
        try:
            with open(BACKUP_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            table.add_row("크롤링된 페이지", str(len(data.get("pages", []))))
        except Exception:
            pass

    # 청크 통계
    if PROCESSED_JSON.exists():
        try:
            with open(PROCESSED_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            table.add_row("생성된 청크", str(data.get("total_chunks", 0)))
        except Exception:
            pass

    # 벡터 DB 통계
    if VECTORDB_DIR.exists():
        try:
            from chromadb import PersistentClient
            from chromadb.config import Settings
            client = PersistentClient(
                path=str(VECTORDB_DIR),
                settings=Settings(anonymized_telemetry=False),
            )
            collection = client.get_collection(name="confluence_pages")
            table.add_row("벡터 DB 총 벡터", f"{collection.count():,}")
        except Exception:
            pass

        # DB 크기
        db_size = sum(f.stat().st_size for f in VECTORDB_DIR.rglob("*") if f.is_file())
        if db_size >= 1024 * 1024:
            table.add_row("벡터 DB 크기", f"{db_size / (1024 * 1024):.1f} MB")
        else:
            table.add_row("벡터 DB 크기", f"{db_size / 1024:.1f} KB")

    console.print()
    console.print(table)

    # 로거에도 기록
    status = "실패" if failed_step else ("건너뜀" if skipped else "성공")
    logger.info(f"결과: {status} / 소요 시간: {minutes}분 {seconds}초")


if __name__ == "__main__":
    main()
