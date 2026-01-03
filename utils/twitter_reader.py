import os
import requests
from typing import Any, Dict, List


def extract_channel_username(url_or_handle: str) -> str:
    """
    Accepts:
      - "https://x.com/username"
      - "https://twitter.com/username/"
      - "@username"
      - "username"
    Returns: "username" (no @)
    """
    if not url_or_handle:
        return ""

    v = url_or_handle.strip()

    # URL forms
    if "twitter.com/" in v:
        v = v.split("twitter.com/")[-1]
    if "x.com/" in v:
        v = v.split("x.com/")[-1]

    v = v.strip().strip("/")

    # remove @
    if v.startswith("@"):
        v = v[1:]

    # remove querystring
    if "?" in v:
        v = v.split("?", 1)[0]

    return v


def _walk(obj: Any):
    """Recursively yields dict/list nodes for robust JSON parsing."""
    if isinstance(obj, dict):
        yield obj
        for _, v in obj.items():
            yield from _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def _extract_media_urls(tweet_result: Dict[str, Any]) -> List[str]:
    """
    Photos often appear in:
      legacy.entities.media[].media_url_https
    and sometimes:
      legacy.extended_entities.media[].media_url_https
    """
    urls: List[str] = []

    legacy = tweet_result.get("legacy") or {}
    entities = legacy.get("entities") or {}
    media = entities.get("media") or []

    for m in media:
        u = m.get("media_url_https")
        if u:
            urls.append(u)

    ext = legacy.get("extended_entities") or {}
    ext_media = ext.get("media") or []
    for m in ext_media:
        u = m.get("media_url_https")
        if u and u not in urls:
            urls.append(u)

    # de-dup preserve order
    seen = set()
    deduped = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    return deduped


def _extract_text(tweet_result: Dict[str, Any]) -> str:
    """
    Prefer Note Tweet text if exists, else legacy.full_text.
    """
    note = tweet_result.get("note_tweet_results") or {}
    note_res = note.get("result") or {}
    note_text = note_res.get("text")
    if note_text:
        return note_text.strip()

    legacy = tweet_result.get("legacy") or {}
    return (legacy.get("full_text") or "").strip()


def _extract_created_at(tweet_result: Dict[str, Any]) -> str:
    legacy = tweet_result.get("legacy") or {}
    return str(legacy.get("created_at") or "")


def _extract_rest_id(tweet_result: Dict[str, Any]) -> str:
    rid = tweet_result.get("rest_id")
    if rid:
        return str(rid)

    legacy = tweet_result.get("legacy") or {}
    id_str = legacy.get("id_str")
    return str(id_str or "")


def parse_tweets_from_timeline_json(data: Dict[str, Any], limit: int = 1) -> List[Dict[str, Any]]:
    """
    Returns list of messages shaped like your Telegram reader output, but for tweets:
      {
        "id": "...",
        "text": "...",
        "has_photo": bool,
        "photos": [url,...],
        "raw": {...},
        "date": "..."
      }
    """
    results: List[Dict[str, Any]] = []

    for node in _walk(data):
        if not isinstance(node, dict):
            continue

        tr = node.get("tweet_results")
        if not isinstance(tr, dict):
            continue

        tweet = tr.get("result")
        if not isinstance(tweet, dict):
            continue

        # skip non-tweet types (tombstone, unavailable, etc.)
        if tweet.get("__typename") != "Tweet":
            continue

        text = _extract_text(tweet)
        photos = _extract_media_urls(tweet)

        if text or photos:
            results.append({
                "id": _extract_rest_id(tweet),
                "text": text or "",
                "has_photo": len(photos) > 0,
                "photos": photos,   # list of photo URLs
                "raw": tweet,       # raw tweet object
                "date": _extract_created_at(tweet),
            })

    # De-dup by id
    seen = set()
    deduped = []
    for t in results:
        tid = t.get("id")
        if tid and tid not in seen:
            seen.add(tid)
            deduped.append(t)

    return deduped[: max(1, limit)]


def fetch_latest_tweets_from_api(username_or_url: str, limit: int = 1) -> List[Dict[str, Any]]:
    """
    Uses env vars:
      - RAPIDAPI_KEY
      - RAPIDAPI_HOST
      - TWITTER_API_URL
    """
    rapidapi_key = os.getenv("RAPIDAPI_KEY", "").strip()
    rapidapi_host = os.getenv("RAPIDAPI_HOST", "").strip()
    api_url = os.getenv("TWITTER_API_URL", "").strip()

    if not rapidapi_key or not rapidapi_host or not api_url:
        raise RuntimeError(
            "Missing required env vars. Please set RAPIDAPI_KEY, RAPIDAPI_HOST, and TWITTER_API_URL."
        )

    username = extract_channel_username(username_or_url)
    if not username:
        return []

    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": rapidapi_host,
    }

    # IMPORTANT: adjust these params if your endpoint uses different ones.
    # Common patterns: {"username": username, "count": limit} or {"screenname": username, "limit": limit}
    params = {
        "username": username,
        "count": limit,
    }

    resp = requests.get(api_url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    return parse_tweets_from_timeline_json(data, limit=limit)


# ✅ Compatibility-style function name (so your main pipeline can stay similar)
async def fetch_latest_messages(api_id, api_hash, channel_username, limit=1):
    """
    COMPAT MODE:
    - Your old Telegram reader signature was (api_id, api_hash, channel_username, limit)
    - For Twitter, api_id/api_hash are not used.
    - channel_username is your twitter handle/url from Google Sheet.
    """
    # This is sync requests, but kept async signature for compatibility with your existing async pipeline.
    # If your main code awaits this, it still works.
    return fetch_latest_tweets_from_api(channel_username, limit=limit)
