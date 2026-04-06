import logging
import os
import sys
from pathlib import Path

from monitor import naver_rss, youtube as yt_module, notifier, state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

STATE_PATH = Path(__file__).parent.parent / "state" / "seen_items.json"


def main() -> int:
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "")
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    notify_email = os.environ.get("NOTIFY_EMAIL", "")

    if not all([gmail_user, gmail_password, notify_email]):
        logger.error("Missing required env vars: GMAIL_USER, GMAIL_APP_PASSWORD, NOTIFY_EMAIL")
        return 1

    # Load persisted state
    seen = state.load_state(str(STATE_PATH))

    new_items: dict[str, list] = {"naver_news": [], "naver_general": [], "youtube": []}

    # --- Naver News RSS ---
    try:
        naver_news_items = naver_rss.fetch_feed(naver_rss.NAVER_NEWS_RSS)
        new_items["naver_news"] = state.find_new_items(naver_news_items, seen["naver_news"], "guid")
        logger.info("Naver news: %d new / %d total", len(new_items["naver_news"]), len(naver_news_items))
    except Exception as e:
        logger.warning("Naver news fetch failed: %s", e)

    # --- Naver General RSS ---
    try:
        naver_gen_items = naver_rss.fetch_feed(naver_rss.NAVER_GENERAL_RSS)
        new_items["naver_general"] = state.find_new_items(naver_gen_items, seen["naver_general"], "guid")
        logger.info("Naver general: %d new / %d total", len(new_items["naver_general"]), len(naver_gen_items))
    except Exception as e:
        logger.warning("Naver general fetch failed: %s", e)

    # --- YouTube ---
    if youtube_api_key:
        try:
            yt_items = yt_module.search_videos(youtube_api_key)
            new_items["youtube"] = state.find_new_items(yt_items, seen["youtube"], "video_id")
            logger.info("YouTube: %d new / %d total", len(new_items["youtube"]), len(yt_items))
        except Exception as e:
            logger.warning("YouTube fetch failed: %s", e)
    else:
        logger.warning("YOUTUBE_API_KEY not set — skipping YouTube")

    total_new = sum(len(v) for v in new_items.values())

    if total_new == 0:
        logger.info("No new content found.")
        return 0

    logger.info("Found %d new items total — sending email", total_new)

    # Send email (fatal on failure)
    try:
        notifier.send_notification(new_items, notify_email, gmail_user, gmail_password)
    except Exception as e:
        logger.error("Failed to send notification email: %s", e)
        return 1

    # Update and save state
    state.update_seen(seen["naver_news"], new_items["naver_news"], "guid")
    state.update_seen(seen["naver_general"], new_items["naver_general"], "guid")
    state.update_seen(seen["youtube"], new_items["youtube"], "video_id")
    state.save_state(seen, str(STATE_PATH))

    return 0


if __name__ == "__main__":
    sys.exit(main())
