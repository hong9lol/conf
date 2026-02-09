"""
벡터 DB 증분 업데이트 스크립트

마지막 동기화 이후 변경된 페이지만 식별하여
벡터 DB를 효율적으로 업데이트합니다.
수정된 페이지의 기존 벡터를 삭제하고 새 벡터를 추가합니다.
"""

import json
import time
from pathlib import Path

import click
from chromadb import PersistentClient
from chromadb.config import Settings
from rich.console import Console
from rich.table import Table
from tqdm import tqdm

from build_vectordb import (
    DEFAULT_COLLECTION,
    DEFAULT_PERSIST_DIR,
    load_embedding_model,
)
from preprocess_data import split_into_chunks
from sync_state import load_sync_state

console = Console()


def load_vectordb(persist_dir: str = DEFAULT_PERSIST_DIR):
    """기존 ChromaDB 로드

    Args:
        persist_dir: ChromaDB 저장 디렉토리

    Returns:
        (client, collection) 튜플

    Raises:
        FileNotFoundError: DB 디렉토리가 없을 때
    """
    if not Path(persist_dir).exists():
        console.print(f"[red]오류: 벡터 DB가 존재하지 않습니다: {persist_dir}[/red]")
        console.print("[yellow]먼저 build_vectordb.py를 실행해주세요.[/yellow]")
        raise FileNotFoundError(f"벡터 DB 없음: {persist_dir}")

    client = PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )

    collection = client.get_collection(name=DEFAULT_COLLECTION)
    console.print(f"[green]벡터 DB 로드 완료 (벡터 {collection.count():,}개)[/green]")

    return client, collection


def identify_changes(backup_path: str = "confluence_backup.json") -> dict:
    """변경사항 파악

    confluence_backup.json의 페이지 정보와 last_sync.json을 비교하여
    추가/수정/삭제된 페이지를 식별합니다.

    Args:
        backup_path: 크롤링 백업 JSON 경로

    Returns:
        {
            'added': [새로 추가된 페이지 리스트],
            'modified': [수정된 페이지 리스트],
            'deleted': [삭제된 페이지 ID 리스트]
        }
    """
    # 최신 백업 데이터 로드
    path = Path(backup_path)
    if not path.exists():
        console.print(f"[red]오류: 백업 파일 없음: {backup_path}[/red]")
        raise FileNotFoundError(f"파일 없음: {backup_path}")

    with open(path, "r", encoding="utf-8") as f:
        backup_data = json.load(f)

    backup_pages = backup_data.get("pages", [])

    # 동기화 상태 로드
    sync_state = load_sync_state()
    synced_pages = sync_state.get("pages", {})

    # 백업의 페이지 ID 집합
    backup_page_ids = {p.get("page_id", "") for p in backup_pages}
    # 동기화 상태의 페이지 ID 집합
    synced_page_ids = set(synced_pages.keys())

    changes = {
        "added": [],     # 신규 페이지
        "modified": [],  # 수정된 페이지
        "deleted": [],   # 삭제된 페이지 ID
    }

    # 추가/수정 판별
    for page in backup_pages:
        page_id = page.get("page_id", "")
        if not page_id:
            continue

        if page_id not in synced_page_ids:
            # 동기화 상태에 없으면 신규
            changes["added"].append(page)
        else:
            # 버전 또는 수정일 비교
            prev = synced_pages[page_id]
            current_version = page.get("version", 0)
            prev_version = prev.get("version", 0)
            current_modified = page.get("last_modified", "")
            prev_modified = prev.get("last_modified", "")

            if (current_version > 0 and prev_version > 0 and current_version != prev_version) or \
               (current_modified and prev_modified and current_modified != prev_modified):
                changes["modified"].append(page)

    # 삭제 판별: 동기화 상태에는 있지만 백업에는 없는 페이지
    deleted_ids = synced_page_ids - backup_page_ids
    changes["deleted"] = list(deleted_ids)

    # 결과 출력
    console.print(f"\n[bold]변경사항 분석 결과:[/bold]")
    console.print(f"  신규 추가: [green]{len(changes['added'])}[/green]개")
    console.print(f"  수정됨:    [yellow]{len(changes['modified'])}[/yellow]개")
    console.print(f"  삭제됨:    [red]{len(changes['deleted'])}[/red]개")

    return changes


