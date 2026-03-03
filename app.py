"""
Flask 웹 서버

Confluence RAG 검색 시스템의 REST API와 웹 UI를 제공합니다.
검색 기록 저장, 페이지 보고서 생성 기능을 포함합니다.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request
from rich.console import Console

from rag_search import ConfluenceRAG

load_dotenv()

console = Console()
app = Flask(__name__)


# ============================================
# 내부 성능 캐시 (투명, UI 미노출)
# ============================================
class _TTLCache:
    """동일 질문 반복 시 LLM 호출을 생략하는 인메모리 캐시"""

    def __init__(self, ttl: int = 3600, max_size: int = 100):
        self._data: dict[str, tuple] = {}
        self._ttl = ttl
        self._max_size = max_size

    def _key(self, query: str, k: int) -> str:
        return f"{query.strip().lower()}|{k}"

    def get(self, query: str, k: int = 5) -> dict | None:
        key = self._key(query, k)
        if key in self._data:
            value, expiry = self._data[key]
            if time.time() < expiry:
                return value
            del self._data[key]
        return None

    def set(self, query: str, k: int, result: dict):
        if len(self._data) >= self._max_size:
            oldest = min(self._data, key=lambda k: self._data[k][1])
            del self._data[oldest]
        self._data[self._key(query, k)] = (result, time.time() + self._ttl)


_cache = _TTLCache(
    ttl=int(os.getenv("CACHE_TTL", "3600")),
    max_size=int(os.getenv("CACHE_MAX_SIZE", "100")),
)


# ============================================
# 검색 기록 (파일 영속 저장)
# ============================================
class SearchHistory:
    """검색 기록을 JSON 파일에 영속적으로 저장/조회합니다."""

    def __init__(self, path: str = "search_history.json", max_entries: int = 200):
        self._path = Path(path)
        self._max_entries = max_entries
        self._history: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self):
        self._path.write_text(
            json.dumps(self._history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, query: str, answer_preview: str, sources: list[dict]):
        # 같은 질문이 이미 있으면 제거 후 맨 앞에 추가 (최신 결과 반영)
        self._history = [h for h in self._history if h["query"] != query]
        self._history.insert(0, {
            "query": query,
            "preview": answer_preview[:120].replace("\n", " "),
            "sources": [{"title": s["title"], "url": s["url"]} for s in sources[:3]],
            "searched_at": datetime.now().isoformat(),
        })
        if len(self._history) > self._max_entries:
            self._history = self._history[:self._max_entries]
        self._save()

    def get_all(self) -> list[dict]:
        return self._history

    def clear(self):
        self._history = []
        if self._path.exists():
            self._path.unlink()


search_history = SearchHistory(
    path=os.getenv("HISTORY_FILE", "search_history.json"),
    max_entries=int(os.getenv("HISTORY_MAX_ENTRIES", "200")),
)


# ============================================
# RAG 엔진 (지연 초기화)
# ============================================
_rag_engine: ConfluenceRAG | None = None


def get_rag() -> ConfluenceRAG | None:
    global _rag_engine
    if _rag_engine is not None:
        return _rag_engine
    try:
        console.print("[blue]RAG 시스템 초기화 중...[/blue]")
        _rag_engine = ConfluenceRAG()
        console.print("[green]RAG 시스템 준비 완료[/green]")
    except FileNotFoundError:
        console.print("[red]벡터 DB가 존재하지 않습니다.[/red]")
    except ConnectionError:
        console.print("[red]Ollama 서버에 연결할 수 없습니다.[/red]")
    except Exception as e:
        console.print(f"[red]RAG 시스템 초기화 실패: {e}[/red]")
    return _rag_engine


# ============================================
# 보고서 생성
# ============================================
REPORT_PROMPT_TEMPLATE = """다음은 Confluence에서 가져온 문서들의 내용입니다:

{content}

위 문서들을 바탕으로 {report_type_label} 보고서를 한국어로 작성해주세요.

다음 형식으로 작성해주세요:

# 보고서 제목

