"""
RAG 검색 엔진

ChromaDB 벡터 검색과 Ollama LLM을 결합하여
Confluence 문서 기반 질의응답을 수행합니다.
"""

import os
import time
from pathlib import Path

from chromadb import PersistentClient
from chromadb.config import Settings
from dotenv import load_dotenv
from langchain_community.llms import Ollama
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from build_vectordb import (
    DEFAULT_COLLECTION,
    DEFAULT_PERSIST_DIR,
    load_embedding_model,
)

load_dotenv()

console = Console()

# ============================================
# 프롬프트 템플릿
# ============================================
RAG_PROMPT_TEMPLATE = """다음은 Confluence 문서에서 검색된 관련 내용입니다:

{context}

위 내용을 바탕으로 다음 질문에 답변해주세요:
{question}

답변 형식:
1. 핵심 요약 (2-3문장)
2. 상세 설명
3. 필요시 예시 또는 단계별 설명

답변은 명확하고 구체적으로, 한국어로 작성해주세요.
문서에서 관련 내용을 찾을 수 없는 경우, 솔직하게 "해당 내용을 문서에서 찾을 수 없습니다"라고 답변해주세요."""

# Ollama 연결 최대 재시도 횟수
MAX_RETRIES = 3
RETRY_DELAY = 3


class ConfluenceRAG:
    """Confluence RAG 검색 엔진

    벡터 유사도 검색으로 관련 문서를 찾고,
    Ollama LLM을 통해 자연어 답변을 생성합니다.
    """

    def __init__(
        self,
        persist_dir: str = DEFAULT_PERSIST_DIR,
        ollama_host: str = None,
        ollama_model: str = None,
    ):
        """RAG 엔진 초기화

        Args:
            persist_dir: ChromaDB 저장 경로
            ollama_host: Ollama 서버 주소 (기본값: .env의 OLLAMA_HOST)
            ollama_model: 사용할 LLM 모델명 (기본값: .env의 OLLAMA_MODEL)
        """
        self.persist_dir = persist_dir
        self.ollama_host = ollama_host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.ollama_model = ollama_model or os.getenv("OLLAMA_MODEL", "eeve-korean-10.8b")

        # ChromaDB 로드
        self.collection = self._load_vectordb()

        # 임베딩 모델 로드
        self.embeddings = load_embedding_model()

        # Ollama LLM 초기화
        self.llm = self._init_ollama()

    def _load_vectordb(self):
        """ChromaDB 벡터 저장소 로드

        Returns:
            ChromaDB 컬렉션

        Raises:
            FileNotFoundError: DB 디렉토리가 없을 때
        """
        if not Path(self.persist_dir).exists():
            console.print(f"[red]오류: 벡터 DB가 존재하지 않습니다: {self.persist_dir}[/red]")
            console.print("[yellow]먼저 build_vectordb.py를 실행해주세요:[/yellow]")
            console.print("[dim]  1. python preprocess_data.py[/dim]")
            console.print("[dim]  2. python build_vectordb.py[/dim]")
            raise FileNotFoundError(f"벡터 DB 없음: {self.persist_dir}")

        client = PersistentClient(
            path=self.persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        collection = client.get_collection(name=DEFAULT_COLLECTION)

        count = collection.count()
        if count == 0:
            console.print("[yellow]경고: 벡터 DB가 비어 있습니다.[/yellow]")
        else:
            console.print(f"[green]벡터 DB 로드 완료 ({count:,}개 벡터)[/green]")

        return collection

    def _init_ollama(self) -> Ollama:
        """Ollama LLM 초기화 (재시도 포함)

        Returns:
            Ollama LLM 인스턴스

        Raises:
            ConnectionError: 최대 재시도 후에도 연결 실패 시
        """
        console.print(f"[blue]Ollama 연결 중: {self.ollama_host} ({self.ollama_model})[/blue]")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                llm = Ollama(
                    base_url=self.ollama_host,
                    model=self.ollama_model,
                    temperature=0.3,
                )

                # 연결 테스트
                llm.invoke("테스트")
                console.print("[green]Ollama 연결 성공[/green]")
                return llm

            except Exception as e:
                console.print(
                    f"[yellow]Ollama 연결 실패 (시도 {attempt}/{MAX_RETRIES}): {e}[/yellow]"
                )
                if attempt < MAX_RETRIES:
                    console.print(f"[dim]{RETRY_DELAY}초 후 재시도...[/dim]")
                    time.sleep(RETRY_DELAY)
                else:
                    console.print("[red]Ollama 연결에 실패했습니다.[/red]")
                    console.print("[yellow]Ollama가 실행 중인지 확인해주세요:[/yellow]")
                    console.print(f"[dim]  ollama serve[/dim]")
                    console.print(f"[dim]  ollama pull {self.ollama_model}[/dim]")
                    raise ConnectionError(
                        f"Ollama 연결 실패: {self.ollama_host}"
                    ) from e

    def search(self, query: str, k: int = 5) -> dict:
        """RAG 검색 수행

        쿼리를 벡터로 변환하여 유사 문서를 검색하고,
        LLM을 통해 답변을 생성합니다.

        Args:
            query: 사용자 질문
            k: 검색할 문서 수 (기본값: 5)

        Returns:
            {
                'answer': LLM 생성 답변,
                'sources': [출처 정보 리스트],
                'query': 원본 질문,
                'elapsed': 소요 시간(초)
            }
        """
        start_time = time.time()

        console.print(f"\n[bold cyan]질문: {query}[/bold cyan]")
        console.print("[dim]검색 중...[/dim]")

        # 1. 쿼리를 벡터로 변환
        query_vector = self.embeddings.embed_query(query)

        # 2. 유사도 검색
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=min(k, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        # 3. 출처 정보 구성 (중복 URL 제거)
        sources = []
        seen_urls = set()
        for meta, dist in zip(metadatas, distances):
            url = meta.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    "title": meta.get("title", "제목 없음"),
                    "url": url,
                    "page_id": meta.get("page_id", ""),
                    "relevance": round(1 - dist, 4),  # 거리 → 유사도 변환
                })

        # 4. 컨텍스트 구성
        context = self._build_context(documents, metadatas)

        # 5. LLM으로 답변 생성
        prompt = RAG_PROMPT_TEMPLATE.format(
            context=context,
            question=query,
        )

        console.print("[dim]답변 생성 중...[/dim]")
        answer = self.llm.invoke(prompt)

        elapsed = time.time() - start_time

        return {
            "answer": answer.strip(),
            "sources": sources,
            "query": query,
            "elapsed": round(elapsed, 2),
        }

    def _build_context(self, documents: list[str], metadatas: list[dict]) -> str:
        """검색된 문서를 컨텍스트 문자열로 구성

        Args:
            documents: 검색된 문서 텍스트 리스트
            metadatas: 문서 메타데이터 리스트

        Returns:
            포맷팅된 컨텍스트 문자열
        """
        context_parts = []

        for i, (doc, meta) in enumerate(zip(documents, metadatas), 1):
            title = meta.get("title", "제목 없음")
            chunk_idx = meta.get("chunk_index", 0)
            total = meta.get("total_chunks", 1)

            context_parts.append(
                f"[문서 {i}] {title} (청크 {chunk_idx + 1}/{total})\n{doc}"
            )

        return "\n\n---\n\n".join(context_parts)

    def format_response(self, result: dict) -> str:
        """검색 결과를 Markdown 형식으로 포맷팅

        Args:
            result: search() 반환값

        Returns:
            Markdown 형식 응답 문자열
        """
        lines = []

        # 답변
        lines.append("## 답변\n")
        lines.append(result["answer"])
        lines.append("")

        # 출처
        if result["sources"]:
            lines.append("---")
            lines.append("")
            lines.append("## 참고 문서\n")
            for i, source in enumerate(result["sources"], 1):
                relevance_pct = int(source["relevance"] * 100)
                lines.append(
                    f"{i}. **[{source['title']}]({source['url']})** "
                    f"(관련도: {relevance_pct}%)"
                )
            lines.append("")

        # 메타 정보
        lines.append(f"*검색 소요 시간: {result['elapsed']}초*")

        return "\n".join(lines)

    def display_response(self, result: dict):
        """검색 결과를 Rich 콘솔에 출력

        Args:
            result: search() 반환값
        """
        # 답변 패널
        console.print()
        console.print(Panel(
            Markdown(result["answer"]),
            title="[bold green]답변[/bold green]",
            border_style="green",
        ))

        # 출처 테이블
        if result["sources"]:
            console.print()
            console.print("[bold]참고 문서:[/bold]")
            for i, source in enumerate(result["sources"], 1):
                relevance_pct = int(source["relevance"] * 100)
                console.print(
                    f"  {i}. [cyan]{source['title']}[/cyan] "
                    f"(관련도: {relevance_pct}%)"
                )
                console.print(f"     [dim]{source['url']}[/dim]")

        console.print(f"\n[dim]소요 시간: {result['elapsed']}초[/dim]")


