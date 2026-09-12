import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def webhook_url():
    if os.environ.get("WARNING_DISCORD_WEBHOOK"):
        return os.environ["WARNING_DISCORD_WEBHOOK"]
    env_file = Path("/lab/.env")
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "WARNING_DISCORD_WEBHOOK":
            return value.strip().strip('"').strip("'") or None
    return None


def notify_server_up():
    url = webhook_url()
    if not url:
        print("warning: WARNING_DISCORD_WEBHOOK is not configured", file=sys.stderr)
        return
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "WARNING",
        "message": "server is up",
        "details": {"source": "ofelia"},
    }
    payload = {
        "embeds": [{
            "title": "Warning detected",
            "description": event["message"],
            "color": 0xF0A202,
            "fields": [{"name": "Source", "value": "`ofelia`", "inline": True}],
            "timestamp": event["timestamp"],
            "footer": {"text": "lab-cli • ofelia"},
        }],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "lab-cli/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            pass
    except (OSError, urllib.error.URLError) as error:
        print(f"warning: could not send server-up notification to Discord: {error}", file=sys.stderr)


if __name__ == "__main__":
    notify_server_up()