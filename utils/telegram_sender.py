import os
import re
import html
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API_BASE = "https://api.telegram.org"
MESSAGE_LIMIT = 4096
CAPTION_LIMIT = 1024  # safe caption limit for captions' VISIBLE text

# -------------------- Markdown → HTML (safe subset) --------------------

# [label](https://url)
MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^)\s]+)\)')
# **bold** or __bold__
MD_BOLD_RE = re.compile(r'(\*\*|__)(.+?)\1', re.DOTALL)
# *italic* or _italic_ (but not **bold**)
MD_ITALIC_RE = re.compile(
    r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)',
    re.DOTALL
)


def render_html_with_basic_md(text: str) -> str:
    """
    Convert a minimal Markdown subset to Telegram-safe HTML:
      - [label](url)  -> <a href="url">label</a>
      - **bold**/__bold__ -> <b>bold</b>
      - *italic*/_italic_  -> <i>italic</i>
    Everything else is HTML-escaped. Labels/hrefs are escaped too.
    """
    if not text:
        return ""

    # We do one pass with a combined regex so we can escape 'between' parts safely
    token_re = re.compile(
        r'(\[([^\]]+)\]\((https?://[^)\s]+)\)|'          # [label](url)
        r'(\*\*|__)(.+?)\4|'                             # **bold** or __bold__
        r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|'          # *italic*
        r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_))',               # _italic_
        re.DOTALL
    )

    out = []
    i = 0
    for m in token_re.finditer(text):
        # Escape the literal segment before the token
        out.append(html.escape(text[i:m.start()]))

        full = m.group(1)
        # link pieces
        link_label = m.group(2)
        link_href = m.group(3)
        # bold pieces
        bold_delim = m.group(4)
        bold_inner = m.group(5)
        # italic pieces (two alternatives)
        italic_star_inner = m.group(6)
        italic_underscore_inner = m.group(7)

        if link_label and link_href:
            out.append(
                f'<a href="{html.escape(link_href, quote=True)}">'
                f'{html.escape(link_label)}</a>'
            )
        elif bold_delim and bold_inner is not None:
            out.append(f'<b>{html.escape(bold_inner)}</b>')
        elif italic_star_inner is not None:
            out.append(f'<i>{html.escape(italic_star_inner)}</i>')
        elif italic_underscore_inner is not None:
            out.append(f'<i>{html.escape(italic_underscore_inner)}</i>')
        else:
            # Fallback (shouldn't happen): escape token
            out.append(html.escape(full))

        i = m.end()

    # Tail after the last token
    out.append(html.escape(text[i:]))
    return "".join(out)


# -------------------- Smarter splitter (try not to cut sentences) --------------------

def _split_for_telegram_raw(text: str, limit: int) -> list[str]:
    """
    Split RAW TEXT (not HTML) into <=limit chunks.
    Preference order:
      1. Double newline (\n\n)
      2. Single newline (\n)
      3. Sentence end (. / ! / ? + space)
      4. Space
      5. Hard cut at 'limit' if needed (e.g., very long URL)
    """
    if text is None:
        return [""]
    text = text or ""
    if len(text) <= limit:
        return [text]

    parts = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break

        # Look at the next 'limit' chars window
        chunk = remaining[:limit]

        split_idx = -1

        # 1. Try double newline
        idx = chunk.rfind("\n\n")
        if idx != -1 and idx > limit * 0.4:
            split_idx = idx + 2  # include the "\n\n"

        # 2. Try single newline
        if split_idx == -1:
            idx = chunk.rfind("\n")
            if idx != -1 and idx > limit * 0.4:
                split_idx = idx + 1

        # 3. Try sentence end (. ! ? + space)
        if split_idx == -1:
            for ender in [". ", "! ", "? "]:
                idx = chunk.rfind(ender)
                if idx != -1 and idx > limit * 0.4:
                    split_idx = idx + len(ender)
                    break

        # 4. Try last space
        if split_idx == -1:
            idx = chunk.rfind(" ")
            if idx != -1 and idx > limit * 0.4:
                split_idx = idx + 1

        # 5. Fallback: hard cut
        if split_idx == -1:
            split_idx = limit

        part = remaining[:split_idx].rstrip()
        parts.append(part)

        remaining = remaining[split_idx:].lstrip()

    # Hard cap just in case
    return [p[:limit] for p in parts]


