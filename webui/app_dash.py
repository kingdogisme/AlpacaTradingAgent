"""
app_dash.py - Simplified Dash-based web UI for TradingAgents

This is the refactored version of app_dash.py that uses organized modules
for better code structure and maintainability.

RECENT FIX: Multiple Symbol Page Refresh Issue
- Fixed issue where only the first symbol would show after page refresh when analyzing multiple symbols
- The app now stores symbols list in browser storage and restores all symbol pages correctly
- Added safeguards to prevent index out of range errors during pagination
- Users can now refresh the page while analyzing multiple symbols without losing access to all symbol pages
"""

import dash
import dash_bootstrap_components as dbc
from flask import Flask, jsonify, request
from html import escape
import json
import logging
import os

from webui.config.constants import APP_CONFIG, COLORS
from webui.layout import create_main_layout
from webui.callbacks import register_all_callbacks
from tradingagents.alpha_discovery import AlphaDiscoveryService
from tradingagents.alpha_discovery.repository import AlphaDiscoveryRepository


def apply_sequential_mode_fix():
    """Apply fix for sequential execution mode report mapping bug"""
    try:
        from webui.utils.state import AppState
        
        # Check if fix is already applied
        if hasattr(AppState, '_mapping_fix_applied'):
            return True
            
        # Patch the process_chunk_updates method to fix report mapping
        original_process_chunk_updates = AppState.process_chunk_updates
        
        def fixed_process_chunk_updates(self, chunk):
            """Fixed version that correctly maps social analyst reports"""
            
            # 🔍 DEBUG: Log what we're receiving
            current_symbol = getattr(self, 'current_symbol', '')
            if current_symbol:
                state = self.get_state(current_symbol)
                if state:
                    social_status = state["agent_statuses"].get("Social Analyst")
                    if social_status == "in_progress":
                        chunk_fields = list(chunk.keys())
                        # print(f"[DEBUG] Social Analyst chunk received: {chunk_fields}")
                        
                        # Check for the ACTUAL bug: Social Analyst writing to market_report
                        if "market_report" in chunk and "sentiment_report" not in chunk:
                            # print(f"[FIX] 🛑 Detected Social Analyst incorrectly updating market_report - fixing...")
                            # Move the content to the correct field
                            chunk["sentiment_report"] = chunk["market_report"]
                            del chunk["market_report"]
                            # print(f"[FIX] ✅ Corrected: market_report -> sentiment_report")
                        elif "sentiment_report" in chunk:
                            # This is correct - Social Analyst updating sentiment_report
                            sentiment_length = len(chunk["sentiment_report"])
                            # print(f"[DEBUG] ✅ Social Analyst correctly updating sentiment_report ({sentiment_length} chars)")
            
            # Call the original method with the fixed chunk
            return original_process_chunk_updates(self, chunk)
        
        # Apply the patch
        AppState.process_chunk_updates = fixed_process_chunk_updates
        AppState._mapping_fix_applied = True
        return True
        
    except Exception as e:
        print(f"⚠️ Could not apply sequential mode fix: {e}")
        return False


