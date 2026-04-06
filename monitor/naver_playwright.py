import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from monitor.filter import is_relevant, is_within_days

logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    "네오배터리머티리얼즈",
    "네오배터리",
]

_JS_EXTRACT = """
() => {
    const container = document.querySelector('.fds-news-item-list-tab');
    if (!container) return [];

    const links = Array.from(container.querySelectorAll('a'));
    const seen = new Set();
    const results = [];

    // Date pattern: "5일 전", "1주 전", "3개월 전", "2026.03.08."
    const dateRe = /^\\d+[시분초]\\s*전$|^\\d+일\\s*전$|^\\d+주\\s*전$|^\\d+개월\\s*전$|^\\d{4}\\.\\d{2}\\.\\d{2}/;

    for (const a of links) {
        const href = a.getAttribute('href');
        const title = a.innerText.trim();

        if (!href || seen.has(href)) continue;
        if (!title || title.length < 10) continue;
        if (href === '#' || href.includes('naver.com') || href.includes('keep.')) continue;
        seen.add(href);

        // Walk up to find a container that has a date span
        let date = '';
        let parent = a.parentElement;
        for (let i = 0; i < 8; i++) {
            if (!parent) break;
            const spans = Array.from(parent.querySelectorAll("span[class*='sds-comps-text-type-body2']"));
            for (const sp of spans) {
                const txt = sp.innerText.trim();
                if (dateRe.test(txt)) { date = txt; break; }
            }
            if (date) break;
            parent = parent.parentElement;
        }

        results.push({ href, title, date });
    }
    return results;
}
"""


def fetch_news() -> list[dict]:
    seen_guids: set[str] = set()
    all_articles: list[dict] = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for query in SEARCH_QUERIES:
                url = f"https://search.naver.com/search.naver?where=news&query={query}&sort=1"
                page = browser.new_page()
                try:
                    page.goto(url, timeout=30000)
                    page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeoutError:
                    logger.warning("Naver playwright: page load timed out for '%s', proceeding with partial content", query)

                for art in page.evaluate(_JS_EXTRACT):
                    href = art.get("href", "")
                    if href and href not in seen_guids:
                        seen_guids.add(href)
                        all_articles.append(art)
                page.close()
            browser.close()
    except Exception as e:
        logger.warning("Naver playwright fetch failed: %s", e)
        return []

    items = []
    for art in all_articles:
        href = art.get("href", "")
        title = art.get("title", "")
        date = art.get("date", "")
        if not href or not title:
            continue
        items.append({
            "guid": href,
            "title": title,
            "link": href,
            "pub_date": date,
            "description": "",
        })

    filtered = [item for item in items if is_relevant(item["title"], item["description"])]
    filtered = [item for item in filtered if is_within_days(item["pub_date"], days=7)]
    logger.info("Naver playwright: %d articles fetched, %d passed relevance+date filter", len(items), len(filtered))
    return filtered
