import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

EMPTY_STATE = {"naver": {}, "youtube": {}, "nbm": {}, "nbm_pages": {}}


def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Ensure all expected keys exist
        for key in EMPTY_STATE:
            data.setdefault(key, {})
        return data
    except FileNotFoundError:
        logger.info("State file not found, starting fresh: %s", path)
        return {k: {} for k in EMPTY_STATE}
    except json.JSONDecodeError as e:
        logger.warning("State file corrupted (%s), starting fresh", e)
        return {k: {} for k in EMPTY_STATE}


def save_state(state: dict, path: str) -> None:
    # Atomic write: write to temp file then rename
    dir_path = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_path, suffix=".tmp", delete=False, encoding="utf-8"
    ) as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        tmp_path = f.name
    os.replace(tmp_path, path)
    logger.info("State saved to %s", path)


def find_new_items(current: list[dict], seen: dict, key_field: str) -> list[dict]:
    return [item for item in current if item.get(key_field) not in seen]


def update_seen(seen: dict, new_items: list[dict], key_field: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for item in new_items:
        key = item.get(key_field)
        if key:
            seen[key] = {**item, "first_seen": now}
