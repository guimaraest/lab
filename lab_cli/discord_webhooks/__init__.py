import json
import os
import sys
import urllib.error
import urllib.request

from lab_cli.constants import COMPOSE_ENV_FILE


class DiscordWebhook:
    """Send lab notifications and reports to Discord webhooks."""

    def __init__(self, url):
        self.url = url

    @classmethod
    def from_env(cls, variable):
        url = os.environ.get(variable)
        if url:
            return cls(url)
        if COMPOSE_ENV_FILE.exists():
            for line in COMPOSE_ENV_FILE.read_text().splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() == variable:
                    value = value.strip().strip('"').strip("'")
                    return cls(value) if value else None
        return None

    def send(self, payload):
        if not self or not self.url:
            return False
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "lab-cli/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5):
                pass
        except (OSError, urllib.error.URLError) as error:
            print(f"warning: could not send notification to Discord: {error}", file=sys.stderr)
            return False
        return True

    def send_status(self, status_text):
        chunks = _chunks(status_text, 3900)
        return all(self.send({"embeds": [{"title": "Lab status", "description": f"```\n{chunk}\n```"}]}) for chunk in chunks)


def _chunks(text, limit):
    lines = text.splitlines() or [""]
    chunks = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if current and len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks