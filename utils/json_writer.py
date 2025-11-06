import json
import os
from datetime import datetime

def save_results(messages, file_path="results.json"):
    """
    Save new messages into results.json.
    Works whether the file already contains a dict with 'messages'
    or a top-level list of messages.
    """
    existing_messages = []

    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}

        # Handle both shapes: dict-with-'messages' and list
        if isinstance(data, dict):
            existing_messages = data.get("messages", [])
        elif isinstance(data, list):
            existing_messages = data

    # Combine existing and new messages
    combined_messages = existing_messages + messages

    # Save back in a consistent dict format
    data = {"timestamp": datetime.now().isoformat(), "messages": combined_messages}
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def load_posted_messages(file_path="results.json"):
    """
    Load all 'original_text' entries from results.json.
    Works safely whether results.json is a dict with 'messages'
    or a list of messages.
    """
    if not os.path.exists(file_path):
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return []

    # Handle both shapes: dict-with-'messages' and list
    if isinstance(data, dict):
        items = data.get("messages", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []

    posted_messages = []
    for msg in items:
        if isinstance(msg, dict) and "original_text" in msg:
            posted_messages.append(msg["original_text"])

    return posted_messages