def delete_old_vectors(collection, page_ids: list[str]) -> int:
    """페이지 ID 기준으로 기존 벡터 삭제

    수정 또는 삭제된 페이지의 모든 청크 벡터를 제거합니다.

    Args:
        collection: ChromaDB 컬렉션
        page_ids: 삭제할 페이지 ID 리스트

    Returns:
        삭제된 벡터 수
    """
    if not page_ids:
        return 0

    deleted_count = 0

    for page_id in tqdm(page_ids, desc="기존 벡터 삭제"):
        # page_id로 시작하는 모든 청크 ID 조회
        results = collection.get(
            where={"page_id": page_id},
        )

        if results and results["ids"]:
            collection.delete(ids=results["ids"])
            deleted_count += len(results["ids"])

    console.print(f"[yellow]{deleted_count}개 벡터 삭제 완료[/yellow]")
    return deleted_count


def add_new_vectors(
    collection,
    pages: list[dict],
    embeddings,
    batch_size: int = 100,
) -> int:
    """새로운/수정된 페이지의 청크 벡터 추가

    페이지를 청크로 분할하고 벡터화하여 DB에 추가합니다.

    Args:
        collection: ChromaDB 컬렉션
        pages: 추가할 페이지 데이터 리스트
        embeddings: 임베딩 모델
        batch_size: 배치 크기

    Returns:
        추가된 벡터 수
    """
    if not pages:
        return 0

    # 페이지를 청크로 분할
    console.print("[blue]청크 분할 중...[/blue]")
    chunks = split_into_chunks(pages)

    if not chunks:
        console.print("[yellow]추가할 청크가 없습니다.[/yellow]")
        return 0

    # 배치 단위 임베딩 및 저장
    added_count = 0
    total_batches = (len(chunks) + batch_size - 1) // batch_size

    for i in tqdm(range(total_batches), desc="벡터 추가"):
        batch_start = i * batch_size
        batch_end = min(batch_start + batch_size, len(chunks))
        batch = chunks[batch_start:batch_end]

        texts = [chunk["content"] for chunk in batch]
        metadatas = [chunk["metadata"] for chunk in batch]
        ids = [
            f"{meta['page_id']}_chunk_{meta['chunk_index']}"
            for meta in metadatas
        ]

        # 임베딩 생성
        vectors = embeddings.embed_documents(texts)

        # ChromaDB에 upsert
        collection.upsert(
            ids=ids,
            embeddings=vectors,
            documents=texts,
            metadatas=metadatas,
        )

        added_count += len(batch)

    console.print(f"[green]{added_count}개 벡터 추가 완료[/green]")
    return added_count