def create_app(base_path: str = "/"):
    """Create and configure the Dash application"""
    
    # Apply the sequential mode fix first
    apply_sequential_mode_fix()
    
    if not base_path:
        base_path = "/"
    if not base_path.startswith("/"):
        base_path = f"/{base_path}"
    if not base_path.endswith("/"):
        base_path = f"{base_path}/"
    
    # Initialize Flask server
    server = Flask(__name__)

    @server.post("/api/v1/n8n/events")
    def ingest_n8n_event():
        expected_token = os.getenv("ALPHADISCOVERY_INGEST_TOKEN")
        auth_header = request.headers.get("Authorization", "")
        if not expected_token or auth_header != f"Bearer {expected_token}":
            return jsonify({"status": "error", "error": "unauthorized"}), 401
        try:
            payload = request.get_json(force=True, silent=False)
            result = AlphaDiscoveryService().ingest_n8n_event(payload or {})
            return jsonify(result), 200
        except ValueError as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400
        except Exception as exc:
            logging.exception("AlphaDiscovery n8n ingest failed")
            return jsonify({"status": "error", "error": str(exc)}), 500

    @server.get("/api/v1/research/articles")
    def list_research_articles():
        repo = _alpha_discovery_repository()
        limit = _int_arg("limit", default=50, minimum=1, maximum=200)
        articles = repo.list_research_articles(
            limit=limit,
            source_id=_str_arg("source_id"),
            article_kind=_str_arg("article_kind"),
            ticker=_str_arg("ticker"),
        )
        return jsonify({"status": "ok", "count": len(articles), "articles": articles}), 200

    @server.get("/api/v1/research/articles/<event_id>")
    def get_research_article(event_id: str):
        article = _alpha_discovery_repository().get_research_article(event_id)
        if not article:
            return jsonify({"status": "error", "error": "not_found"}), 404
        return jsonify({"status": "ok", "article": article}), 200

    @server.get("/alpha-discovery/research")
    def research_articles_page():
        repo = _alpha_discovery_repository()
        limit = _int_arg("limit", default=50, minimum=1, maximum=200)
        articles = repo.list_research_articles(
            limit=limit,
            source_id=_str_arg("source_id"),
            article_kind=_str_arg("article_kind"),
            ticker=_str_arg("ticker"),
        )
        return _render_research_articles_page(articles), 200, {"Content-Type": "text/html; charset=utf-8"}

    # Initialize Dash app with Bootstrap
    app = dash.Dash(
        __name__,
        server=server,
        external_stylesheets=[
            dbc.themes.DARKLY,
            *APP_CONFIG["external_stylesheets"]
        ],
        suppress_callback_exceptions=APP_CONFIG["suppress_callback_exceptions"],
        update_title=APP_CONFIG["update_title"],
        requests_pathname_prefix=base_path,
        routes_pathname_prefix=base_path,
    )

    # Set app title
    app.title = APP_CONFIG["title"]

    # Set the layout
    app.layout = create_main_layout()

    # Register all callbacks
    register_all_callbacks(app)

    return app


def _alpha_discovery_repository() -> AlphaDiscoveryRepository:
    return AlphaDiscoveryService().repository


