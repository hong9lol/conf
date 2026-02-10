"""
시스템 체크 스크립트

프로젝트 실행에 필요한 모든 환경 요소를 점검하고
문제가 있으면 해결 방법을 안내합니다.
"""

import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

console = Console()

# 체크 결과 카운터
passed = 0
failed = 0
warned = 0


def check_pass(item: str, detail: str = ""):
    """체크 통과"""
    global passed
    passed += 1
    msg = f"[green]  ✅ {item}[/green]"
    if detail:
        msg += f"  [dim]{detail}[/dim]"
    console.print(msg)


def check_fail(item: str, fix: str):
    """체크 실패 + 해결 방법"""
    global failed
    failed += 1
    console.print(f"[red]  ❌ {item}[/red]")
    console.print(f"[yellow]     → {fix}[/yellow]")


def check_warn(item: str, detail: str):
    """경고"""
    global warned
    warned += 1
    console.print(f"[yellow]  ⚠️  {item}[/yellow]")
    console.print(f"[dim]     → {detail}[/dim]")


# ============================================
# 1. Python 버전
# ============================================
def check_python_version():
    """Python 버전 확인 (3.8 이상)"""
    console.print("\n[bold cyan]1. Python 환경[/bold cyan]")

    version = platform.python_version()
    major, minor = sys.version_info.major, sys.version_info.minor

    if major >= 3 and minor >= 8:
        check_pass(f"Python 버전: {version}")
    else:
        check_fail(
            f"Python 버전: {version} (3.8 이상 필요)",
            "Python 3.11 이상을 설치하세요: https://python.org"
        )


# ============================================
# 2. 가상환경 확인
# ============================================
def check_venv():
    """가상환경 활성화 여부 확인"""
    console.print("\n[bold cyan]2. 가상환경[/bold cyan]")

    venv_path = Path("venv")
    venv_active = sys.prefix != sys.base_prefix

    if venv_active:
        check_pass("가상환경 활성화됨", sys.prefix)
    elif venv_path.exists():
        check_warn(
            "가상환경이 존재하지만 활성화되지 않았습니다",
            "source venv/bin/activate"
        )
    else:
        check_fail(
            "가상환경이 없습니다",
            "python3 -m venv venv && source venv/bin/activate"
        )


# ============================================
# 3. 필수 패키지 설치 여부
# ============================================
def check_packages():
    """필수 패키지 설치 확인"""
    console.print("\n[bold cyan]3. 필수 패키지[/bold cyan]")

    packages = {
        "playwright": "playwright",
        "bs4": "beautifulsoup4",
        "markdownify": "markdownify",
        "langchain": "langchain",
        "chromadb": "chromadb",
        "sentence_transformers": "sentence-transformers",
        "gradio": "gradio",
        "dotenv": "python-dotenv",
        "click": "click",
        "tqdm": "tqdm",
        "rich": "rich",
    }

    missing = []
    for import_name, pip_name in packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        check_pass(f"필수 패키지 {len(packages)}개 모두 설치됨")
    else:
        check_fail(
            f"미설치 패키지: {', '.join(missing)}",
            f"pip install {' '.join(missing)}"
        )


# ============================================
# 4. .env 파일 및 필수 변수
# ============================================
def check_env_file():
    """환경변수 파일 및 필수 변수 확인"""
    console.print("\n[bold cyan]4. 환경변수 (.env)[/bold cyan]")

    if not Path(".env").exists():
        check_fail(
            ".env 파일이 없습니다",
            "cp .env.template .env && vim .env"
        )
        return

    check_pass(".env 파일 존재")

    # 필수 변수 확인
    required = {
        "CONFLUENCE_BASE_URL": "Confluence 기본 URL",
        "CONFLUENCE_USERNAME": "Confluence 사용자명",
        "CONFLUENCE_PASSWORD": "Confluence 비밀번호/API 토큰",
        "ROOT_PAGE_URL": "크롤링 시작 페이지 URL",
    }

    for var, desc in required.items():
        value = os.getenv(var, "")
        if value and not value.startswith("your-"):
            check_pass(f"{var} 설정됨")
        elif value.startswith("your-"):
            check_warn(
                f"{var} 기본값 그대로입니다",
                f".env 파일에서 {desc}을(를) 실제 값으로 변경하세요"
            )
        else:
            check_fail(
                f"{var} 미설정",
                f".env 파일에 {desc}을(를) 입력하세요"
            )


# ============================================
# 5. Playwright 브라우저
# ============================================
def check_playwright():
    """Playwright Chromium 브라우저 설치 확인"""
    console.print("\n[bold cyan]5. Playwright 브라우저[/bold cyan]")

    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(headless=True)
            browser.close()
            check_pass("Playwright Chromium 설치됨")
        except Exception:
            check_fail(
                "Chromium 브라우저가 설치되지 않았습니다",
                "playwright install chromium"
            )
        finally:
            pw.stop()
    except ImportError:
        check_fail(
            "Playwright가 설치되지 않았습니다",
            "pip install playwright && playwright install chromium"
        )
    except Exception as e:
        check_warn(
            f"Playwright 확인 중 오류: {e}",
            "playwright install chromium"
        )


