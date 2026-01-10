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
    print(f"[DEBUG] posted_messages loaded: {len(posted_messages)}")

    result_output = []

    channels_data = fetch_channels_from_google_sheet(sheet_id, google_sheet_api_key)
    print(f"[DEBUG] channels loaded from sheet: {len(channels_data)}")

    for entry in channels_data:
        channel_link = entry["channel_link"]                 # twitter username/url now
        channel_type = entry.get("channel_type")             # e.g. "Market Events"
        twitter_username = extract_channel_username(channel_link)

        print(f"\n🐦 Processing Twitter: @{twitter_username} (Type: {channel_type})")
        print(f"[DEBUG] twitter_fetch_limit: {twitter_fetch_limit}")
        print(f"[DEBUG] channel_link raw: {channel_link}")

        # Fetch latest tweets
        try:
            messages = fetch_latest_messages(channel_link, limit=twitter_fetch_limit)

            # ✅ KEY DEBUG: check if twitter reader returns 0
            print(f"[DEBUG] fetched {len(messages)} tweets from @{twitter_username}")

            if not messages:
                print("[DEBUG] ❌ Twitter reader returned 0 tweets (likely parsing mismatch or API returned empty)")
                continue
            else:
                first = messages[0]
                print(f"[DEBUG] first tweet id: {first.get('id')}")
                print(f"[DEBUG] first tweet has_photo: {first.get('has_photo')}")
                print(f"[DEBUG] first tweet photos count: {len(first.get('photos', []))}")
                print(f"[DEBUG] first tweet text preview: {first.get('text', '')[:120]}")

        except Exception as e:
            print(f"[Error] Failed to fetch tweets for @{twitter_username}: {e}")
            continue

        for msg in messages:
            original_text = msg.get("text", "").strip()

            # Extra debug
            print(f"\n[DEBUG] processing tweet id={msg.get('id')} text_len={len(original_text)} has_photo={msg.get('has_photo')}")

            # Skip duplicates
            if original_text and original_text in posted_messages:
                print(f"⚠️ Skipping duplicate tweet ID {msg.get('id')} from @{twitter_username}")
                continue

            # Translate
            translated = translate_text_gemini(original_text)
            print(f"[DEBUG] translated length: {len(translated) if translated else 0}")

            # If translation fails, skip (keeps your results clean)
            if not translated or not translated.strip():
                print(f"[Warning] Empty translation. Skipping tweet ID {msg.get('id')} from @{twitter_username}")
                continue

            # Post to Telegram
            if msg.get("has_photo") and msg.get("photos"):
                photo_url = msg["photos"][0]  # take first photo for now
                print(f"[DEBUG] attempting photo download: {photo_url}")

                with tempfile.TemporaryDirectory() as tmpdir:
                    image_path = os.path.join(tmpdir, f"photo_{msg.get('id')}.jpg")

                    if download_image(photo_url, image_path):
                        print("[DEBUG] photo download OK, sending to Telegram...")
                        send_photo_to_telegram_channel(
                            image_path=image_path,
                            translated_caption=translated,
                            post_type=channel_type
                        )
                    else:
                        print("[DEBUG] photo download FAILED, fallback to text-only Telegram message...")
                        send_telegram_message_html(
                            translated_text=translated,
                            post_type=channel_type
                        )
            else:
                print("[DEBUG] text-only tweet, sending Telegram message...")
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

    print(f"\n[DEBUG] total new posts prepared: {len(result_output)}")

    if result_output:
        save_results(result_output)
        print("[DEBUG] results.json updated via save_results()")
    else:
        print("[DEBUG] No new posts. results.json not updated.")


if __name__ == "__main__":
    asyncio.run(main())
