import difflib
import hashlib
import html
import logging
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from monitor.filter import is_within_days

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

NEWS_RELEASES_API = "https://neobatterymaterials.com/wp-json/pad-news/v1/releases/"
MEDIA_COVERAGE_URL = "https://neobatterymaterials.com/investor-relations/media-coverage/"

WATCHED_PAGES = {
    "Directors & Officers":          "https://neobatterymaterials.com/directors-officers-advisors/",
    "Technology":                    "https://neobatterymaterials.com/technology/",
    "Battery Foundry":               "https://neobatterymaterials.com/battery-foundry/",
    "NBMSiDE Commercialization":     "https://neobatterymaterials.com/nbmside-commercialization-pathway/",
    "About":                         "https://neobatterymaterials.com/about/",
}


# ---------------------------------------------------------------------------
# Part 1: New content (news releases + media coverage)
# ---------------------------------------------------------------------------

def fetch_news_releases() -> list[dict]:
    try:
        resp = requests.get(NEWS_RELEASES_API, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning("NBM news releases fetch failed: %s", e)
        return []

    items = []
    for raw in resp.json().get("items", []):
        permalink = raw.get("permalink", "")
        title = raw.get("title", "")
        if not permalink or not title:
            continue
        items.append({
            "guid": permalink,
            "title": html.unescape(title),
            "link": permalink,
            "pub_date": raw.get("date", ""),
            "description": "",
        })

    items = [item for item in items if is_within_days(item["pub_date"], days=7)]
    logger.info("NBM news releases: %d items within 7 days", len(items))
    return items


def fetch_media_coverage() -> list[dict]:
    try:
        resp = requests.get(MEDIA_COVERAGE_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning("NBM media coverage fetch failed: %s", e)
        return []

    soup = BeautifulSoup(resp.content, "html.parser")
    items = []

    for article in soup.find_all("article", class_="media_coverage"):
        title_tag = article.find("h4", class_="entry-title")
        if not title_tag:
            continue
        link_tag = title_tag.find("a")
        if not link_tag:
            continue

        title = link_tag.get_text(strip=True)
        link = link_tag.get("href", "")
        if not title or not link:
            continue

        date = ""
        date_a = article.find("a", class_="pix-post-meta-date")
        if date_a:
            date_span = date_a.find("span", class_="text-body-default")
            if date_span:
                date = date_span.get_text(strip=True)

        items.append({
            "guid": link,
            "title": title,
            "link": link,
            "pub_date": date,
            "description": "",
        })

    items = [item for item in items if is_within_days(item["pub_date"], days=7)]
    logger.info("NBM media coverage: %d items within 7 days", len(items))
    return items


def fetch_new_content() -> list[dict]:
    seen_guids: set[str] = set()
    combined = []
    for item in fetch_news_releases() + fetch_media_coverage():
        if item["guid"] not in seen_guids:
            seen_guids.add(item["guid"])
            combined.append(item)
    return combined


# ---------------------------------------------------------------------------
# Part 2: Page change detection (hash-based)
# ---------------------------------------------------------------------------

# Patterns that indicate a Cloudflare / bot-check interstitial page
_CF_PATTERNS = re.compile(
    r"(please\s+wait|just\s+a\s+moment|checking\s+your\s+browser|verif(y|ying|ication)|ray\s+id|cloudflare)",
    re.I,
)


def _extract_page_text(url: str) -> str | None:
    """Playwright으로 JS 렌더링된 페이지에서 동적 노이즈를 제거한 정규화 텍스트를 반환한다.

    Cloudflare 봇 방지 인터스티셜이 감지되면 None을 반환하여 오탐을 방지한다.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
            )
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=20000)
            except PlaywrightTimeoutError:
                logger.warning("NBM page load timed out (%s), using partial content", url)

            html_content = page.content()
            page.close()
            browser.close()
    except Exception as e:
        logger.warning("NBM page fetch failed (%s): %s", url, e)
        return None

    soup = BeautifulSoup(html_content, "html.parser")

    # Detect Cloudflare / bot-check interstitial before processing
    raw_text_preview = soup.get_text(" ", strip=True)[:500]
    if _CF_PATTERNS.search(raw_text_preview):
        logger.warning("NBM page appears to be a bot-check / Cloudflare page (%s) — skipping", url)
        return None

    # Remove noisy/dynamic elements that change on every request
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    # Remove cookie consent banners and popups
    for tag in soup.find_all(True, class_=re.compile(
        r"(cookie|consent|popup|modal|banner|notice|gdpr|overlay)", re.I
    )):
        tag.decompose()

    # Try to get main content area; fall back to body
    content = soup.find("main") or soup.find("div", class_=re.compile(r"e-con")) or soup.body
    if not content:
        return None

    # Line-by-line extraction for diffable output
    lines = [l.strip() for l in content.get_text(separator="\n").splitlines()]
    text = "\n".join(l for l in lines if l)
    # Remove standalone year-like numbers (e.g. copyright year "© 2026")
    text = re.sub(r"©\s*\d{4}", "", text)
    # Remove ISO-style timestamps and date strings that auto-update
    text = re.sub(r"\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?", "", text)
    return text


def _text_to_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _build_diff_html(old_text: str, new_text: str, max_lines: int = 60) -> str:
    """두 텍스트의 diff를 HTML 형식으로 반환한다."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=2))

    if not diff:
        return ""

    # 너무 길면 잘라냄
    if len(diff) > max_lines:
        diff = diff[:max_lines]
        diff.append(f"... (이하 {len(diff) - max_lines}줄 생략)")

    rows = []
    for line in diff:
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            rows.append(
                f'<tr><td style="background:#ffeef0;color:#b31d28;padding:2px 8px;'
                f'font-family:monospace;font-size:12px;white-space:pre-wrap;">'
                f'− {html.escape(line[1:])}</td></tr>'
            )
        elif line.startswith("+"):
            rows.append(
                f'<tr><td style="background:#e6ffed;color:#22863a;padding:2px 8px;'
                f'font-family:monospace;font-size:12px;white-space:pre-wrap;">'
                f'+ {html.escape(line[1:])}</td></tr>'
            )
        elif line.startswith("@@"):
            rows.append(
                f'<tr><td style="background:#f1f8ff;color:#0366d6;padding:2px 8px;'
                f'font-family:monospace;font-size:11px;">{html.escape(line)}</td></tr>'
            )
        else:
            rows.append(
                f'<tr><td style="padding:2px 8px;font-family:monospace;font-size:12px;'
                f'white-space:pre-wrap;color:#555;">{html.escape(line)}</td></tr>'
            )

    if not rows:
        return ""
    return '<table style="width:100%;border-collapse:collapse;border:1px solid #ddd;border-radius:4px;overflow:hidden;">' + "".join(rows) + "</table>"


def check_page_changes(seen_hashes: dict) -> list[dict]:
    """
    Compare current page hashes against stored hashes.
    On first run (url not in seen_hashes), stores the baseline — no alert.
    Returns list of changed pages with diff_html field for email rendering.
    Mutates seen_hashes in-place so caller can persist the updated state.
    """
    changed = []
    now = datetime.now(timezone.utc).isoformat()

    for name, url in WATCHED_PAGES.items():
        current_text = _extract_page_text(url)
        if current_text is None:
            continue

        current_hash = _text_to_hash(current_text)
        stored = seen_hashes.get(url)

        if stored is None:
            # First run: store baseline, no alert
            seen_hashes[url] = {"hash": current_hash, "text": current_text, "first_seen": now}
            logger.info("NBM page baseline stored: %s", name)
        elif stored["hash"] != current_hash:
            # Content changed — build diff
            old_text = stored.get("text", "")
            diff_html = _build_diff_html(old_text, current_text)
            seen_hashes[url] = {"hash": current_hash, "text": current_text, "first_seen": now}
            logger.info("NBM page changed: %s", name)
            changed.append({
                "guid": url,
                "title": f"페이지 변경 감지: {name}",
                "link": url,
                "pub_date": now[:10],
                "description": "",
                "diff_html": diff_html,
            })
        else:
            logger.info("NBM page unchanged: %s", name)

    return changed
