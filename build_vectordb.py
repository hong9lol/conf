"""
벡터 DB 구축 스크립트

전처리된 청크 데이터를 한국어 특화 임베딩 모델로 벡터화하고
ChromaDB에 저장합니다. 배치 처리와 중단 시 재개 기능을 지원합니다.
"""

import json
import shutil
import time
from pathlib import Path

import click
import torch
from chromadb import PersistentClient
from chromadb.config import Settings
from langchain_community.embeddings import HuggingFaceEmbeddings
from rich.console import Console
from rich.table import Table
from tqdm import tqdm

console = Console()

# 기본 설정
DEFAULT_MODEL = "jhgan/ko-sroberta-multitask"
DEFAULT_PERSIST_DIR = "./confluence_vectordb"
DEFAULT_COLLECTION = "confluence_pages"
PROGRESS_FILE = Path(".vectordb_progress.json")


def load_embedding_model(model_name: str = DEFAULT_MODEL) -> HuggingFaceEmbeddings:
    """한국어 특화 임베딩 모델 로드

    GPU가 사용 가능하면 CUDA를, 아니면 CPU를 사용합니다.
    CUDA OOM 발생 시 자동으로 CPU로 전환합니다.

    Args:
        model_name: HuggingFace 모델명

    Returns:
        HuggingFaceEmbeddings 인스턴스
    """
    # 디바이스 자동 감지
    device = "cuda" if torch.cuda.is_available() else "cpu"
    console.print(f"[blue]임베딩 모델 로드 중: {model_name}[/blue]")
    console.print(f"[dim]디바이스: {device}[/dim]")

    try:
        embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True},
        )

        # 테스트 임베딩으로 동작 확인
        embeddings.embed_query("테스트")
        console.print("[green]임베딩 모델 로드 완료[/green]")
        return embeddings

    except torch.cuda.OutOfMemoryError:
        # CUDA 메모리 부족 시 CPU로 전환
        console.print("[yellow]GPU 메모리 부족 - CPU로 전환합니다.[/yellow]")
        torch.cuda.empty_cache()

        embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        console.print("[green]임베딩 모델 로드 완료 (CPU)[/green]")
        return embeddings


def _load_chunks(input_path: str) -> list[dict]:
    """전처리된 청크 데이터 로드

    Args:
        input_path: processed_chunks.json 경로

    Returns:
        청크 리스트
    """
    path = Path(input_path)
    if not path.exists():
        console.print(f"[red]오류: 파일을 찾을 수 없습니다: {input_path}[/red]")
        console.print("[yellow]먼저 preprocess_data.py를 실행해주세요.[/yellow]")
        raise FileNotFoundError(f"파일 없음: {input_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    chunks = data.get("chunks", [])
    console.print(f"[green]{len(chunks)}개 청크 로드 완료[/green]")
    return chunks


def _load_progress() -> int:
    """중단된 진행 상황 로드

    Returns:
        마지막으로 처리 완료된 배치 인덱스 (없으면 0)
    """
    if PROGRESS_FILE.exists():
        try:
            data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            last_batch = data.get("last_completed_batch", 0)
            console.print(f"[yellow]이전 진행 상황 발견: 배치 {last_batch}까지 완료[/yellow]")
            return last_batch
        except (json.JSONDecodeError, IOError):
            pass
    return 0


def _save_progress(batch_index: int):
    """진행 상황 저장

    Args:
        batch_index: 완료된 배치 인덱스
    """
    PROGRESS_FILE.write_text(
        json.dumps({"last_completed_batch": batch_index}),
        encoding="utf-8",
    )


def _clear_progress():
    """진행 상황 파일 삭제"""
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()


def build_vectordb(
    input_path: str = "processed_chunks.json",
    persist_dir: str = DEFAULT_PERSIST_DIR,
    batch_size: int = 100,
    rebuild: bool = False,
):
    """벡터 DB 구축

    전처리된 청크를 임베딩하여 ChromaDB에 저장합니다.
    배치 단위로 처리하며, 중단 시 이어서 재개할 수 있습니다.

    Args:
        input_path: 전처리된 청크 JSON 경로
        persist_dir: ChromaDB 저장 디렉토리
        batch_size: 한 번에 처리할 청크 수
        rebuild: True면 기존 DB 삭제 후 재구축
    """
    start_time = time.time()

    # 기존 DB 삭제 (rebuild 모드)
    if rebuild and Path(persist_dir).exists():
        console.print("[yellow]기존 벡터 DB를 삭제합니다...[/yellow]")
        shutil.rmtree(persist_dir)
        _clear_progress()

    # 청크 데이터 로드
    chunks = _load_chunks(input_path)
    if not chunks:
        console.print("[yellow]처리할 청크가 없습니다.[/yellow]")
        return

    # 임베딩 모델 로드
    embeddings = load_embedding_model()

    # ChromaDB 클라이언트 초기화
    console.print(f"[blue]ChromaDB 초기화: {persist_dir}[/blue]")
    client = PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )

    # 컬렉션 생성 또는 가져오기
    collection = client.get_or_create_collection(
        name=DEFAULT_COLLECTION,
        metadata={"description": "Confluence 페이지 벡터 저장소"},
    )

    # 중단 지점부터 재개
    start_batch = _load_progress()
    start_index = start_batch * batch_size

    if start_index > 0:
        console.print(f"[yellow]배치 {start_batch}부터 재개합니다 (청크 #{start_index}~)[/yellow]")

    # 배치 단위 처리
    total_batches = (len(chunks) - start_index + batch_size - 1) // batch_size
    processed = 0

    console.print(f"\n[bold]벡터 임베딩 시작 (배치 크기: {batch_size})[/bold]")

    for batch_idx in tqdm(range(total_batches), desc="벡터 임베딩"):
        actual_batch_num = start_batch + batch_idx
        batch_start = start_index + (batch_idx * batch_size)
        batch_end = min(batch_start + batch_size, len(chunks))
        batch = chunks[batch_start:batch_end]

        # 텍스트와 메타데이터 분리
        texts = [chunk["content"] for chunk in batch]
        metadatas = [chunk["metadata"] for chunk in batch]
        ids = [
            f"{meta['page_id']}_chunk_{meta['chunk_index']}"
            for meta in metadatas
        ]

        try:
            # 임베딩 생성
            vectors = embeddings.embed_documents(texts)

            # ChromaDB에 upsert (중복 방지)
            collection.upsert(
                ids=ids,
                embeddings=vectors,
                documents=texts,
                metadatas=metadatas,
            )

            processed += len(batch)

            # 진행 상황 저장
            _save_progress(actual_batch_num + 1)

        except torch.cuda.OutOfMemoryError:
            # CUDA OOM 발생 시 CPU로 전환 후 재시도
            console.print("\n[yellow]GPU 메모리 부족 - CPU로 전환하여 재시도[/yellow]")
            torch.cuda.empty_cache()
            embeddings = load_embedding_model()

            vectors = embeddings.embed_documents(texts)
            collection.upsert(
                ids=ids,
                embeddings=vectors,
                documents=texts,
                metadatas=metadatas,
            )

            processed += len(batch)
            _save_progress(actual_batch_num + 1)

    # 완료 후 진행 파일 정리
    _clear_progress()

    elapsed = time.time() - start_time
    console.print(f"\n[green]벡터 DB 구축 완료! ({processed}개 청크 처리)[/green]")

    return {
        "processed_chunks": processed,
        "total_vectors": collection.count(),
        "elapsed_seconds": elapsed,
        "persist_dir": persist_dir,
    }


