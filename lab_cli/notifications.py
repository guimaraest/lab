import json
from datetime import datetime, timezone

from lab_cli.constants import NOTIFICATION_LOG
from lab_cli.discord_webhooks import DiscordWebhook


class NotificationService:
    """Collect notifications locally and forward warnings to Discord."""

    _DISCORD_COLORS = {
        "WARNING": 0xF0A202,
        "ERROR": 0xD64550,
        "STATUS": 0x2A9D8F,
        "INFO": 0x3A86FF,
    }

    def __init__(self, callback=None, log_path=NOTIFICATION_LOG, webhook_url=None):
        self.callback = callback
        self.log_path = log_path
        self.webhook = DiscordWebhook(webhook_url) if webhook_url else DiscordWebhook.from_env("WARNING_DISCORD_WEBHOOK")

    def _send_warning_to_discord(self, event):
        if not self.webhook:
            return
        self.webhook.send({"embeds": [self._discord_embed(event)]})

    @classmethod
    def _discord_embed(cls, event):
        level = str(event.get("level", "warning")).upper()
        details = {
            key: value
            for key, value in event.get("details", {}).items()
            if not key.startswith("_")
        }
        fields = [
            {
                "name": str(key).replace("_", " ").title(),
                "value": f"`{str(value)[:1020]}`",
                "inline": key in {"source", "beaker", "container"},
            }
            for key, value in sorted(details.items())
        ]
        source = details.get("source", "lab-cli")
        return {
            "title": f"{level.title()} detected",
            "description": str(event.get("message", ""))[:4096],
            "color": cls._DISCORD_COLORS.get(level, cls._DISCORD_COLORS["WARNING"]),
            "fields": fields[:25],
            "timestamp": event.get("timestamp"),
            "footer": {"text": f"lab-cli • {source}"},
        }

    def notify(self, level, message, **details):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
        }
        if details:
            event["details"] = details

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as log_file:
            log_file.write(json.dumps(event, sort_keys=True) + "\n")

        if level == "warning":
            self._send_warning_to_discord(event)

        if self.callback is not None:
            self.callback(event)


notification_service = NotificationService()


def notify(level, message, **details):
    notification_service.notify(level, message, **details)


def notify_server_up():
    notify("warning", "server is up", source="ofelia")


def notify_once(key, level, message, **details):
    for event in recent_notifications(None):
        if event.get("details", {}).get("_dedupe_key") == key:
            return False
    details["_dedupe_key"] = key
    notify(level, message, **details)
    return True


def recent_notifications(limit=50):
    if limit == 0 or not NOTIFICATION_LOG.exists():
        return []
    events = []
    lines = NOTIFICATION_LOG.read_text().splitlines()
    for line in lines if limit is None else lines[-limit:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def format_notification(event):
    timestamp = event.get("timestamp", "unknown time")
    try:
        timestamp = datetime.fromisoformat(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    level = str(event.get("level", "info")).upper()
    message = event.get("message", "")
    details = event.get("details", {})
    details = {key: value for key, value in details.items() if not key.startswith("_")}
    suffix = " " + " ".join(f"{key}={value}" for key, value in sorted(details.items())) if details else ""
    return f"{timestamp} [{level:<7}] {message}{suffix}"


def format_relative_notification(event):
    timestamp = event.get("timestamp")
    try:
        elapsed = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds()))
        if elapsed < 60:
            age = "just now" if elapsed < 5 else f"{elapsed}s ago"
        elif elapsed < 3600:
            age = f"{elapsed // 60}m ago"
        elif elapsed < 86400:
            age = f"{elapsed // 3600}h ago"
        else:
            age = f"{elapsed // 86400}d ago"
    except (TypeError, ValueError):
        age = "unknown time"
    level = str(event.get("level", "info")).upper()
    message = event.get("message", "")
    details = {key: value for key, value in event.get("details", {}).items() if not key.startswith("_")}
    suffix = " " + " ".join(f"{key}={value}" for key, value in sorted(details.items())) if details else ""
    return f"{age:<10} [{level:<7}] {message}{suffix}"


def print_recent_notifications(limit=50):
    events = recent_notifications(limit)
    if not events:
        print("no notifications")
        return
    for event in events:
        print(format_notification(event))