import os
import requests
from typing import Any, Dict, List


def extract_channel_username(url_or_handle: str) -> str:
    """
    Accepts:
      - https://x.com/username
      - https://twitter.com/username/
      - @username
      - username
    Returns: username (no @)
    """
    if not url_or_handle:
        return ""

    v = url_or_handle.strip()

    if "twitter.com/" in v:
        v = v.split("twitter.com/")[-1]
    if "x.com/" in v:
        v = v.split("x.com/")[-1]

    v = v.strip().strip("/")
    if v.startswith("@"):
        v = v[1:]

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
    # Prefer Note Tweets (long-form)
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
    return str(legacy.get("id_str") or "")


def parse_tweets_from_timeline_json(data: Dict[str, Any], limit: int = 1) -> List[Dict[str, Any]]:
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

        if tweet.get("__typename") != "Tweet":
            continue

        text = _extract_text(tweet)
        photos = _extract_media_urls(tweet)

        if text or photos:
            results.append({
                "id": _extract_rest_id(tweet),
                "text": text or "",
                "has_photo": len(photos) > 0,
                "photos": photos,  # list[str]
                "raw": tweet,      # raw tweet object (smaller than full response)
                "date": _extract_created_at(tweet),
            })

    # De-dup by id, keep first occurrence
    seen = set()
    deduped = []
    for t in results:
        tid = t.get("id")
        if tid and tid not in seen:
            seen.add(tid)
            deduped.append(t)

    return deduped[: max(1, limit)]


def fetch_latest_messages(channel_username: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Twitter reader public API:
    - channel_username can be @handle, handle, or profile URL.
    - limit = number of tweets to fetch.
    """
    rapidapi_key = os.getenv("RAPIDAPI_KEY", "").strip()
    rapidapi_host = os.getenv("RAPIDAPI_HOST", "").strip()
    api_url = os.getenv("TWITTER_API_URL", "").strip()

    if not rapidapi_key or not rapidapi_host or not api_url:
        raise RuntimeError("Missing env vars: RAPIDAPI_KEY, RAPIDAPI_HOST, TWITTER_API_URL")

    username = extract_channel_username(channel_username)
    if not username:
        return []

    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": rapidapi_host,
    }

    # IMPORTANT: matches your RapidAPI spec
    params = {
        "username": username,
        "limit": limit,
    }

    resp = requests.get(api_url, headers=headers, params=params, timeout=3030)
    resp.raise_for_status()
    data = resp.json()

    return parse_tweets_from_timeline_json(data, limit=limit)
