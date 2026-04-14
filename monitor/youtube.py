import logging
from datetime import datetime, timedelta, timezone

import requests

from monitor.filter import is_relevant

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

QUERIES = [
    "네오배터리",
    "네오배터리머티리얼즈",
    "neo battery materials",
]


def search_videos(api_key: str, max_results: int = 10) -> list[dict]:
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=14)
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

    hydrated = _hydrate_videos(api_key, all_items)

    filtered = []
    for item in hydrated:
        haystack = " ".join([
            item.get("title", ""),
            item.get("channel_title", ""),
            item.get("description", ""),
            " ".join(item.get("tags", []) or []),
        ])
        if is_relevant(item["title"], haystack):
            filtered.append(item)

    logger.info(
        "YouTube: %d unique videos fetched, %d hydrated, %d passed relevance filter",
        len(all_items), len(hydrated), len(filtered),
    )
    return filtered


def _hydrate_videos(api_key: str, items: list[dict]) -> list[dict]:
    """Replace search-snippet description with full description + tags via videos.list."""
    if not items:
        return items

    by_id = {item["video_id"]: item for item in items}
    ids = list(by_id.keys())

    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        params = {
            "part": "snippet",
            "id": ",".join(batch),
            "key": api_key,
        }
        try:
            resp = requests.get(YOUTUBE_VIDEOS_URL, params=params, timeout=15)
        except requests.exceptions.RequestException as e:
            logger.warning("Network error hydrating YouTube videos: %s", e)
            continue

        if resp.status_code == 403:
            data = resp.json()
            errors = data.get("error", {}).get("errors", [])
            if any(e.get("reason") == "quotaExceeded" for e in errors):
                logger.warning("YouTube API quota exceeded during hydrate — leaving remaining items un-hydrated")
                break
            logger.warning("YouTube videos.list 403: %s", resp.text[:200])
            continue

        if not resp.ok:
            logger.warning("YouTube videos.list error %d", resp.status_code)
            continue

        data = resp.json()
        for raw in data.get("items", []):
            vid = raw.get("id")
            snippet = raw.get("snippet", {})
            if not vid or vid not in by_id:
                continue
            target = by_id[vid]
            target["description"] = snippet.get("description", target.get("description", ""))
            target["tags"] = snippet.get("tags", []) or []
            target["channel_title"] = snippet.get("channelTitle", target.get("channel_title", ""))

    return list(by_id.values())


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