def _str_arg(name: str) -> str | None:
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _int_arg(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = request.args.get(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _render_research_articles_page(articles: list[dict]) -> str:
    cards = "\n".join(_render_research_article_card(article) for article in articles)
    if not cards:
        cards = "<section class='empty'>No research articles stored yet.</section>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AlphaDiscovery Research Evidence</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #111417;
      --panel: #171c20;
      --panel-2: #1f262b;
      --text: #eef2f4;
      --muted: #9daab2;
      --line: #2e3941;
      --accent: #62c4a5;
      --warn: #e5b567;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    header {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 16px;
      margin-bottom: 18px;
    }}
    h1 {{
      font-size: 24px;
      margin: 0 0 4px;
      letter-spacing: 0;
    }}
    .muted {{ color: var(--muted); }}
    .filters {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 16px 0 20px;
    }}
    .filters a, .api-link {{
      color: var(--text);
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 6px 10px;
      border-radius: 6px;
      text-decoration: none;
    }}
    .article {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 16px;
      margin-bottom: 14px;
    }}
    .article h2 {{
      font-size: 18px;
      line-height: 1.35;
      margin: 0 0 8px;
      letter-spacing: 0;
    }}
    .article h2 a {{ color: var(--text); text-decoration: none; }}
    .meta, .chips, .grid {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .meta {{ color: var(--muted); margin-bottom: 10px; }}
    .chip {{
      border: 1px solid var(--line);
      background: var(--panel-2);
      border-radius: 999px;
      padding: 2px 8px;
      color: var(--text);
    }}
    .chip.accent {{ color: var(--accent); }}
    .chip.warn {{ color: var(--warn); }}
    .summary {{
      margin: 12px 0;
      color: #dce3e7;
      white-space: pre-wrap;
    }}
    .section-title {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      margin: 12px 0 4px;
    }}
    .impacts {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 8px;
    }}
    .impact {{
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
    }}
    pre {{
      overflow-x: auto;
      background: #0c0f11;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      color: #cbd5da;
    }}
    .empty {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
      color: var(--muted);
      background: var(--panel);
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>AlphaDiscovery Research Evidence</h1>
        <div class="muted">n8n/Substack research articles stored as structured SourceSignal evidence.</div>
      </div>
      <a class="api-link" href="/api/v1/research/articles?limit=50">JSON API</a>
    </header>
    <nav class="filters">
      <a href="/alpha-discovery/research">All</a>
      <a href="/alpha-discovery/research?article_kind=single_ticker_dd">Single Ticker DD</a>
      <a href="/alpha-discovery/research?article_kind=thematic_dd">Thematic DD</a>
      <a href="/alpha-discovery/research?article_kind=news_digest">News Digest</a>
    </nav>
    {cards}
  </main>
</body>
</html>"""


def _render_research_article_card(article: dict) -> str:
    enriched = article.get("enriched") or {}
    title = escape(str(article.get("article_title") or "Untitled"))
    url = escape(str(article.get("article_canonical_url") or "#"))
    source_name = escape(str(article.get("source_name") or article.get("source_id") or "unknown"))
    published_at = escape(str(article.get("article_published_at") or ""))
    kind = escape(str(enriched.get("article_kind") or "unknown"))
    quality = enriched.get("evidence_quality")
    priority = enriched.get("priority_score")
    summary = escape(str(article.get("summary_zh") or article.get("article_excerpt") or ""))
    primary = _chips(enriched.get("primary_tickers") or [], css="accent")
    secondary = _chips(enriched.get("secondary_tickers") or [])
    themes = _chips(enriched.get("themes") or [])
    watch_items = _chips(article.get("watch_items") or [], css="warn")
    linked = _chips(article.get("linked_candidate_tickers") or [], css="accent")
    impacts = "\n".join(_render_impact(impact) for impact in enriched.get("candidate_impacts") or [])
    if not impacts:
        impacts = "<div class='muted'>No candidate impact generated.</div>"
    return f"""<article class="article">
  <h2><a href="{url}" target="_blank" rel="noreferrer">{title}</a></h2>
  <div class="meta">
    <span>{source_name}</span>
    <span>{published_at}</span>
    <span>{kind}</span>
    <span>quality: {_fmt_score(quality)}</span>
    <span>priority: {_fmt_score(priority)}</span>
  </div>
  <div class="summary">{summary}</div>
  <div class="section-title">Primary Tickers</div>
  <div class="chips">{primary or "<span class='muted'>None</span>"}</div>
  <div class="section-title">Secondary Tickers</div>
  <div class="chips">{secondary or "<span class='muted'>None</span>"}</div>
  <div class="section-title">Themes</div>
  <div class="chips">{themes or "<span class='muted'>None</span>"}</div>
  <div class="section-title">Watch Items</div>
  <div class="chips">{watch_items or "<span class='muted'>None</span>"}</div>
  <div class="section-title">Linked Candidates</div>
  <div class="chips">{linked or "<span class='muted'>None</span>"}</div>
  <div class="section-title">Candidate Impacts</div>
  <div class="impacts">{impacts}</div>
</article>"""


def _render_impact(impact: dict) -> str:
    explanation = impact.get("explanation")
    if not explanation:
        explanation = json.dumps(impact, ensure_ascii=False, sort_keys=True)
    return f"""<div class="impact">
  <strong>{escape(str(impact.get("ticker") or "unknown"))}</strong>
  <div class="muted">role: {escape(str(impact.get("role") or ""))} · boost: {_fmt_score(impact.get("research_boost"))} · max tier: {escape(str(impact.get("max_tier") or ""))}</div>
  <div>{escape(str(explanation))}</div>
</div>"""


def _chips(values: list, *, css: str = "") -> str:
    class_name = f"chip {css}".strip()
    return "".join(f"<span class='{class_name}'>{escape(str(value))}</span>" for value in values if value)


def _fmt_score(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def run_app(port=7860, share=False, server_name="127.0.0.1", debug=False, max_threads=1, base_path="/"):
    """Run the TradingAgents Dash Web UI"""
    
    # Create the app
    app = create_app(base_path=base_path)
    
    if debug:
        print(f"Starting TradingAgents Dash Web UI on port {port}...")
    else:
        print("Starting TradingAgents Web UI...")
    
    # Suppress verbose HTTP request logs from Werkzeug
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    # Optionally also silence Dash's callback exceptions logger
    logging.getLogger("dash.callback").setLevel(logging.ERROR)
    
    # Run the app
    app.run(
        port=port,
        host=server_name,
        debug=debug,
        dev_tools_hot_reload=debug,
        use_reloader=False  # Disable reloader to prevent double-start in debug mode
    )
    
    return 0


# Create the app instance for use by other modules
app = create_app()

if __name__ == "__main__":
    run_app(debug=True)
