"""
Gradio 웹 인터페이스

Confluence RAG 검색 시스템의 웹 UI를 제공합니다.
사용자가 자연어로 질문하면 관련 문서를 검색하고 답변을 생성합니다.
"""

import os

import gradio as gr
from dotenv import load_dotenv
from rich.console import Console

from rag_search import ConfluenceRAG

load_dotenv()

console = Console()

# RAG 엔진 전역 인스턴스
rag_engine: ConfluenceRAG | None = None


def load_rag_system() -> ConfluenceRAG | None:
    """RAG 시스템 초기화

    ConfluenceRAG 인스턴스를 생성하고 전역 변수에 저장합니다.
    초기화 실패 시 None을 반환합니다.

    Returns:
        ConfluenceRAG 인스턴스 또는 None
    """
    global rag_engine

    if rag_engine is not None:
        return rag_engine

    try:
        console.print("[blue]RAG 시스템 초기화 중...[/blue]")
        rag_engine = ConfluenceRAG()
        console.print("[green]RAG 시스템 준비 완료[/green]")
        return rag_engine

    except FileNotFoundError:
        console.print("[red]벡터 DB가 존재하지 않습니다.[/red]")
        return None

    except ConnectionError:
        console.print("[red]Ollama 서버에 연결할 수 없습니다.[/red]")
        return None

    except Exception as e:
        console.print(f"[red]RAG 시스템 초기화 실패: {e}[/red]")
        return None


def search_interface(query: str) -> str:
    """검색 인터페이스 핸들러

    Gradio UI에서 호출되는 메인 검색 함수입니다.
    입력 검증, RAG 검색, 에러 처리를 수행합니다.

    Args:
        query: 사용자 질문 텍스트

    Returns:
        Markdown 형식의 응답 문자열
    """
    # --- 입력 검증 ---
    if not query or not query.strip():
        return "⚠️ 질문을 입력해주세요."

    query = query.strip()

    if len(query) > 500:
        return "⚠️ 질문은 500자 이내로 입력해주세요."

    if len(query) < 2:
        return "⚠️ 좀 더 구체적으로 질문해주세요."

    # --- RAG 엔진 확인 ---
    if rag_engine is None:
        return (
            "## ❌ 시스템 오류\n\n"
            "RAG 시스템이 초기화되지 않았습니다.\n\n"
            "다음 사항을 확인해주세요:\n\n"
            "1. **벡터 DB 구축 여부**\n"
            "   ```bash\n"
            "   python preprocess_data.py\n"
            "   python build_vectordb.py\n"
            "   ```\n\n"
            "2. **Ollama 서버 실행 여부**\n"
            "   ```bash\n"
            "   ollama serve\n"
            "   ollama pull anpigon/eeve-korean-10.8b\n"
            "   ```"
        )

    # --- RAG 검색 실행 ---
    try:
        result = rag_engine.search(query)

        # 검색 결과가 비어있는 경우
        if not result["answer"].strip():
            return (
                "## 🔍 검색 결과 없음\n\n"
                "입력하신 질문에 대한 관련 문서를 찾지 못했습니다.\n\n"
                "**다음을 시도해보세요:**\n"
                "- 다른 키워드로 질문해보세요\n"
                "- 좀 더 구체적으로 질문해보세요\n"
                "- Confluence에 관련 문서가 있는지 확인해보세요"
            )

        # 정상 응답 포맷팅
        return rag_engine.format_response(result)

    except ConnectionError:
        return (
            "## ❌ Ollama 연결 실패\n\n"
            "Ollama 서버에 연결할 수 없습니다.\n\n"
            "```bash\n"
            "ollama serve\n"
            "```\n\n"
            "서버를 시작한 후 다시 시도해주세요."
        )

    except Exception as e:
        return (
            "## ❌ 검색 오류\n\n"
            f"검색 중 오류가 발생했습니다: `{e}`\n\n"
            "문제가 지속되면 시스템 관리자에게 문의해주세요."
        )


def create_ui() -> gr.Blocks:
    """Gradio 웹 인터페이스 생성

    Returns:
        Gradio Blocks 인스턴스
    """
    # 예시 질문 목록
    examples = [
        ["프로젝트 배포 프로세스는 어떻게 되나요?"],
        ["개발 환경 설정 방법을 알려주세요"],
        ["코드 리뷰 가이드라인이 있나요?"],
        ["API 인증 방식은 어떻게 되나요?"],
        ["신규 입사자 온보딩 절차가 궁금합니다"],
    ]

    with gr.Blocks(
        theme=gr.themes.Soft(),
        title="Confluence AI 검색",
        css="""
            .main-title { text-align: center; margin-bottom: 0.5em; }
            .sub-desc { text-align: center; color: #666; margin-bottom: 1.5em; }
        """,
    ) as app:

        # --- 헤더 ---
        gr.Markdown(
            "<h1 class='main-title'>🔍 Confluence AI 검색</h1>",
        )
        gr.Markdown(
            "<p class='sub-desc'>"
            "Confluence 문서를 AI로 검색합니다. "
            "자연어로 질문하면 관련 문서를 찾아 답변을 생성합니다."
            "</p>",
        )

        with gr.Row():
            with gr.Column(scale=4):
                # 질문 입력
                query_input = gr.Textbox(
                    label="질문",
                    placeholder="궁금한 내용을 질문해주세요...",
                    max_lines=3,
                    lines=2,
                )
            with gr.Column(scale=1, min_width=120):
                # 검색 버튼
                search_btn = gr.Button(
                    "🔍 검색",
                    variant="primary",
                    size="lg",
                )

        # 답변 출력
        answer_output = gr.Markdown(
            label="답변",
            value="*질문을 입력하고 검색 버튼을 클릭하세요.*",
        )

        # 예시 질문
        gr.Examples(
            examples=examples,
            inputs=query_input,
            label="예시 질문",
        )

        # --- 이벤트 바인딩 ---
        # 검색 버튼 클릭
        search_btn.click(
            fn=search_interface,
            inputs=query_input,
            outputs=answer_output,
        )

        # Enter 키로 검색
        query_input.submit(
            fn=search_interface,
            inputs=query_input,
            outputs=answer_output,
        )

        # --- 하단 정보 ---
        gr.Markdown(
            "<hr/>"
            "<p style='text-align:center; color:#999; font-size:0.85em;'>"
            "Confluence RAG 시스템 | "
            "ChromaDB + Ollama | "
            "벡터 유사도 검색 기반"
            "</p>"
        )

    return app


# ============================================
# 메인 실행
# ============================================
if __name__ == "__main__":
    # RAG 시스템 초기화
    load_rag_system()

    # UI 생성 및 실행
    app = create_ui()

    # 서버 포트 (.env에서 로드, 기본값 7860)
    port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))

    console.print(f"\n[bold magenta]===== Confluence AI 검색 UI 시작 =====[/bold magenta]")
    console.print(f"[green]http://localhost:{port}[/green]\n")

    app.launch(
        server_port=port,
        share=False,
        show_error=True,
    )