## 개요
(이 보고서에서 다루는 주제와 목적 요약)

## 주요 내용
(각 문서의 핵심 내용 정리)

## 종합 분석
(전체적인 분석 및 인사이트)

## 결론
(요약 및 권장 사항)

명확하고 간결하게 작성해주세요."""

REPORT_TYPE_LABELS = {
    "summary": "요약",
    "detailed": "상세",
    "comparison": "비교 분석",
}


def _collect_pages_content(urls: list[str]) -> list[dict]:
    """URL 목록에 해당하는 페이지 내용 수집"""
    pages = []
    found_urls: set[str] = set()

    # 1. 백업 JSON에서 검색
    backup_file = Path("confluence_backup.json")
    if backup_file.exists():
        try:
            data = json.loads(backup_file.read_text(encoding="utf-8"))
            by_url = {p["url"]: p for p in data.get("pages", [])}
            for url in urls:
                if url in by_url:
                    p = by_url[url]
                    pages.append({
                        "title": p["title"],
                        "url": url,
                        "content": p["content"][:4000],
                    })
                    found_urls.add(url)
        except Exception:
            pass

    # 2. ChromaDB에서 URL 메타데이터 필터로 검색
    rag = _rag_engine
    if rag:
        for url in urls:
            if url in found_urls:
                continue
            try:
                result = rag.collection.get(where={"url": {"$eq": url}})
                if result and result["documents"]:
                    title = (
                        result["metadatas"][0].get("title", "제목 없음")
                        if result["metadatas"] else "제목 없음"
                    )
                    pages.append({
                        "title": title,
                        "url": url,
                        "content": "\n\n".join(result["documents"][:5]),
                    })
                    found_urls.add(url)
            except Exception:
                pass

    return pages


def generate_report(urls: list[str], report_type: str) -> dict:
    """특정 페이지들을 보고서 형식으로 변환"""
    rag = get_rag()
    if not rag:
        raise RuntimeError("RAG 시스템이 초기화되지 않았습니다.")

    pages = _collect_pages_content(urls)
    if not pages:
        return {
            "error": "지정한 URL의 페이지를 찾을 수 없습니다. 크롤링 후 다시 시도해주세요.",
            "urls": urls,
        }

    content_text = "\n\n---\n\n".join(
        f"### {p['title']}\n출처: {p['url']}\n\n{p['content']}"
        for p in pages
    )
    report_type_label = REPORT_TYPE_LABELS.get(report_type, "요약")
    prompt = REPORT_PROMPT_TEMPLATE.format(
        content=content_text,
        report_type_label=report_type_label,
    )
    report_text = rag.llm.invoke(prompt)

    return {
        "report": report_text.strip(),
        "pages": [{"title": p["title"], "url": p["url"]} for p in pages],
        "report_type": report_type,
        "generated_at": datetime.now().isoformat(),
    }


# ============================================
# HTML 템플릿
# ============================================
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Confluence AI 검색</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f0f2f5; color: #333; }
    .container { max-width: 900px; margin: 0 auto; padding: 24px 16px; }
    h1 { text-align: center; padding: 20px 0 24px; color: #1a73e8; font-size: 1.8em; }
    .tabs { display: flex; gap: 4px; border-bottom: 2px solid #1a73e8; margin-bottom: 20px; }
    .tab { padding: 10px 22px; cursor: pointer; border: none; background: none;
           font-size: 14px; color: #555; border-radius: 4px 4px 0 0; transition: 0.2s; }
    .tab:hover { background: #e8f0fe; color: #1a73e8; }
    .tab.active { background: #1a73e8; color: white; }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .card { background: white; border-radius: 10px; padding: 20px;
            margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
    .search-row { display: flex; gap: 8px; }
    input[type=text], textarea, select {
      padding: 10px 14px; border: 1px solid #ddd; border-radius: 6px;
      font-size: 14px; font-family: inherit; outline: none; transition: 0.2s; }
    input[type=text]:focus, textarea:focus { border-color: #1a73e8; }
    input[type=text] { flex: 1; }
    textarea { width: 100%; height: 130px; resize: vertical; }
    button.primary { padding: 10px 22px; background: #1a73e8; color: white;
                     border: none; border-radius: 6px; cursor: pointer;
                     font-size: 14px; white-space: nowrap; transition: 0.2s; }
    button.primary:hover { background: #1558b0; }
    button.danger { padding: 8px 16px; background: #d32f2f; color: white;
                    border: none; border-radius: 6px; cursor: pointer; font-size: 13px; }
    button.danger:hover { background: #b71c1c; }
    button.ghost { padding: 6px 12px; background: none; color: #888;
                   border: 1px solid #ddd; border-radius: 6px; cursor: pointer;
                   font-size: 12px; transition: 0.2s; }
    button.ghost:hover { background: #f5f5f5; color: #333; }
    .answer { white-space: pre-wrap; line-height: 1.7; font-size: 14px; }
    .sources { margin-top: 14px; padding-top: 12px; border-top: 1px solid #eee; }
    .source-item { padding: 5px 0; font-size: 13px; }
    .source-item a { color: #1a73e8; text-decoration: none; }
    .source-item a:hover { text-decoration: underline; }
    .loading { color: #888; font-style: italic; padding: 14px 0; }
    .error-msg { color: #c62828; padding: 10px; background: #ffebee;
                 border-radius: 6px; font-size: 14px; }
    .meta { color: #888; font-size: 12px; margin-top: 10px; }
    .report-content { white-space: pre-wrap; line-height: 1.7; font-size: 14px; }
    .flex-row { display: flex; gap: 10px; align-items: center; margin-top: 12px; }
    .section-label { font-weight: 600; margin-bottom: 10px; color: #444; }
    .hint { font-size: 12px; color: #888; margin-top: 6px; }

    /* 검색 기록 */
    .history-header { display: flex; justify-content: space-between; align-items: center;
                      margin-bottom: 12px; }
    .history-count { font-size: 13px; color: #888; }
    .history-list { display: flex; flex-direction: column; gap: 8px; }
    .history-item { display: flex; align-items: flex-start; gap: 10px; padding: 12px;
                    border: 1px solid #eee; border-radius: 8px; cursor: pointer;
                    transition: 0.15s; background: #fafafa; }
    .history-item:hover { border-color: #1a73e8; background: #e8f0fe; }
    .history-icon { font-size: 16px; flex-shrink: 0; margin-top: 2px; }
    .history-body { flex: 1; min-width: 0; }
    .history-query { font-size: 14px; font-weight: 500; color: #222;
                     white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .history-preview { font-size: 12px; color: #777; margin-top: 3px;
                       white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .history-time { font-size: 11px; color: #aaa; flex-shrink: 0; white-space: nowrap; }
    .history-empty { text-align: center; color: #aaa; padding: 40px 0; font-size: 14px; }
  </style>
</head>
<body>
<div class="container">
  <h1>🔍 Confluence AI 검색</h1>

  <div class="tabs">
    <button class="tab active" onclick="switchTab('search', this)">검색</button>
    <button class="tab" onclick="switchTab('report', this)">보고서 생성</button>
    <button class="tab" onclick="switchTab('history', this)">검색 기록</button>
  </div>

  <!-- 검색 탭 -->
  <div id="tab-search" class="tab-content active">
    <div class="card">
      <div class="search-row">
        <input type="text" id="query" placeholder="궁금한 내용을 질문해주세요..." onkeypress="if(event.key==='Enter')doSearch()">
        <button class="primary" onclick="doSearch()">검색</button>
      </div>
      <p class="hint">Enter 키 또는 검색 버튼을 클릭하세요.</p>
    </div>
    <div id="search-result"></div>
  </div>

  <!-- 보고서 탭 -->
  <div id="tab-report" class="tab-content">
    <div class="card">
      <p class="section-label">페이지 URL을 한 줄씩 입력하세요 (최대 10개)</p>
      <textarea id="report-urls" placeholder="https://your-company.atlassian.net/wiki/.../pages/12345/Page-Title
https://your-company.atlassian.net/wiki/.../pages/67890/Another-Page"></textarea>
      <div class="flex-row">
        <select id="report-type">
          <option value="summary">요약 보고서</option>
          <option value="detailed">상세 보고서</option>
          <option value="comparison">비교 분석</option>
        </select>
        <button class="primary" onclick="doReport()">보고서 생성</button>
      </div>
      <p class="hint">크롤링된 페이지만 보고서로 변환할 수 있습니다.</p>
    </div>
    <div id="report-result"></div>
  </div>

  <!-- 검색 기록 탭 -->
  <div id="tab-history" class="tab-content">
    <div class="card">
      <div class="history-header">
        <span class="section-label">최근 검색 기록</span>
        <div style="display:flex;gap:8px;align-items:center">
          <span class="history-count" id="history-count"></span>
          <button class="danger" onclick="clearHistory()">기록 삭제</button>
        </div>
      </div>
      <div id="history-list" class="history-list">
        <div class="history-empty">검색 기록이 없습니다.</div>
      </div>
    </div>
  </div>
</div>

<script>
  function switchTab(name, btn) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + name).classList.add('active');
    if (name === 'history') loadHistory();
  }

  async function doSearch(query) {
    query = query || document.getElementById('query').value.trim();
    if (!query) return;
    document.getElementById('query').value = query;

    // 검색 탭으로 이동
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelector('.tab').classList.add('active');
    document.getElementById('tab-search').classList.add('active');

    const el = document.getElementById('search-result');
    el.innerHTML = '<div class="card"><p class="loading">검색 중...</p></div>';

    try {
      const resp = await fetch('/api/search', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query, k: 5})
      });
      const data = await resp.json();
      if (!resp.ok) {
        el.innerHTML = `<div class="card"><p class="error-msg">오류: ${data.error}</p></div>`;
        return;
      }
      const sources = (data.sources || []).map((s, i) =>
        `<div class="source-item">${i+1}. <a href="${s.url}" target="_blank">${esc(s.title)}</a> <span style="color:#aaa">(관련도: ${Math.round(s.relevance*100)}%)</span></div>`
      ).join('');
      el.innerHTML = `
        <div class="card">
          <div style="margin-bottom:12px"><strong>답변</strong></div>
          <div class="answer">${esc(data.answer)}</div>
          ${sources ? `<div class="sources"><strong>참고 문서</strong>${sources}</div>` : ''}
          <div class="meta">소요 시간: ${data.elapsed}초</div>
        </div>`;
    } catch(e) {
      el.innerHTML = `<div class="card"><p class="error-msg">연결 오류: ${e.message}</p></div>`;
    }
  }

  async function doReport() {
    const text = document.getElementById('report-urls').value.trim();
    if (!text) { alert('URL을 입력해주세요.'); return; }
    const urls = text.split('\n').map(u => u.trim()).filter(u => u);
    const reportType = document.getElementById('report-type').value;
    const el = document.getElementById('report-result');
    el.innerHTML = '<div class="card"><p class="loading">보고서 생성 중... (시간이 걸릴 수 있습니다)</p></div>';
    try {
      const resp = await fetch('/api/report', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({urls, report_type: reportType})
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        el.innerHTML = `<div class="card"><p class="error-msg">오류: ${data.error}</p></div>`;
        return;
      }
      const pageList = data.pages.map(p =>
        `<div class="source-item"><a href="${p.url}" target="_blank">${esc(p.title)}</a></div>`
      ).join('');
      el.innerHTML = `
        <div class="card">
          <div class="sources" style="margin-bottom:14px"><strong>포함된 페이지</strong>${pageList}</div>
          <div class="report-content">${esc(data.report)}</div>
          <div class="meta">생성 일시: ${data.generated_at}</div>
        </div>`;
    } catch(e) {
      el.innerHTML = `<div class="card"><p class="error-msg">연결 오류: ${e.message}</p></div>`;
    }
  }

  async function loadHistory() {
    try {
      const resp = await fetch('/api/history');
      const data = await resp.json();
      const list = document.getElementById('history-list');
      const count = document.getElementById('history-count');
      if (!data.length) {
        list.innerHTML = '<div class="history-empty">검색 기록이 없습니다.</div>';
        count.textContent = '';
        return;
      }
      count.textContent = `${data.length}개`;
      list.innerHTML = data.map(h => `
        <div class="history-item" onclick="doSearch(${JSON.stringify(h.query)})">
          <div class="history-icon">🔍</div>
          <div class="history-body">
            <div class="history-query">${esc(h.query)}</div>
            ${h.preview ? `<div class="history-preview">${esc(h.preview)}</div>` : ''}
          </div>
          <div class="history-time">${formatTime(h.searched_at)}</div>
        </div>`
      ).join('');
    } catch(e) {
      document.getElementById('history-list').innerHTML =
        '<div class="history-empty">기록을 불러올 수 없습니다.</div>';
    }
  }

  async function clearHistory() {
    if (!confirm('검색 기록을 모두 삭제하시겠습니까?')) return;
    await fetch('/api/history', {method: 'DELETE'});
    loadHistory();
  }

  function formatTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60) return '방금 전';
    if (diff < 3600) return `${Math.floor(diff/60)}분 전`;
    if (diff < 86400) return `${Math.floor(diff/3600)}시간 전`;
    return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  }

  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
</script>
</body>
</html>"""


