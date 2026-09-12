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