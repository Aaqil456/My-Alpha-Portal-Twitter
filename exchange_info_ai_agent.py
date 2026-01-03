import sys
import os
import asyncio
import tempfile
import requests

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.google_sheet_reader import fetch_channels_from_google_sheet
from utils.twitter_reader import extract_channel_username, fetch_latest_messages
from utils.ai_translator import translate_text_gemini
from utils.telegram_sender import send_telegram_message_html, send_photo_to_telegram_channel
from utils.json_writer import save_results, load_posted_messages


def download_image(url: str, out_path: str, timeout: int = 30) -> bool:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(r.content)
        return True
    except Exception as e:
        print(f"[Error] Failed to download image: {url} | {e}")
        return False


async def main():
    # Required secrets
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    google_sheet_api_key = os.environ["GOOGLE_SHEET_API_KEY"]

    # Optional: set default fetch size per account via env, fallback 1
    twitter_fetch_limit = int(os.getenv("TWITTER_FETCH_LIMIT", "1"))

    # Already-posted texts (to avoid duplicates)
    posted_messages = load_posted_messages()
    result_output = []

    channels_data = fetch_channels_from_google_sheet(sheet_id, google_sheet_api_key)

    for entry in channels_data:
        channel_link = entry["channel_link"]                 # twitter username/url now
        channel_type = entry.get("channel_type")             # e.g. "Market Events"
        twitter_username = extract_channel_username(channel_link)

        print(f"\n🐦 Processing Twitter: @{twitter_username} (Type: {channel_type})")

        # Fetch latest tweets
        try:
            messages = fetch_latest_messages(channel_link, limit=twitter_fetch_limit)
        except Exception as e:
            print(f"[Error] Failed to fetch tweets for @{twitter_username}: {e}")
            continue

        for msg in messages:
            original_text = msg.get("text", "").strip()

            # Skip duplicates
            if original_text and original_text in posted_messages:
                print(f"⚠️ Skipping duplicate tweet ID {msg.get('id')} from @{twitter_username}")
                continue

            # Translate
            translated = translate_text_gemini(original_text)

            # If translation fails, skip (keeps your results clean)
            if not translated or not translated.strip():
                print(f"[Warning] Empty translation. Skipping tweet ID {msg.get('id')} from @{twitter_username}")
                continue

            # Post to Telegram
            if msg.get("has_photo") and msg.get("photos"):
                photo_url = msg["photos"][0]  # take first photo for now

                with tempfile.TemporaryDirectory() as tmpdir:
                    image_path = os.path.join(tmpdir, f"photo_{msg.get('id')}.jpg")

                    if download_image(photo_url, image_path):
                        send_photo_to_telegram_channel(
                            image_path=image_path,
                            translated_caption=translated,
                            post_type=channel_type
                        )
                    else:
                        # fallback to text-only if image download fails
                        send_telegram_message_html(
                            translated_text=translated,
                            post_type=channel_type
                        )
            else:
                send_telegram_message_html(
                    translated_text=translated,
                    post_type=channel_type
                )

            # Log what we posted
            result_output.append({
                "source": "twitter",
                "channel_link": channel_link,
                "channel_type": channel_type,
                "twitter_username": twitter_username,
                "original_text": original_text,
                "translated_text": translated,
                "date": msg.get("date"),
                "message_id": msg.get("id"),
                "photos": msg.get("photos", []),
            })

    if result_output:
        save_results(result_output)


if __name__ == "__main__":
    asyncio.run(main())
