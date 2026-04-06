import logging
import os
import sys
from pathlib import Path

from monitor import naver_playwright, nbm_website, youtube as yt_module, google_news as gn_module, notifier, state

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

    new_items: dict[str, list] = {"naver": [], "youtube": [], "nbm": [], "nbm_pages": [], "google_news": []}

    # --- Naver News (Playwright) ---
    try:
        naver_items = naver_playwright.fetch_news()
        new_items["naver"] = state.find_new_items(naver_items, seen["naver"], "guid")
        logger.info("Naver: %d new / %d total", len(new_items["naver"]), len(naver_items))
    except Exception as e:
        logger.warning("Naver fetch failed: %s", e)

    # --- NBM Website: News Releases + Media Coverage ---
    try:
        nbm_items = nbm_website.fetch_new_content()
        new_items["nbm"] = state.find_new_items(nbm_items, seen["nbm"], "guid")
        logger.info("NBM website: %d new / %d total", len(new_items["nbm"]), len(nbm_items))
    except Exception as e:
        logger.warning("NBM website fetch failed: %s", e)

    # --- NBM Website: Page Change Detection ---
    try:
        new_items["nbm_pages"] = nbm_website.check_page_changes(seen["nbm_pages"])
        logger.info("NBM pages: %d changed", len(new_items["nbm_pages"]))
    except Exception as e:
        logger.warning("NBM page check failed: %s", e)

    # --- Google News ---
    try:
        gn_items = gn_module.fetch_news()
        new_items["google_news"] = state.find_new_items(gn_items, seen["google_news"], "guid")
        logger.info("Google News: %d new / %d total", len(new_items["google_news"]), len(gn_items))
    except Exception as e:
        logger.warning("Google News fetch failed: %s", e)

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

    # Always update seen items and save state (preserves page hash baselines)
    state.update_seen(seen["naver"], new_items["naver"], "guid")
    state.update_seen(seen["nbm"], new_items["nbm"], "guid")
    state.update_seen(seen["google_news"], new_items["google_news"], "guid")
    state.update_seen(seen["youtube"], new_items["youtube"], "video_id")
    # nbm_pages state is mutated in-place by check_page_changes()
    state.save_state(seen, str(STATE_PATH))

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
