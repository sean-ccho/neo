import re
from datetime import datetime, timedelta, timezone

REQUIRED_KEYWORDS = [
    "네오배터리머티리얼즈",
    "neo battery materials",
]

BLOCKLIST = [
    "맥북", "macbook", "mac book", "자전거", "소셜라이딩",
    "치과", "dental", "doctus", "덴티미", "보조배터리",
]


def is_relevant(title: str, description: str = "") -> bool:
    combined = (title + " " + description).lower()
    if any(kw.lower() in combined for kw in REQUIRED_KEYWORDS):
        return True
    if "네오배터리" in combined:
        return not any(bl.lower() in combined for bl in BLOCKLIST)
    return False


def parse_pub_date(date_str: str) -> datetime | None:
    """Parse various date string formats into a UTC-aware datetime."""
    if not date_str:
        return None
    s = date_str.strip()

    # Naver relative: "5일 전", "1주 전", "3개월 전", "2시간 전"
    m = re.match(r"^(\d+)(시간|분|초)\s*전$", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = timedelta(hours=n) if unit == "시간" else timedelta(minutes=n) if unit == "분" else timedelta(seconds=n)
        return datetime.now(timezone.utc) - delta

    m = re.match(r"^(\d+)일\s*전$", s)
    if m:
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))

    m = re.match(r"^(\d+)주\s*전$", s)
    if m:
        return datetime.now(timezone.utc) - timedelta(weeks=int(m.group(1)))

    m = re.match(r"^(\d+)개월\s*전$", s)
    if m:
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)) * 30)

    # Naver absolute: "2026.03.08." or "2026.03.08"
    m = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return None

    # ISO: "2026-04-01" or "2026-04-01T00:00:00" or with timezone
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return None

    # English long form: "April 1, 2026" / "March 19, 2026"
    try:
        dt = datetime.strptime(s, "%B %d, %Y")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    return None


def is_within_days(date_str: str, days: int = 7) -> bool:
    """Return True if the date is within the last `days` days. Returns True on parse failure (safe include)."""
    dt = parse_pub_date(date_str)
    if dt is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return dt >= cutoff