def update_process(
    persist_dir: str = DEFAULT_PERSIST_DIR,
    backup_path: str = "confluence_backup.json",
    batch_size: int = 100,
    force: bool = False,
):
    """전체 증분 업데이트 프로세스

    1. 변경사항 식별
    2. 수정/삭제된 페이지의 기존 벡터 삭제
    3. 신규/수정된 페이지의 새 벡터 추가

    Args:
        persist_dir: ChromaDB 저장 경로
        backup_path: 크롤링 백업 JSON 경로
        batch_size: 배치 크기
        force: 변경사항 없어도 강제 업데이트

    Returns:
        업데이트 결과 딕셔너리
    """
    start_time = time.time()

    # 1. 기존 벡터 DB 로드
    client, collection = load_vectordb(persist_dir)
    initial_count = collection.count()

    # 2. 변경사항 파악
    changes = identify_changes(backup_path)

    total_changes = len(changes["added"]) + len(changes["modified"]) + len(changes["deleted"])

    if total_changes == 0 and not force:
        console.print("\n[green]변경사항이 없습니다. 업데이트를 건너뜁니다.[/green]")
        console.print("[dim]강제 업데이트: --force 옵션 사용[/dim]")
        return {
            "deleted_vectors": 0,
            "added_vectors": 0,
            "final_total": initial_count,
            "elapsed_seconds": time.time() - start_time,
        }

    # 3. 임베딩 모델 로드
    embeddings = load_embedding_model()

    # 4. 수정/삭제된 페이지의 기존 벡터 삭제
    delete_page_ids = [p.get("page_id", "") for p in changes["modified"]]
    delete_page_ids.extend(changes["deleted"])
    delete_page_ids = [pid for pid in delete_page_ids if pid]  # 빈 값 제거

    console.print(f"\n[bold]기존 벡터 삭제 중...[/bold]")
    deleted_count = delete_old_vectors(collection, delete_page_ids)

    # 5. 신규/수정된 페이지의 새 벡터 추가
    pages_to_add = changes["added"] + changes["modified"]

    console.print(f"\n[bold]새 벡터 추가 중...[/bold]")
    added_count = add_new_vectors(collection, pages_to_add, embeddings, batch_size)

    elapsed = time.time() - start_time
    final_count = collection.count()

    result = {
        "deleted_vectors": deleted_count,
        "added_vectors": added_count,
        "final_total": final_count,
        "elapsed_seconds": elapsed,
        "changes": {
            "pages_added": len(changes["added"]),
            "pages_modified": len(changes["modified"]),
            "pages_deleted": len(changes["deleted"]),
        },
    }

    # 결과 통계 출력
    _print_statistics(result, initial_count)

    return result


def _print_statistics(result: dict, initial_count: int):
    """업데이트 결과 통계 출력

    Args:
        result: update_process 반환값
        initial_count: 업데이트 전 벡터 수
    """
    elapsed = result["elapsed_seconds"]
    minutes, seconds = divmod(int(elapsed), 60)

    table = Table(title="증분 업데이트 결과")
    table.add_column("항목", style="cyan")
    table.add_column("값", justify="right", style="bold")

    changes = result["changes"]
    table.add_row("추가된 페이지", str(changes["pages_added"]))
    table.add_row("수정된 페이지", str(changes["pages_modified"]))
    table.add_row("삭제된 페이지", str(changes["pages_deleted"]))
    table.add_row("─" * 20, "─" * 10)
    table.add_row("삭제된 벡터 수", f"{result['deleted_vectors']:,}")
    table.add_row("추가된 벡터 수", f"{result['added_vectors']:,}")
    table.add_row("─" * 20, "─" * 10)
    table.add_row("업데이트 전 벡터", f"{initial_count:,}")
    table.add_row("업데이트 후 벡터", f"{result['final_total']:,}")
    table.add_row("변동량", f"{result['final_total'] - initial_count:+,}")
    table.add_row("─" * 20, "─" * 10)
    table.add_row("소요 시간", f"{minutes}분 {seconds}초")

    console.print()
    console.print(table)


# ============================================
# CLI 진입점
# ============================================
@click.command()
@click.option(
    "--persist-dir",
    default=DEFAULT_PERSIST_DIR,
    help=f"ChromaDB 저장 경로 (기본값: {DEFAULT_PERSIST_DIR})",
)
@click.option(
    "--backup-path",
    default="confluence_backup.json",
    help="크롤링 백업 파일 경로 (기본값: confluence_backup.json)",
)
@click.option(
    "--batch-size",
    default=100,
    type=int,
    help="배치 크기 (기본값: 100)",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="변경사항 없어도 강제 업데이트",
)
def main(persist_dir: str, backup_path: str, batch_size: int, force: bool):
    """벡터 DB 증분 업데이트

    마지막 동기화 이후 변경된 페이지만 식별하여
    벡터 DB를 효율적으로 업데이트합니다.

    \b
    사용 예시:
        python update_vectordb.py
        python update_vectordb.py --force
        python update_vectordb.py --batch-size 50
    """
    console.print("\n[bold magenta]===== 벡터 DB 증분 업데이트 시작 =====[/bold magenta]\n")

    update_process(
        persist_dir=persist_dir,
        backup_path=backup_path,
        batch_size=batch_size,
        force=force,
    )

    console.print(f"\n[bold magenta]===== 증분 업데이트 완료 =====[/bold magenta]\n")


if __name__ == "__main__":
    main()
