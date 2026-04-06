import logging
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Environment, BaseLoader

logger = logging.getLogger(__name__)

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 700px; margin: 0 auto; color: #333; }
  h1 { background: #1a73e8; color: white; padding: 16px 20px; margin: 0; font-size: 18px; }
  .timestamp { background: #f8f9fa; padding: 8px 20px; font-size: 13px; color: #666; border-bottom: 1px solid #e0e0e0; }
  .section { padding: 16px 20px; border-bottom: 1px solid #eee; }
  .section-title { font-size: 15px; font-weight: 600; margin: 0 0 12px; }
  .item { margin: 10px 0; padding: 10px 12px; background: #f8f9fa; border-left: 3px solid #1a73e8; border-radius: 2px; }
  .item a { color: #1a73e8; text-decoration: none; font-weight: 500; }
  .item a:hover { text-decoration: underline; }
  .item .meta { font-size: 12px; color: #888; margin-top: 4px; }
  .footer { padding: 12px 20px; font-size: 12px; color: #aaa; text-align: center; }
  .count { font-weight: bold; color: #1a73e8; }
</style>
</head>
<body>
<h1>네오배터리 모니터링 알림</h1>
<div class="timestamp">{{ timestamp }} EST &nbsp;|&nbsp; 총 <span class="count">{{ total }}건</span>의 새로운 콘텐츠</div>

{% if naver_news %}
<div class="section">
  <div class="section-title">📰 Naver 뉴스 ({{ naver_news|length }}건)</div>
  {% for item in naver_news %}
  <div class="item">
    <a href="{{ item.link }}" target="_blank">{{ item.title }}</a>
    <div class="meta">{{ item.pub_date }}</div>
  </div>
  {% endfor %}
</div>
{% endif %}

{% if naver_general %}
<div class="section">
  <div class="section-title">🔍 Naver 통합검색 ({{ naver_general|length }}건)</div>
  {% for item in naver_general %}
  <div class="item">
    <a href="{{ item.link }}" target="_blank">{{ item.title }}</a>
    <div class="meta">{{ item.pub_date }}</div>
  </div>
  {% endfor %}
</div>
{% endif %}

{% if youtube %}
<div class="section">
  <div class="section-title">🎬 YouTube ({{ youtube|length }}건)</div>
  {% for item in youtube %}
  <div class="item">
    <a href="{{ item.url }}" target="_blank">{{ item.title }}</a>
    <div class="meta">{{ item.channel_title }} &nbsp;·&nbsp; {{ item.published_at[:10] if item.published_at else '' }}</div>
  </div>
  {% endfor %}
</div>
{% endif %}

<div class="footer">이 이메일은 자동으로 발송되었습니다 · Neo Battery Monitor</div>
</body>
</html>
"""

PLAIN_TEMPLATE = """네오배터리 모니터링 알림
{{ timestamp }} EST | 총 {{ total }}건

{% if naver_news %}[Naver 뉴스 {{ naver_news|length }}건]
{% for item in naver_news %}- {{ item.title }}
  {{ item.link }}
  {{ item.pub_date }}
{% endfor %}{% endif %}
{% if naver_general %}[Naver 통합검색 {{ naver_general|length }}건]
{% for item in naver_general %}- {{ item.title }}
  {{ item.link }}
{% endfor %}{% endif %}
{% if youtube %}[YouTube {{ youtube|length }}건]
{% for item in youtube %}- {{ item.title }} ({{ item.channel_title }})
  {{ item.url }}
{% endfor %}{% endif %}"""


def send_notification(
    new_items: dict,
    recipient: str,
    gmail_user: str,
    gmail_password: str,
) -> None:
    naver_news = new_items.get("naver_news", [])
    naver_general = new_items.get("naver_general", [])
    youtube = new_items.get("youtube", [])
    total = len(naver_news) + len(naver_general) + len(youtube)

    from datetime import datetime, timezone, timedelta
    est = timezone(timedelta(hours=-5))  # EST (UTC-5)
    timestamp = datetime.now(est).strftime("%Y-%m-%d %I:%M %p")

    context = dict(
        timestamp=timestamp,
        total=total,
        naver_news=naver_news,
        naver_general=naver_general,
        youtube=youtube,
    )

    env = Environment(loader=BaseLoader())
    html_body = env.from_string(EMAIL_TEMPLATE).render(**context)
    plain_body = env.from_string(PLAIN_TEMPLATE).render(**context)

    subject = f"[네오배터리 알림] 새로운 콘텐츠 {total}건 — {timestamp} EST"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = recipient
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    _send_with_retry(msg, gmail_user, gmail_password, recipient)
    logger.info("Email sent to %s: %d new items", recipient, total)


def _send_with_retry(
    msg: MIMEMultipart,
    gmail_user: str,
    gmail_password: str,
    recipient: str,
    max_retries: int = 3,
) -> None:
    delay = 2
    for attempt in range(1, max_retries + 1):
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(gmail_user, gmail_password)
                server.sendmail(gmail_user, [recipient], msg.as_string())
            return
        except Exception as e:
            logger.warning("Email attempt %d/%d failed: %s", attempt, max_retries, e)
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(f"Failed to send email after {max_retries} attempts")