# -------------------- Public send functions --------------------

def send_telegram_message_html(
    translated_text: str,
    exchange_name: str | None = None,
    referral_link: str | None = None,
    post_type: str | None = None,
):
    """
    Sends a (possibly long) message with Telegram HTML parse_mode.
      - Converts **bold**, *italic*, [label](url) to <b>, <i>, <a>
      - Escapes everything else
      - Splits RAW text into 4096-safe chunks, then converts each chunk
      - Adds a bold [Type] label on its own line at the top if post_type is provided.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment.")
        return []

    raw_chunks = _split_for_telegram_raw(translated_text or "", MESSAGE_LIMIT)
    url = f"{API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    results = []

    for i, raw_chunk in enumerate(raw_chunks, 1):
        # Convert message body first (safe, escaped)
        safe_html = render_html_with_basic_md(raw_chunk)

        # Inject TYPE TAG AFTER conversion so <b> isn't escaped
        if post_type and i == 1:
            type_tag = f"[<b>{html.escape(post_type)}</b>]\n\n"
            safe_html = type_tag + safe_html

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": safe_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            r = requests.post(url, json=payload, timeout=20)
            results.append(r.json())
            if r.ok and r.json().get("ok"):
                print(
                    f"✅ Telegram message part {i}/{len(raw_chunks)} sent "
                    f"(raw-len={len(raw_chunk)})."
                )
            else:
                print(
                    f"❌ Telegram send error part {i}/{len(raw_chunks)}: {r.text}"
                )
        except Exception as e:
            print(f"❌ Telegram send exception part {i}/{len(raw_chunks)}: {e}")

    return results


def send_photo_to_telegram_channel(
    image_path: str,
    translated_caption: str,
    exchange_name: str | None = None,
    referral_link: str | None = None,
    post_type: str | None = None,
):
    """
    Sends a photo with caption (<=1024 VISIBLE chars). If caption is longer,
    sends the remainder as follow-up 4096-safe text messages.
      - Uses the same Markdown→HTML conversion
      - Splits RAW caption first, then converts each part
      - Adds a bold [Type] label on its own line at the top of the caption if provided.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment.")
        return None

    raw_caption = translated_caption or ""

    # Split RAW caption by CAPTION_LIMIT (visible text)
    if len(raw_caption) <= CAPTION_LIMIT:
        head_raw = raw_caption
        tail_raw = ""
    else:
        head_raw = raw_caption[:CAPTION_LIMIT]
        tail_raw = raw_caption[CAPTION_LIMIT:]

    # Convert the head to HTML for caption
    caption_head_html = render_html_with_basic_md(head_raw)

    # Insert type tag after conversion, only for the first (caption) part
    if post_type:
        type_tag = f"[<b>{html.escape(post_type)}</b>]\n\n"
        caption_head_html = type_tag + caption_head_html

    url = f"{API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    try:
        with open(image_path, "rb") as photo_file:
            files = {"photo": photo_file}
            data = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption_head_html,
                "parse_mode": "HTML",
            }
            r = requests.post(url, data=data, files=files, timeout=30)

        if r.ok and r.json().get("ok"):
            print(f"✅ Photo sent. Caption raw-len={len(head_raw)}.")
        else:
            print(f"❌ Failed to send photo: {r.text}")

        # Remainder of caption as regular messages (split raw -> then convert)
        if tail_raw:
            print(
                f"[INFO] Sending caption remainder as text "
                f"(raw-len={len(tail_raw)})."
            )
            # Here we DON'T repeat post_type so tag only appears once.
            send_telegram_message_html(
                translated_text=tail_raw,
                exchange_name=exchange_name,
                referral_link=referral_link,
                post_type=None,
            )

        return r.json()
    except FileNotFoundError:
        print(f"❌ Image not found: {image_path}")
    except Exception as e:
        print(f"❌ Telegram photo send exception: {e}")

    return None