def verify_vectordb(persist_dir: str = DEFAULT_PERSIST_DIR):
    """생성된 벡터 DB 검증

    DB가 정상적으로 생성되었는지 확인하고
    샘플 쿼리로 검색 테스트를 수행합니다.

    Args:
        persist_dir: ChromaDB 저장 디렉토리

    Returns:
        검증 결과 딕셔너리
    """
    console.print("\n[blue]벡터 DB 검증 중...[/blue]")

    if not Path(persist_dir).exists():
        console.print("[red]오류: 벡터 DB 디렉토리가 존재하지 않습니다.[/red]")
        return None

    client = PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )

    collection = client.get_collection(name=DEFAULT_COLLECTION)
    total_count = collection.count()

    console.print(f"  컬렉션: {DEFAULT_COLLECTION}")
    console.print(f"  총 벡터 수: {total_count}")

    # 샘플 검색 테스트
    if total_count > 0:
        embeddings = load_embedding_model()
        test_query = "사용 방법"
        query_vector = embeddings.embed_query(test_query)

        results = collection.query(
            query_embeddings=[query_vector],
            n_results=min(3, total_count),
        )

        console.print(f"\n  [dim]테스트 쿼리: \"{test_query}\"[/dim]")
        for i, doc in enumerate(results["documents"][0]):
            title = results["metadatas"][0][i].get("title", "")
            preview = doc[:80].replace("\n", " ")
            console.print(f"  [dim]  #{i + 1} [{title}] {preview}...[/dim]")

        console.print("\n[green]검증 완료: 정상[/green]")
    else:
        console.print("[yellow]경고: 벡터 DB가 비어 있습니다.[/yellow]")

    return {"total_vectors": total_count}


def print_statistics(result: dict):
    """벡터 DB 구축 결과 통계 출력

    Args:
        result: build_vectordb 반환값
    """
    if not result:
        return

    elapsed = result["elapsed_seconds"]
    minutes, seconds = divmod(int(elapsed), 60)

    # DB 디렉토리 크기 계산
    persist_path = Path(result["persist_dir"])
    db_size_bytes = sum(f.stat().st_size for f in persist_path.rglob("*") if f.is_file())
    if db_size_bytes >= 1024 * 1024:
        db_size_str = f"{db_size_bytes / (1024 * 1024):.1f} MB"
    else:
        db_size_str = f"{db_size_bytes / 1024:.1f} KB"

    table = Table(title="벡터 DB 구축 결과")
    table.add_column("항목", style="cyan")
    table.add_column("값", justify="right", style="bold")

    table.add_row("처리된 청크 수", f"{result['processed_chunks']:,}")
    table.add_row("생성된 벡터 수", f"{result['total_vectors']:,}")
    table.add_row("소요 시간", f"{minutes}분 {seconds}초")
    table.add_row("DB 크기", db_size_str)
    table.add_row("저장 경로", result["persist_dir"])

    console.print()
    console.print(table)


# ============================================
# CLI 진입점
# ============================================
@click.command()
@click.option(
    "--input", "input_path",
    default="processed_chunks.json",
    help="입력 파일 경로 (기본값: processed_chunks.json)",
)
@click.option(
    "--persist-dir",
    default=DEFAULT_PERSIST_DIR,
    help=f"ChromaDB 저장 경로 (기본값: {DEFAULT_PERSIST_DIR})",
)
@click.option(
    "--batch-size",
    default=100,
    type=int,
    help="배치 크기 (기본값: 100)",
)
@click.option(
    "--rebuild",
    is_flag=True,
    default=False,
    help="기존 DB 삭제 후 재구축",
)
def main(input_path: str, persist_dir: str, batch_size: int, rebuild: bool):
    """벡터 DB 구축

    전처리된 청크 데이터를 한국어 특화 임베딩 모델로 벡터화하고
    ChromaDB에 저장합니다.

    \b
    사용 예시:
        python build_vectordb.py
        python build_vectordb.py --rebuild
        python build_vectordb.py --batch-size 50
    """
    console.print("\n[bold magenta]===== 벡터 DB 구축 시작 =====[/bold magenta]\n")

    # 벡터 DB 구축
    result = build_vectordb(
        input_path=input_path,
        persist_dir=persist_dir,
        batch_size=batch_size,
        rebuild=rebuild,
    )

    if result:
        # 통계 출력
        print_statistics(result)

        # DB 검증
        verify_vectordb(persist_dir)

    console.print(f"\n[bold magenta]===== 벡터 DB 구축 완료 =====[/bold magenta]\n")


if __name__ == "__main__":
    main()
