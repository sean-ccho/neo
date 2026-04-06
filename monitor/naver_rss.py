import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from monitor.filter import is_relevant

logger = logging.getLogger(__name__)

NAVER_NEWS_RSS = "https://search.naver.com/search.naver?where=rss&query=네오배터리"
NAVER_GENERAL_RSS = "https://search.naver.com/search.naver?where=rss&query=네오배터리머티리얼즈"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def fetch_feed(url: str, timeout: int = 15) -> list[dict]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            logger.warning("Naver rate limited (429), skipping: %s", url)
        else:
            logger.warning("HTTP error fetching Naver feed %s: %s", url, e)
        return []
    except requests.exceptions.RequestException as e:
        logger.warning("Network error fetching Naver feed %s: %s", url, e)
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.warning("Failed to parse RSS XML from %s: %s", url, e)
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

        items.append(
            {
                "guid": guid,
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "description": description,
            }
        )

    filtered = [item for item in items if is_relevant(item["title"], item.get("description", ""))]
    logger.info("Naver: %d items fetched from %s, %d passed relevance filter", len(items), url, len(filtered))
    return filtered


def _text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""
