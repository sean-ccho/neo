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
