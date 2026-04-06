import logging
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

QUERIES = [
    "네오배터리",
    "네오배터리머티리얼즈",
    "neo battery materials",
]


def search_videos(api_key: str, max_results: int = 10) -> list[dict]:
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=7)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    seen_video_ids: set[str] = set()
    all_items: list[dict] = []

    for query in QUERIES:
        items = _search_query(api_key, query, published_after, max_results)
        for item in items:
            vid = item["video_id"]
            if vid not in seen_video_ids:
                seen_video_ids.add(vid)
                all_items.append(item)

    logger.info("YouTube: found %d unique videos across %d queries", len(all_items), len(QUERIES))
    return all_items


def _search_query(
    api_key: str, query: str, published_after: str, max_results: int
) -> list[dict]:
    params = {
        "part": "snippet",
        "type": "video",
        "order": "date",
        "q": query,
        "publishedAfter": published_after,
        "maxResults": max_results,
        "key": api_key,
    }

    try:
        resp = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        logger.warning("Network error querying YouTube for '%s': %s", query, e)
        return []

    if resp.status_code == 403:
        data = resp.json()
        errors = data.get("error", {}).get("errors", [])
        if any(e.get("reason") == "quotaExceeded" for e in errors):
            logger.warning("YouTube API quota exceeded — skipping remaining queries")
            return []
        logger.warning("YouTube API returned 403 for query '%s': %s", query, resp.text[:200])
        return []

    if not resp.ok:
        logger.warning("YouTube API error %d for query '%s'", resp.status_code, query)
        return []

    data = resp.json()
    items = []
    for raw in data.get("items", []):
        video_id = raw.get("id", {}).get("videoId")
        if not video_id:
            continue
        snippet = raw.get("snippet", {})
        items.append(
            {
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "description": snippet.get("description", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "query": query,
            }
        )

    logger.info("YouTube query '%s': %d results", query, len(items))
    return items