# ============================================
# API 라우트
# ============================================
@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json() or {}
    query = data.get("query", "").strip()
    k = min(int(data.get("k", 5)), 20)

    if not query:
        return jsonify({"error": "query 파라미터가 필요합니다."}), 400
    if len(query) > 500:
        return jsonify({"error": "질문은 500자 이내로 입력해주세요."}), 400
    if len(query) < 2:
        return jsonify({"error": "더 구체적으로 질문해주세요."}), 400

    # 내부 캐시 확인 (투명)
    cached = _cache.get(query, k)
    if cached:
        return jsonify(cached)

    rag = get_rag()
    if not rag:
        return jsonify({"error": "RAG 시스템이 준비되지 않았습니다. 벡터 DB를 먼저 구축해주세요."}), 503

    try:
        result = rag.search(query, k=k)
        _cache.set(query, k, result)

        # 검색 기록 저장
        search_history.add(
            query=query,
            answer_preview=result.get("answer", ""),
            sources=result.get("sources", []),
        )

        return jsonify(result)
    except ConnectionError:
        return jsonify({"error": "Ollama 서버에 연결할 수 없습니다."}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/history", methods=["GET"])
def api_history_get():
    return jsonify(search_history.get_all())


@app.route("/api/history", methods=["DELETE"])
def api_history_clear():
    search_history.clear()
    return jsonify({"message": "검색 기록이 삭제되었습니다."})


@app.route("/api/report", methods=["POST"])
def api_report():
    data = request.get_json() or {}
    urls = data.get("urls", [])
    report_type = data.get("report_type", "summary")

    if not urls:
        return jsonify({"error": "urls 파라미터가 필요합니다."}), 400
    if len(urls) > 10:
        return jsonify({"error": "최대 10개 URL만 처리 가능합니다."}), 400
    if report_type not in REPORT_TYPE_LABELS:
        return jsonify({"error": f"report_type은 {list(REPORT_TYPE_LABELS.keys())} 중 하나여야 합니다."}), 400

    try:
        result = generate_report(urls, report_type)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "rag_ready": _rag_engine is not None,
        "history_entries": len(search_history.get_all()),
    })


# ============================================
# 메인 실행
# ============================================
if __name__ == "__main__":
    get_rag()

    port = int(os.getenv("SERVER_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    console.print(f"\n[bold magenta]===== Confluence AI 검색 서버 시작 =====[/bold magenta]")
    console.print(f"[green]http://localhost:{port}[/green]\n")

    app.run(host="0.0.0.0", port=port, debug=debug)
