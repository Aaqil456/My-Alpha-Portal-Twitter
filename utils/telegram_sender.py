import os
import re
import html
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API_BASE = "https://api.telegram.org"
MESSAGE_LIMIT = 4096
CAPTION_LIMIT = 1024  # safe caption limit

# --- Helpers ---------------------------------------------------------------

MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^)]+)\)')

def render_html_with_links(text: str) -> str:
    """
    Safely render text to Telegram-HTML:
    - Converts Markdown links [label](url) -> <a href="url">label</a>
    - Escapes all other characters.
    - Escapes label and href attributes too.
    """
    if not text:
        return ""

    out = []
    last = 0
    for m in MD_LINK_RE.finditer(text):
        # escape the plain part before the link
        out.append(html.escape(text[last:m.start()]))

        label = html.escape(m.group(1))
        href = html.escape(m.group(2), quote=True)  # escape quotes in href
        out.append(f'<a href="{href}">{label}</a>')
        last = m.end()

    # tail after the last match
    out.append(html.escape(text[last:]))
    return "".join(out)


def _split_for_telegram(text: str, limit: int) -> list[str]:
    """
    Split text into chunks <= limit, preferring paragraph/line boundaries,
    with word-split fallback.
    """
    if text is None:
        return [""]
    if len(text) <= limit:
        return [text]

    parts, current = [], []
    cur_len = 0

    for para in text.split("\n\n"):
        chunk = para + "\n\n"
        if cur_len + len(chunk) <= limit:
            current.append(chunk); cur_len += len(chunk)
        else:
            if current:
                parts.append("".join(current).rstrip())
                current, cur_len = [], 0
            if len(chunk) > limit:
                for line in chunk.split("\n"):
                    line_n = line + "\n"
                    if len(line_n) > limit:
                        words = line_n.split(" ")
                        buf, L = [], 0
                        for w in words:
                            w2 = w + " "
                            if L + len(w2) <= limit:
                                buf.append(w2); L += len(w2)
                            else:
                                parts.append("".join(buf).rstrip())
                                buf, L = [w2], len(w2)
                        if buf:
                            parts.append("".join(buf).rstrip())
                    else:
                        if cur_len + len(line_n) <= limit:
                            current.append(line_n); cur_len += len(line_n)
                        else:
                            parts.append("".join(current).rstrip())
                            current, cur_len = [line_n], len(line_n)
            else:
                current, cur_len = [chunk], len(chunk)

    if current:
        parts.append("".join(current).rstrip())

    return [p[:limit] for p in parts]


# --- Public send functions -------------------------------------------------

def send_telegram_message_html(translated_text: str,
                               exchange_name: str | None = None,
                               referral_link: str | None = None):
    """
    Sends a (possibly long) message with Telegram HTML parse_mode.
    - Converts [label](url) to <a href="url">label</a>
    - Escapes all other text
    - Splits into 4096-safe chunks
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment.")
        return []

    # Convert Markdown links to HTML anchors; escape everything else
    safe_html = render_html_with_links(translated_text or "")

    url = f"{API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = _split_for_telegram(safe_html, MESSAGE_LIMIT)

    results = []
    for i, chunk in enumerate(chunks, 1):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",               # we produced safe HTML
            "disable_web_page_preview": False,  # set True if you don't want previews
        }
        try:
            r = requests.post(url, json=payload, timeout=20)
            results.append(r.json())
            if r.ok and r.json().get("ok"):
                print(f"✅ Telegram message part {i}/{len(chunks)} sent (len={len(chunk)}).")
            else:
                print(f"❌ Telegram send error part {i}/{len(chunks)} (len={len(chunk)}): {r.text}")
        except Exception as e:
            print(f"❌ Telegram send exception part {i}/{len(chunks)}: {e}")

    return results


def send_photo_to_telegram_channel(image_path: str,
                                   translated_caption: str,
                                   exchange_name: str | None = None,
                                   referral_link: str | None = None):
    """
    Sends a photo with caption (<=1024 chars). If caption is longer,
    sends the remainder as follow-up 4096-safe text messages.
    - Caption supports [label](url) syntax as clickable links.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment.")
        return None

    # Safe HTML caption with anchor conversion
    safe_caption_html = render_html_with_links(translated_caption or "")
    caption_head = safe_caption_html[:CAPTION_LIMIT]
    caption_tail = safe_caption_html[CAPTION_LIMIT:]

    url = f"{API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    try:
        with open(image_path, "rb") as photo_file:
            files = {"photo": photo_file}
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption_head,
                "parse_mode": "HTML",
            }
            r = requests.post(url, data=data, files=files, timeout=30)

        if r.ok and r.json().get("ok"):
            print(f"✅ Photo sent. Caption len={len(caption_head)}.")
        else:
            print(f"❌ Failed to send photo: {r.text}")

        # Remainder of caption as regular messages
        if caption_tail:
            print(f"[INFO] Sending caption remainder as text (len={len(caption_tail)}).")
            send_telegram_message_html(caption_tail, exchange_name=exchange_name, referral_link=referral_link)

        return r.json()
    except FileNotFoundError:
        print(f"❌ Image not found: {image_path}")
    except Exception as e:
        print(f"❌ Telegram photo send exception: {e}")

    return None
