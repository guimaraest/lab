import json
from datetime import datetime, timezone

from lab_cli.constants import NOTIFICATION_LOG


class NotificationService:
    """Collect important events in one place for a future phone notifier."""

    def __init__(self, callback=None, log_path=NOTIFICATION_LOG):
        self.callback = callback
        self.log_path = log_path

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

        if self.callback is not None:
            self.callback(event)


notification_service = NotificationService()


def notify(level, message, **details):
    notification_service.notify(level, message, **details)


def recent_notifications(limit=50):
    if limit <= 0 or not NOTIFICATION_LOG.exists():
        return []
    events = []
    for line in NOTIFICATION_LOG.read_text().splitlines()[-limit:]:
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
    suffix = " " + " ".join(f"{key}={value}" for key, value in sorted(details.items())) if details else ""
    return f"{timestamp} [{level:<7}] {message}{suffix}"


def print_recent_notifications(limit=50):
    events = recent_notifications(limit)
    if not events:
        print("no notifications")
        return
    for event in events:
        print(format_notification(event))