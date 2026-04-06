import hashlib
import html
import logging
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

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
    "Directors & Officers": "https://neobatterymaterials.com/directors-officers-advisors/",
    "Technology":           "https://neobatterymaterials.com/technology/",
    "Battery Foundry":      "https://neobatterymaterials.com/battery-foundry/",
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

    logger.info("NBM news releases: %d items fetched", len(items))
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

    logger.info("NBM media coverage: %d items fetched", len(items))
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

def _page_text_hash(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning("NBM page fetch failed (%s): %s", url, e)
        return None

    soup = BeautifulSoup(resp.content, "html.parser")

    # Remove scripts, styles, and noscript tags
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Try to get main content area; fall back to body
    content = soup.find("main") or soup.find("div", class_=re.compile(r"e-con")) or soup.body
    if not content:
        return None

    text = content.get_text(separator=" ")
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def check_page_changes(seen_hashes: dict) -> list[dict]:
    """
    Compare current page hashes against stored hashes.
    On first run (url not in seen_hashes), stores the baseline — no alert.
    Returns list of changed pages (same dict shape as news items).
    Mutates seen_hashes in-place so caller can persist the updated state.
    """
    changed = []
    now = datetime.now(timezone.utc).isoformat()

    for name, url in WATCHED_PAGES.items():
        current_hash = _page_text_hash(url)
        if current_hash is None:
            continue

        stored = seen_hashes.get(url)
        if stored is None:
            # First run: store baseline, no alert
            seen_hashes[url] = {"hash": current_hash, "first_seen": now}
            logger.info("NBM page baseline stored: %s", name)
        elif stored["hash"] != current_hash:
            # Content changed
            seen_hashes[url] = {"hash": current_hash, "first_seen": now}
            logger.info("NBM page changed: %s", name)
            changed.append({
                "guid": url,
                "title": f"페이지 변경 감지: {name}",
                "link": url,
                "pub_date": now[:10],
                "description": "",
            })
        else:
            logger.info("NBM page unchanged: %s", name)

    return changed
