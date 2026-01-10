import requests
from urllib.parse import quote

def fetch_channels_from_google_sheet(sheet_id, api_key):
    sheet_range = quote("api call!A1:Z1000", safe="!:")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{sheet_range}?key={api_key}"
    response = requests.get(url, timeout=30)
    data = response.json()

    if "error" in data:
        print("[ERROR] Google Sheets API:", data["error"])
        return []

    rows = data.get("values", [])
    if not rows:
        print("[DEBUG] Sheet returned 0 rows (values empty).")
        return []

    header = rows[0]
    name_idx = header.index("Name")
    link_idx = header.index("Link")
    type_idx = header.index("Type")

    channel_data = []
    for row in rows[1:]:
        if len(row) > max(name_idx, link_idx, type_idx):
            channel_data.append({
                "channel_name": row[name_idx],
                "channel_link": row[link_idx],
                "channel_type": row[type_idx],
            })

    print(f"[DEBUG] Parsed channels: {len(channel_data)}")
    return channel_data
