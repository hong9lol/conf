"""
Confluence 증분 크롤러

Playwright를 사용하여 Confluence 페이지를 재귀적으로 크롤링하고,
증분 동기화를 지원하여 변경된 페이지만 효율적으로 수집합니다.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from markdownify import markdownify as md
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

from sync_state import load_sync_state, update_sync_state, init_sync_state

import os

# ============================================
# 환경변수 로드
# ============================================
load_dotenv()

console = Console()


class ConfluenceCrawler:
    """Confluence 증분 크롤러 클래스

    Playwright 브라우저를 통해 Confluence에 로그인하고,
    지정된 루트 페이지부터 하위 페이지를 재귀적으로 크롤링합니다.
    증분 크롤링을 지원하여 변경된 페이지만 수집할 수 있습니다.
    """

    # 네트워크 오류 시 최대 재시도 횟수
    MAX_RETRIES = 3
    # 재시도 간 대기 시간 (초)
    RETRY_DELAY = 5
    # 페이지 로딩 타임아웃 (밀리초)
    PAGE_TIMEOUT = 30000

    def __init__(self, full_crawl: bool = False):
        """크롤러 초기화

        Args:
            full_crawl: True면 전체 크롤링, False면 증분 크롤링
        """
        # .env에서 설정값 로드
        self.base_url = os.getenv("CONFLUENCE_BASE_URL")
        self.username = os.getenv("CONFLUENCE_USERNAME")
        self.password = os.getenv("CONFLUENCE_PASSWORD")
        self.root_page_url = os.getenv("ROOT_PAGE_URL")

        # 필수 환경변수 검증
        self._validate_config()

        # 크롤링 모드 설정
        self.full_crawl = full_crawl

        # Playwright 브라우저 인스턴스
        self.playwright = None
        self.browser = None
        self.page = None

        # 크롤링 결과 저장
        self.crawled_pages = []  # 크롤링된 페이지 목록
        self.failed_pages = []   # 실패한 페이지 목록

        # 크롤링 통계
        self.stats = {
            "added": 0,      # 새로 추가된 페이지
            "modified": 0,   # 수정된 페이지
            "deleted": 0,    # 삭제된 페이지
            "skipped": 0,    # 변경 없어 건너뛴 페이지
            "failed": 0,     # 실패한 페이지
        }

        # 동기화 상태 로드
        self.sync_state = load_sync_state()

        # 결과 저장 디렉토리
        self.output_dir = Path("confluence_pages")
        self.output_dir.mkdir(exist_ok=True)

        # 백업 디렉토리
        self.backup_dir = Path("backups")
        self.backup_dir.mkdir(exist_ok=True)

    def _validate_config(self):
        """필수 환경변수가 설정되었는지 검증"""
        required = {
            "CONFLUENCE_BASE_URL": self.base_url,
            "CONFLUENCE_USERNAME": self.username,
            "CONFLUENCE_PASSWORD": self.password,
            "ROOT_PAGE_URL": self.root_page_url,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            console.print(
                f"[red]오류: 다음 환경변수가 설정되지 않았습니다: {', '.join(missing)}[/red]"
            )
            console.print("[yellow].env 파일을 확인해주세요.[/yellow]")
            raise ValueError(f"필수 환경변수 누락: {', '.join(missing)}")

    def login(self):
        """Playwright로 Confluence에 로그인

        Atlassian 로그인 페이지를 통해 인증을 수행합니다.

        Raises:
            Exception: 로그인 실패 시
        """
        console.print("[bold blue]Confluence 로그인 중...[/bold blue]")

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.page = self.browser.new_page()

        try:
            # Confluence 로그인 페이지로 이동
            login_url = f"{self.base_url}/login"
            self.page.goto(login_url, timeout=self.PAGE_TIMEOUT)

            # 이메일 입력
            self.page.fill('input[name="username"], input[type="email"]', self.username)
            self.page.click('button[type="submit"], #login-submit')
            self.page.wait_for_timeout(2000)

            # 비밀번호 입력
            self.page.fill('input[name="password"], input[type="password"]', self.password)
            self.page.click('button[type="submit"], #login-submit')

            # 로그인 완료 대기 (대시보드 또는 위키 메인 페이지)
            self.page.wait_for_load_state("networkidle", timeout=self.PAGE_TIMEOUT)

            console.print("[green]로그인 성공![/green]")

        except PlaywrightTimeout:
            console.print("[red]로그인 시간 초과. 인증 정보를 확인해주세요.[/red]")
            raise
        except Exception as e:
            console.print(f"[red]로그인 실패: {e}[/red]")
            raise

    def _navigate_with_retry(self, url: str) -> bool:
        """페이지 이동 (재시도 로직 포함)

        Args:
            url: 이동할 URL

        Returns:
            성공 여부
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = self.page.goto(url, timeout=self.PAGE_TIMEOUT)

                # 404 처리: 삭제된 페이지로 기록
                if response and response.status == 404:
                    console.print(f"[yellow]  404 - 삭제된 페이지: {url}[/yellow]")
                    self.stats["deleted"] += 1
                    return False

                self.page.wait_for_load_state("networkidle", timeout=self.PAGE_TIMEOUT)
                return True

            except PlaywrightTimeout:
                console.print(
                    f"[yellow]  타임아웃 (시도 {attempt}/{self.MAX_RETRIES}): {url}[/yellow]"
                )
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                else:
                    console.print(f"[red]  최대 재시도 초과: {url}[/red]")
                    return False

            except Exception as e:
                console.print(
                    f"[yellow]  네트워크 오류 (시도 {attempt}/{self.MAX_RETRIES}): {e}[/yellow]"
                )
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                else:
                    console.print(f"[red]  최대 재시도 초과: {url}[/red]")
                    return False

        return False

    def extract_page_metadata(self) -> dict | None:
        """현재 페이지의 메타데이터 추출

        Returns:
            페이지 메타데이터 딕셔너리 또는 None
            {
                'title': 페이지 제목,
                'url': 페이지 URL,
                'page_id': 페이지 ID,
                'version': 버전 번호,
                'last_modified': 마지막 수정일
            }
        """
        try:
            # 페이지 제목 추출
            title_element = self.page.query_selector(
                "#title-text, [data-testid='title-text'], h1"
            )
            title = title_element.inner_text().strip() if title_element else "제목 없음"

            # 현재 URL
            url = self.page.url

            # 페이지 ID 추출 (URL에서)
            page_id = self._extract_page_id(url)

            # 버전 정보 추출 (페이지 메타 영역에서)
            version = self._extract_version()

            # 마지막 수정일 추출
            last_modified = self._extract_last_modified()

            return {
                "title": title,
                "url": url,
                "page_id": page_id,
                "version": version,
                "last_modified": last_modified,
            }

        except Exception as e:
            console.print(f"[red]  메타데이터 추출 실패: {e}[/red]")
            return None

    def _extract_page_id(self, url: str) -> str:
        """URL에서 페이지 ID 추출

        Args:
            url: Confluence 페이지 URL

        Returns:
            페이지 ID 문자열
        """
        # /pages/123456/Page-Title 패턴에서 ID 추출
        match = re.search(r"/pages/(\d+)", url)
        if match:
            return match.group(1)

        # pageId 쿼리 파라미터에서 추출
        match = re.search(r"pageId=(\d+)", url)
        if match:
            return match.group(1)

        return ""

    def _extract_version(self) -> int:
        """페이지 버전 번호 추출

        Returns:
            버전 번호 (추출 실패 시 0)
        """
        try:
            # 페이지 정보 영역에서 버전 텍스트 찾기
            version_element = self.page.query_selector(
                ".page-metadata-modification-info, "
                "[data-testid='page-metadata-banner']"
            )
            if version_element:
                text = version_element.inner_text()
                match = re.search(r"v\.?\s*(\d+)|버전\s*(\d+)|version\s*(\d+)", text, re.I)
                if match:
                    return int(next(g for g in match.groups() if g))
        except Exception:
            pass
        return 0

    def _extract_last_modified(self) -> str:
        """마지막 수정일 추출

        Returns:
            ISO 형식 날짜 문자열 (추출 실패 시 빈 문자열)
        """
        try:
            # 수정일 관련 요소 찾기
            time_element = self.page.query_selector(
                "time[datetime], .last-modified, .page-metadata-modification-info time"
            )
            if time_element:
                datetime_attr = time_element.get_attribute("datetime")
                if datetime_attr:
                    return datetime_attr
                return time_element.inner_text().strip()
        except Exception:
            pass
        return ""

    def extract_page_content(self) -> str:
        """현재 페이지의 본문 HTML을 Markdown으로 변환

        Returns:
            Markdown 형식의 페이지 콘텐츠
        """
        try:
            # Confluence 본문 콘텐츠 영역 선택
            content_element = self.page.query_selector(
                "#main-content, "
                "[data-testid='renderer-container'], "
                ".wiki-content, "
                ".confluence-information-macro"
            )

            if not content_element:
                console.print("[yellow]  본문 콘텐츠를 찾을 수 없습니다.[/yellow]")
                return ""

            # HTML 추출
            html_content = content_element.inner_html()

            # BeautifulSoup으로 불필요한 요소 제거
            soup = BeautifulSoup(html_content, "html.parser")

            # 스크립트, 스타일, 매크로 컨트롤 등 제거
            for tag in soup.find_all(["script", "style", "button"]):
                tag.decompose()

            # HTML을 Markdown으로 변환
            markdown_content = md(
                str(soup),
                heading_style="ATX",       # # 스타일 제목
                bullets="-",               # - 스타일 목록
                strip=["img"],             # 이미지 태그 제거 (선택)
            )

            # 연속 빈 줄 정리
            markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)

            return markdown_content.strip()

        except Exception as e:
            console.print(f"[red]  콘텐츠 추출 실패: {e}[/red]")
            return ""

    def extract_child_pages(self) -> list[dict]:
        """현재 페이지의 하위 페이지 링크 목록 추출

        Returns:
            하위 페이지 정보 리스트 [{'title': ..., 'url': ...}, ...]
        """
        child_pages = []

        try:
            # Confluence 하위 페이지 목록 영역 선택
            # (Children Display 매크로 또는 페이지 트리)
            child_links = self.page.query_selector_all(
                ".children-show-hide a, "
                ".plugin_pagetree_children_container a, "
                "[data-testid='children-item'] a, "
                ".childpages-macro a"
            )

            for link in child_links:
                href = link.get_attribute("href")
                title = link.inner_text().strip()

                if href and title:
                    # 상대 URL을 절대 URL로 변환
                    full_url = urljoin(self.base_url, href)

                    # Confluence 페이지 URL 패턴 확인
                    if "/wiki/" in full_url or "/pages/" in full_url:
                        child_pages.append({
                            "title": title,
                            "url": full_url,
                        })

            console.print(f"[dim]  하위 페이지 {len(child_pages)}개 발견[/dim]")

        except Exception as e:
            console.print(f"[yellow]  하위 페이지 추출 실패: {e}[/yellow]")

        return child_pages

    def is_page_modified(self, page_id: str, version: int, last_modified: str) -> bool:
        """페이지가 마지막 동기화 이후 수정되었는지 확인

        last_sync.json에 저장된 정보와 비교하여 판단합니다.

        Args:
            page_id: 페이지 ID
            version: 현재 버전 번호
            last_modified: 현재 수정일

        Returns:
            수정 여부 (True: 수정됨 또는 신규)
        """
        # 전체 크롤링 모드면 항상 True
        if self.full_crawl:
            return True

        # 이전 동기화 상태에서 페이지 정보 조회
        pages_state = self.sync_state.get("pages", {})
        prev_info = pages_state.get(page_id)

        # 신규 페이지
        if prev_info is None:
            return True

        # 버전 비교 (버전이 있는 경우)
        if version > 0 and prev_info.get("version", 0) > 0:
            return version != prev_info["version"]

        # 수정일 비교
        if last_modified and prev_info.get("last_modified"):
            return last_modified != prev_info["last_modified"]

        # 판단 불가 시 수정된 것으로 간주
        return True

    def crawl_page(self, url: str, depth: int = 0):
        """페이지를 재귀적으로 크롤링

        지정된 URL의 페이지를 크롤링하고,
        하위 페이지가 있으면 재귀적으로 처리합니다.

        Args:
            url: 크롤링할 페이지 URL
            depth: 현재 재귀 깊이 (로깅용)
        """
        indent = "  " * depth
        console.print(f"{indent}[cyan]크롤링: {url}[/cyan]")

        # 페이지 이동 (재시도 포함)
        if not self._navigate_with_retry(url):
            self.failed_pages.append({"url": url, "reason": "접근 실패"})
            self.stats["failed"] += 1
            return

        # 메타데이터 추출
        metadata = self.extract_page_metadata()
        if not metadata:
            self.failed_pages.append({"url": url, "reason": "메타데이터 추출 실패"})
            self.stats["failed"] += 1
            return

        page_id = metadata["page_id"]
        console.print(f"{indent}  제목: [bold]{metadata['title']}[/bold]")

        # 증분 크롤링: 변경 여부 확인
        if not self.is_page_modified(page_id, metadata["version"], metadata["last_modified"]):
            console.print(f"{indent}  [dim]변경 없음 - 건너뜀[/dim]")
            self.stats["skipped"] += 1
        else:
            # 콘텐츠 추출
            content = self.extract_page_content()

            # 신규/수정 판별
            pages_state = self.sync_state.get("pages", {})
            if page_id in pages_state:
                self.stats["modified"] += 1
                status = "수정"
            else:
                self.stats["added"] += 1
                status = "신규"

            console.print(f"{indent}  [green]{status} - 저장 완료[/green]")

            # 결과 저장
            self.crawled_pages.append({
                **metadata,
                "content": content,
                "depth": depth,
                "crawled_at": datetime.now().isoformat(),
            })

        # 하위 페이지 크롤링
        child_pages = self.extract_child_pages()
        for child in child_pages:
            self.crawl_page(child["url"], depth=depth + 1)

    def save_results(self):
        """크롤링 결과를 JSON과 개별 Markdown 파일로 저장

        - confluence_backup.json: 전체 결과를 하나의 JSON으로
        - confluence_pages/: 각 페이지를 개별 .md 파일로
        """
        if not self.crawled_pages:
            console.print("[yellow]저장할 크롤링 결과가 없습니다.[/yellow]")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # --- 1) JSON 전체 백업 ---
        backup_data = {
            "crawl_timestamp": datetime.now().isoformat(),
            "crawl_type": "full" if self.full_crawl else "incremental",
            "total_pages": len(self.crawled_pages),
            "pages": self.crawled_pages,
        }

        json_path = Path("confluence_backup.json")
        json_path.write_text(json.dumps(backup_data, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[green]JSON 백업 저장: {json_path}[/green]")

        # --- 2) 개별 Markdown 파일 저장 ---
        for page_data in self.crawled_pages:
            # 파일명 생성 (특수문자 제거)
            safe_title = re.sub(r'[\\/*?:"<>|]', "_", page_data["title"])
            safe_title = safe_title[:100]  # 파일명 길이 제한
            md_filename = f"{safe_title}.md"
            md_path = self.output_dir / md_filename

            # Markdown 파일 내용 구성
            md_content = (
                f"# {page_data['title']}\n\n"
                f"> 원본 URL: {page_data['url']}  \n"
                f"> 크롤링 일시: {page_data['crawled_at']}  \n"
                f"> 페이지 ID: {page_data['page_id']}\n\n"
                f"---\n\n"
                f"{page_data['content']}\n"
            )

            md_path.write_text(md_content, encoding="utf-8")

        console.print(
            f"[green]Markdown 파일 {len(self.crawled_pages)}개 저장: {self.output_dir}/[/green]"
        )

        # --- 3) 백업 복사본 (타임스탬프 포함) ---
        backup_json_path = self.backup_dir / f"confluence_backup_{timestamp}.json"
        backup_json_path.write_text(
            json.dumps(backup_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"[dim]백업 복사본: {backup_json_path}[/dim]")

    def update_sync_state(self):
        """동기화 상태 파일(last_sync.json) 업데이트

        크롤링 결과를 반영하여 각 페이지의 버전, 수정일 정보와
        동기화 이력을 저장합니다.
        """
        # 페이지별 상태 업데이트
        pages_state = self.sync_state.get("pages", {})
        for page_data in self.crawled_pages:
            page_id = page_data["page_id"]
            pages_state[page_id] = {
                "title": page_data["title"],
                "url": page_data["url"],
                "version": page_data["version"],
                "last_modified": page_data["last_modified"],
                "last_crawled": page_data["crawled_at"],
            }

        # 동기화 통계 기록
        sync_record = {
            "timestamp": datetime.now().isoformat(),
            "type": "full" if self.full_crawl else "incremental",
            **self.stats,
        }

        update_sync_state(
            pages=pages_state,
            sync_record=sync_record,
            is_full_sync=self.full_crawl,
            total_pages=len(pages_state),
        )

        console.print("[green]동기화 상태 업데이트 완료[/green]")

    def _print_summary(self):
        """크롤링 결과 요약 테이블 출력"""
        table = Table(title="크롤링 결과 요약")
        table.add_column("항목", style="cyan")
        table.add_column("건수", justify="right", style="bold")

        table.add_row("신규 추가", str(self.stats["added"]))
        table.add_row("수정됨", str(self.stats["modified"]))
        table.add_row("삭제됨", str(self.stats["deleted"]))
        table.add_row("변경 없음 (건너뜀)", str(self.stats["skipped"]))
        table.add_row("실패", str(self.stats["failed"]))
        table.add_row(
            "총 크롤링",
            str(self.stats["added"] + self.stats["modified"]),
        )

        console.print()
        console.print(table)

    def close(self):
        """브라우저 및 Playwright 리소스 정리"""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def run(self):
        """전체 크롤링 프로세스 실행

        1. 동기화 상태 초기화
        2. Confluence 로그인
        3. 루트 페이지부터 재귀 크롤링
        4. 결과 저장 (JSON + Markdown)
        5. 동기화 상태 업데이트
        6. 결과 요약 출력
        """
        crawl_type = "전체" if self.full_crawl else "증분"
        console.print(f"\n[bold magenta]===== Confluence {crawl_type} 크롤링 시작 =====[/bold magenta]\n")

        start_time = time.time()

        try:
            # 동기화 상태 초기화 (최초 실행 시)
            init_sync_state()

            # 로그인
            self.login()

            # 루트 페이지부터 재귀 크롤링
            console.print(f"\n[bold]루트 페이지: {self.root_page_url}[/bold]\n")
            self.crawl_page(self.root_page_url)

            # 결과 저장
            console.print("\n[bold blue]결과 저장 중...[/bold blue]")
            self.save_results()

            # 동기화 상태 업데이트
            self.update_sync_state()

        except KeyboardInterrupt:
            console.print("\n[yellow]사용자에 의해 크롤링이 중단되었습니다.[/yellow]")

        except Exception as e:
            console.print(f"\n[red]크롤링 중 오류 발생: {e}[/red]")
            raise

        finally:
            # 리소스 정리
            self.close()

            # 소요 시간 계산
            elapsed = time.time() - start_time
            minutes, seconds = divmod(int(elapsed), 60)

            # 결과 요약 출력
            self._print_summary()
            console.print(f"\n[dim]소요 시간: {minutes}분 {seconds}초[/dim]")
            console.print(f"[bold magenta]===== 크롤링 완료 =====[/bold magenta]\n")


# ============================================
# CLI 진입점
# ============================================
if __name__ == "__main__":
    import click

    @click.command()
    @click.option(
        "--full",
        is_flag=True,
        default=False,
        help="전체 크롤링 실행 (기본값: 증분 크롤링)",
    )
    def main(full):
        """Confluence 증분 크롤러

        기본적으로 마지막 동기화 이후 변경된 페이지만 크롤링합니다.
        --full 옵션으로 전체 크롤링을 실행할 수 있습니다.
        """
        crawler = ConfluenceCrawler(full_crawl=full)
        crawler.run()

    main()
