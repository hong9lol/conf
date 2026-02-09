"""
데이터 전처리 스크립트

크롤링된 Confluence 데이터를 RAG 시스템에 적합한 형태로 전처리합니다.
문서를 청크 단위로 분할하고 메타데이터를 추가하여 벡터 임베딩에 사용할 수 있도록 합니다.
"""

import json
from pathlib import Path

import click
from langchain.text_splitter import RecursiveCharacterTextSplitter
from rich.console import Console
from rich.table import Table
from tqdm import tqdm

console = Console()

# 한국어 문장 분할에 적합한 구분자 목록 (우선순위 순)
KOREAN_SEPARATORS = [
    "\n\n",   # 단락 구분
    "\n",     # 줄바꿈
    "。",     # 일본어식 마침표 (간혹 사용)
    ". ",     # 영문 마침표
    "다. ",   # 한국어 종결어미
    "요. ",   # 한국어 종결어미
    "죠. ",   # 한국어 종결어미
    "함. ",   # 한국어 종결어미
    "음. ",   # 한국어 종결어미
    "됨. ",   # 한국어 종결어미
    "임. ",   # 한국어 종결어미
    "!  ",    # 느낌표
    "? ",     # 물음표
    "; ",     # 세미콜론
    ", ",     # 쉼표
    " ",      # 공백
    "",       # 문자 단위 (최후 수단)
]


def load_backup_data(input_path: str) -> list[dict]:
    """크롤링 백업 데이터 로드

    confluence_backup.json 파일을 읽어 페이지 목록을 반환합니다.

    Args:
        input_path: 백업 JSON 파일 경로

    Returns:
        페이지 데이터 리스트

    Raises:
        FileNotFoundError: 파일이 존재하지 않을 때
        json.JSONDecodeError: JSON 파싱 실패 시
    """
    path = Path(input_path)

    if not path.exists():
        console.print(f"[red]오류: 파일을 찾을 수 없습니다: {input_path}[/red]")
        console.print("[yellow]먼저 confluence_crawler.py를 실행해주세요.[/yellow]")
        raise FileNotFoundError(f"파일 없음: {input_path}")

    console.print(f"[blue]데이터 로드 중: {input_path}[/blue]")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pages = data.get("pages", [])
    console.print(f"[green]{len(pages)}개 페이지 로드 완료[/green]")

    return pages