# ============================================
# 테스트 / CLI 진입점
# ============================================
if __name__ == "__main__":
    console.print("\n[bold magenta]===== Confluence RAG 검색 테스트 =====[/bold magenta]\n")

    try:
        # RAG 엔진 초기화
        rag = ConfluenceRAG()

        # 샘플 쿼리 목록
        sample_queries = [
            "프로젝트 개발 환경 설정 방법은?",
            "배포 프로세스를 설명해줘",
            "API 인증 방식은 어떻게 되나요?",
        ]

        console.print("[bold]샘플 쿼리로 테스트를 시작합니다.[/bold]\n")

        for query in sample_queries:
            result = rag.search(query)
            rag.display_response(result)
            console.print("\n" + "=" * 60 + "\n")

        # 대화형 모드
        console.print("[bold yellow]대화형 모드 (종료: q 또는 quit)[/bold yellow]\n")

        while True:
            query = console.input("[bold cyan]질문> [/bold cyan]").strip()

            if query.lower() in ("q", "quit", "exit", "종료"):
                console.print("[dim]종료합니다.[/dim]")
                break

            if not query:
                continue

            result = rag.search(query)
            rag.display_response(result)
            console.print()

    except FileNotFoundError:
        console.print("\n[red]벡터 DB를 먼저 구축해주세요.[/red]")
    except ConnectionError:
        console.print("\n[red]Ollama 서버를 확인해주세요.[/red]")
    except KeyboardInterrupt:
        console.print("\n[dim]종료합니다.[/dim]")
