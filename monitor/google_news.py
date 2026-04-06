import logging
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

from monitor.filter import is_relevant, is_within_days

logger = logging.getLogger(__name__)

BASE_URL = "https://news.google.com/rss/search"

QUERIES = [
    {"q": "neo battery materials", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"q": "네오배터리머티리얼즈", "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_news(days: int = 7) -> list[dict]:
    seen_guids: set[str] = set()
    all_items: list[dict] = []

    for params in QUERIES:
        for item in _fetch_query(params):
            if item["guid"] not in seen_guids:
                seen_guids.add(item["guid"])
                all_items.append(item)

    filtered = [item for item in all_items if is_relevant(item["title"], item["description"])]
    filtered = [item for item in filtered if is_within_days(item["pub_date"], days=days)]
    logger.info("Google News: %d articles fetched, %d passed filter", len(all_items), len(filtered))
    return filtered


def _fetch_query(params: dict) -> list[dict]:
    try:
        resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning("Google News fetch failed for query '%s': %s", params.get("q"), e)
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.warning("Google News XML parse error: %s", e)
        return []

    items = []
    for item_el in root.iter("item"):
        title = _text(item_el, "title")
        link = _text(item_el, "link")
        guid = _text(item_el, "guid") or link
        pub_date = _text(item_el, "pubDate")
        description = _text(item_el, "description")

        if not guid:
            continue

        # Convert RFC 2822 pubDate ("Sun, 06 Apr 2026 12:00:00 GMT") to ISO for filter.py
        if pub_date:
            try:
                pub_date = parsedate_to_datetime(pub_date).isoformat()
            except Exception:
                pass

        items.append({
            "guid": guid,
            "title": title,
            "link": link,
            "pub_date": pub_date,
            "description": description,
        })

    logger.info("Google News query '%s': %d results", params.get("q"), len(items))
    return items


def _text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""