# ============================================
# 6. Ollama 서버 및 모델
# ============================================
def check_ollama():
    """Ollama 서버 실행 및 모델 존재 확인"""
    console.print("\n[bold cyan]6. Ollama LLM[/bold cyan]")

    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "anpigon/eeve-korean-10.8b")

    # 서버 연결 확인
    try:
        resp = requests.get(f"{host}/api/tags", timeout=5)
        if resp.status_code == 200:
            check_pass(f"Ollama 서버 실행 중", host)

            # 모델 확인 (ollama list 명령어 사용 - API 호환성 문제 대응)
            try:
                # OLLAMA_HOST 환경변수가 CLI 동작에 영향을 주므로 제거하고 실행
                env = {k: v for k, v in os.environ.items() if k != "OLLAMA_HOST"}
                result = subprocess.run(
                    ["ollama", "list"],
                    capture_output=True, text=True, timeout=10, env=env,
                )
                model_names = []
                for line in result.stdout.strip().split("\n")[1:]:  # 헤더 스킵
                    if line.strip():
                        name = line.split()[0].split(":")[0]
                        model_names.append(name)

                if model in model_names:
                    check_pass(f"모델 '{model}' 설치됨")
                else:
                    available = ", ".join(model_names[:5]) if model_names else "없음"
                    check_fail(
                        f"모델 '{model}' 미설치",
                        f"ollama pull {model}"
                    )
                    if model_names:
                        console.print(f"[dim]     설치된 모델: {available}[/dim]")
            except FileNotFoundError:
                check_warn("ollama 명령어를 찾을 수 없습니다", "ollama 설치 확인")
            except Exception as e:
                check_warn(f"모델 확인 실패: {e}", f"ollama list 로 직접 확인하세요")
        else:
            check_fail("Ollama 서버 응답 이상", "ollama serve")
    except requests.ConnectionError:
        check_fail(
            f"Ollama 서버에 연결할 수 없습니다 ({host})",
            "ollama serve"
        )
    except Exception as e:
        check_fail(f"Ollama 확인 실패: {e}", "ollama serve")


# ============================================
# 7. 필요 디렉토리
# ============================================
def check_directories():
    """필요한 디렉토리 존재 확인"""
    console.print("\n[bold cyan]7. 디렉토리[/bold cyan]")

    dirs = {
        "confluence_pages": "크롤링된 페이지 저장",
        "confluence_vectordb": "벡터 데이터베이스",
        "logs": "로그 파일",
        "backups": "백업 파일",
    }

    for dir_name, desc in dirs.items():
        path = Path(dir_name)
        if path.exists():
            check_pass(f"{dir_name}/", desc)
        else:
            check_warn(
                f"{dir_name}/ 없음 ({desc})",
                f"mkdir -p {dir_name}  (실행 시 자동 생성됩니다)"
            )


# ============================================
# 8. last_sync.json
# ============================================
def check_sync_state():
    """동기화 상태 파일 확인"""
    console.print("\n[bold cyan]8. 동기화 상태[/bold cyan]")

    sync_file = Path("last_sync.json")
    if sync_file.exists():
        try:
            import json
            data = json.loads(sync_file.read_text(encoding="utf-8"))
            pages = len(data.get("pages", {}))
            check_pass(f"last_sync.json 존재", f"{pages}개 페이지 추적 중")
        except Exception:
            check_warn(
                "last_sync.json 파일이 손상되었을 수 있습니다",
                "python -c \"from sync_state import init_sync_state; init_sync_state()\""
            )
    else:
        check_warn(
            "last_sync.json 없음 (최초 실행 시 자동 생성)",
            "python weekly_update.py --full 실행 시 생성됩니다"
        )


# ============================================
# 9. 포트 7860
# ============================================
def check_port():
    """Gradio UI 포트 사용 가능 여부 확인"""
    console.print("\n[bold cyan]9. 네트워크 포트[/bold cyan]")

    port = int(os.getenv("GRADIO_SERVER_PORT", "7860"))

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", port))
        sock.close()

        if result == 0:
            # 포트가 열려있음 = 이미 사용 중
            check_warn(
                f"포트 {port}이 이미 사용 중입니다",
                f"Gradio가 이미 실행 중이거나 다른 프로세스가 사용 중입니다. "
                f".env에서 GRADIO_SERVER_PORT를 변경하세요"
            )
        else:
            check_pass(f"포트 {port} 사용 가능")
    except Exception:
        check_pass(f"포트 {port} 사용 가능")


# ============================================
# 결과 요약
# ============================================
def print_summary():
    """체크 결과 요약 출력"""
    total = passed + failed + warned

    console.print()

    table = Table(title="체크 결과 요약", show_header=True, header_style="bold")
    table.add_column("결과", justify="center")
    table.add_column("건수", justify="right", style="bold")

    table.add_row("[green]✅ 통과[/green]", str(passed))
    table.add_row("[red]❌ 실패[/red]", str(failed))
    table.add_row("[yellow]⚠️  경고[/yellow]", str(warned))
    table.add_row("총 검사 항목", str(total))

    console.print(table)

    if failed == 0:
        console.print("\n[bold green]모든 필수 항목을 통과했습니다! 시스템 준비 완료.[/bold green]")
    else:
        console.print(f"\n[bold red]{failed}개 항목이 실패했습니다. 위의 해결 방법을 참고하세요.[/bold red]")

    if warned > 0:
        console.print(f"[yellow]{warned}개 경고가 있습니다. 확인을 권장합니다.[/yellow]")


# ============================================
# 메인 실행
# ============================================
if __name__ == "__main__":
    console.print()
    console.print(Panel(
        "[bold]Confluence AI 검색 시스템 - 환경 점검[/bold]",
        border_style="magenta",
    ))

    check_python_version()
    check_venv()
    check_packages()
    check_env_file()
    check_playwright()
    check_ollama()
    check_directories()
    check_sync_state()
    check_port()

    print_summary()
    console.print()
