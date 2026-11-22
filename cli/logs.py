import json
from datetime import datetime, timezone

from cli.constants import LOG_FILE, INTERNAL_NETWORK
from cli.discord_webhooks import DiscordWebhook


class LogService:
    """Collect normal CLI logs locally and forward them to Discord."""

    _DISCORD_COLORS = {
        "WARNING": 0xF0A202,
        "ERROR": 0xD64550,
        "STATUS": 0x2A9D8F,
        "INFO": 0x3A86FF,
    }

    def __init__(self, callback=None, log_path=LOG_FILE, webhook_url=None):
        self.callback = callback
        self.log_path = log_path
        self.webhook = DiscordWebhook(webhook_url) if webhook_url else DiscordWebhook.from_env("LOG_DISCORD_WEBHOOK")

    def _send_to_discord(self, event):
        if self.webhook:
            self.webhook.send({"embeds": [self._discord_embed(event)]})

    @classmethod
    def _discord_embed(cls, event):
        level = str(event.get("level", "info")).upper()
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
            "title": f"{level.title()} logged",
            "description": str(event.get("message", ""))[:4096],
            "color": cls._DISCORD_COLORS.get(level, cls._DISCORD_COLORS["INFO"]),
            "fields": fields[:25],
            "timestamp": event.get("timestamp"),
            "footer": {"text": f"lab-cli - {source}"},
        }

    def _write(self, event):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as log_file:
            log_file.write(json.dumps(event, sort_keys=True) + "\n")

    def log(self, level, message, **details):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
        }
        if details:
            event["details"] = details
        self._write(event)
        self._send_to_discord(event)
        if self.callback is not None:
            self.callback(event)

    def log_status(self, status_text):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "status",
            "message": "lab status report",
            "details": {"report": status_text},
        }
        self._write(event)
        if self.webhook:
            self.webhook.send_status(format_status_for_discord(status_text))
        if self.callback is not None:
            self.callback(event)


log_service = LogService()


def format_status_for_discord(report):
    """Format the structured status report using Discord Markdown."""
    host = report.get("host", {})
    memory = host.get("memory", {})
    disk = host.get("disk", {})
    cpu = host.get("cpu", {})
    cloudflare = host.get("cloudflare", {})
    lines = [
        "**Lab Status**",
        f"**Overall:** `{report.get('status', 'unknown')}`",
        "",
        "**Host**",
        f"- OS: `{host.get('os_version', 'unavailable')}`",
        f"- Uptime: `{host.get('uptime', 'unavailable')}`",
        f"- CPU: `{cpu.get('usage_percent', 'unavailable')}%`",
        f"- Memory: `{memory.get('used_human', 'unavailable')} / {memory.get('total_human', 'unavailable')}` ({memory.get('percent', 'unavailable')}%)",
        f"- Disk: `{disk.get('used_human', 'unavailable')} / {disk.get('total_human', 'unavailable')}` ({disk.get('percent', 'unavailable')}%)",
        f"- Temperature: `{host.get('temperature_celsius', 'unavailable')} C`",
        "",
        "**Network**",
        f"- Cloudflare tunnel: `{cloudflare.get('state', 'unavailable')}`",
        f"- Domains: {', '.join(f'`{domain}`' for domain in cloudflare.get('domains', [])) or '`none`'}",
        f"- Docker network: `{INTERNAL_NETWORK}`",
        "",
        "**Beakers**",
    ]
    for beaker in report.get("beakers", []):
        lines.append(f"**{beaker.get('name', 'unknown')}**")
        for container in beaker.get("containers", []):
            lines.append(
                f"- `{container.get('name', 'unknown')}`: "
                f"**{container.get('status', 'unknown')}** / {container.get('health', 'unknown')} "
                f"- uptime `{container.get('uptime', 'unavailable')}`, "
                f"restarts `{container.get('restart_count', 'unavailable')}`"
            )
    return "\n".join(lines)


def log(level, message, **details):
    log_service.log(level, message, **details)


def log_status(status_text):
    log_service.log_status(status_text)


def recent_logs(limit=50):
    if limit == 0 or not LOG_FILE.exists():
        return []
    events = []
    lines = LOG_FILE.read_text().splitlines()
    for line in lines if limit is None else lines[-limit:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def format_log(event):
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


def print_recent_logs(limit=50):
    events = recent_logs(limit)
    if not events:
        print("no logs")
        return
    for event in events:
        print(format_log(event))