def split_into_chunks(
    pages: list[dict],
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[dict]:
    """페이지 콘텐츠를 청크 단위로 분할

    RecursiveCharacterTextSplitter를 사용하여 한국어 문장 단위로
    우선 분할하고, 각 청크에 메타데이터를 추가합니다.

    Args:
        pages: 페이지 데이터 리스트
        chunk_size: 청크 최대 글자 수
        chunk_overlap: 청크 간 겹치는 글자 수

    Returns:
        메타데이터가 포함된 청크 리스트
    """
    # 한국어 문장 단위 분할기 설정
    text_splitter = RecursiveCharacterTextSplitter(
        separators=KOREAN_SEPARATORS,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
    )

    all_chunks = []

    for page in tqdm(pages, desc="청크 분할 중"):
        content = page.get("content", "")

        # 빈 콘텐츠 건너뛰기
        if not content.strip():
            continue

        # 텍스트 분할
        chunks = text_splitter.split_text(content)

        # 각 청크에 메타데이터 추가
        page_chunks = add_metadata(
            chunks=chunks,
            page_id=page.get("page_id", ""),
            title=page.get("title", ""),
            url=page.get("url", ""),
        )

        all_chunks.extend(page_chunks)

    return all_chunks


def add_metadata(
    chunks: list[str],
    page_id: str,
    title: str,
    url: str,
) -> list[dict]:
    """각 청크에 메타데이터 추가

    검색 및 참조 추적을 위한 메타데이터를 청크에 부착합니다.

    Args:
        chunks: 분할된 텍스트 리스트
        page_id: 원본 페이지 ID
        title: 원본 페이지 제목
        url: 원본 페이지 URL

    Returns:
        메타데이터가 포함된 청크 딕셔너리 리스트
        [
            {
                'content': '청크 텍스트...',
                'metadata': {
                    'page_id': '123456',
                    'title': '페이지 제목',
                    'url': 'https://...',
                    'chunk_index': 0,
                    'total_chunks': 5
                }
            }
        ]
    """
    total_chunks = len(chunks)

    return [
        {
            "content": chunk,
            "metadata": {
                "page_id": page_id,
                "title": title,
                "url": url,
                "chunk_index": i,
                "total_chunks": total_chunks,
            },
        }
        for i, chunk in enumerate(chunks)
    ]


def save_processed_chunks(chunks: list[dict], output_path: str):
    """전처리된 청크 데이터를 JSON으로 저장

    Args:
        chunks: 메타데이터 포함 청크 리스트
        output_path: 출력 파일 경로
    """
    output = Path(output_path)

    data = {
        "total_chunks": len(chunks),
        "chunks": chunks,
    }

    output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    console.print(f"[green]저장 완료: {output_path} ({len(chunks)}개 청크)[/green]")


def print_statistics(pages: list[dict], chunks: list[dict]):
    """전처리 결과 통계 출력

    Args:
        pages: 원본 페이지 리스트
        chunks: 생성된 청크 리스트
    """
    total_pages = len(pages)
    total_chunks = len(chunks)
    avg_chunks = total_chunks / total_pages if total_pages > 0 else 0

    # 페이지별 청크 수 집계
    page_chunk_counts = {}
    for chunk in chunks:
        page_id = chunk["metadata"]["page_id"]
        title = chunk["metadata"]["title"]
        page_chunk_counts[page_id] = {
            "title": title,
            "count": chunk["metadata"]["total_chunks"],
        }

    # 빈 콘텐츠 페이지 수
    empty_pages = total_pages - len(page_chunk_counts)

    # --- 요약 테이블 ---
    summary_table = Table(title="전처리 결과 요약")
    summary_table.add_column("항목", style="cyan")
    summary_table.add_column("값", justify="right", style="bold")

    summary_table.add_row("처리된 총 페이지 수", str(total_pages))
    summary_table.add_row("빈 콘텐츠 페이지", str(empty_pages))
    summary_table.add_row("생성된 총 청크 수", str(total_chunks))
    summary_table.add_row("페이지당 평균 청크 수", f"{avg_chunks:.1f}")

    if page_chunk_counts:
        max_page = max(page_chunk_counts.values(), key=lambda x: x["count"])
        min_page = min(page_chunk_counts.values(), key=lambda x: x["count"])
        summary_table.add_row(
            "최대 청크 페이지",
            f"{max_page['title'][:30]} ({max_page['count']}개)",
        )
        summary_table.add_row(
            "최소 청크 페이지",
            f"{min_page['title'][:30]} ({min_page['count']}개)",
        )

    console.print()
    console.print(summary_table)

    # --- 페이지별 상세 테이블 (상위 10개) ---
    if page_chunk_counts:
        detail_table = Table(title="페이지별 청크 수 (상위 10개)")
        detail_table.add_column("#", style="dim", justify="right")
        detail_table.add_column("페이지 제목", style="cyan")
        detail_table.add_column("청크 수", justify="right", style="bold")

        sorted_pages = sorted(
            page_chunk_counts.values(),
            key=lambda x: x["count"],
            reverse=True,
        )

        for i, page_info in enumerate(sorted_pages[:10], 1):
            detail_table.add_row(
                str(i),
                page_info["title"][:50],
                str(page_info["count"]),
            )

        console.print()
        console.print(detail_table)


# ============================================
# CLI 진입점
# ============================================
@click.command()
@click.option(
    "--input", "input_path",
    default="confluence_backup.json",
    help="입력 파일 경로 (기본값: confluence_backup.json)",
)
@click.option(
    "--output", "output_path",
    default="processed_chunks.json",
    help="출력 파일 경로 (기본값: processed_chunks.json)",
)
@click.option(
    "--chunk-size",
    default=1000,
    type=int,
    help="청크 최대 글자 수 (기본값: 1000)",
)
@click.option(
    "--chunk-overlap",
    default=200,
    type=int,
    help="청크 간 겹치는 글자 수 (기본값: 200)",
)
def main(input_path: str, output_path: str, chunk_size: int, chunk_overlap: int):
    """Confluence 크롤링 데이터 전처리

    크롤링된 JSON 데이터를 RAG 시스템에 적합한 청크로 분할합니다.
    한국어 문장 단위 분할을 우선 적용합니다.

    \b
    사용 예시:
        python preprocess_data.py
        python preprocess_data.py --chunk-size 500 --chunk-overlap 100
        python preprocess_data.py --input backup.json --output chunks.json
    """
    console.print("\n[bold magenta]===== 데이터 전처리 시작 =====[/bold magenta]\n")
    console.print(f"[dim]청크 크기: {chunk_size} / 오버랩: {chunk_overlap}[/dim]\n")

    # 1. 데이터 로드
    pages = load_backup_data(input_path)

    # 2. 청크 분할 + 메타데이터 추가
    chunks = split_into_chunks(pages, chunk_size, chunk_overlap)

    # 3. 결과 저장
    save_processed_chunks(chunks, output_path)

    # 4. 통계 출력
    print_statistics(pages, chunks)

    console.print(f"\n[bold magenta]===== 전처리 완료 =====[/bold magenta]\n")


if __name__ == "__main__":
    main()
