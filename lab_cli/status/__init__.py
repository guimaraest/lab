import json

from lab_cli.constants import *
from lab_cli.discord_webhooks import DiscordWebhook
from lab_cli.notifications import notify, notify_once, recent_notifications
from lab_cli.status.collect import beaker_status, build_report, docker_stats
from lab_cli.status.render import print_beaker_status, print_status, render_status


def cmd_status(args):
    report = build_report()
    host = report["host"]
    if host.get("boot_time"):
        notify_once(
            f"host-restart:{host['boot_time']}",
            "warning",
            "home server restarted",
            source="host",
            boot_time=host["last_restart"],
        )
    memory_percent = host["memory"].get("percent")
    if memory_percent is not None and memory_percent >= WARNING_MEMORY_PERCENT:
        notify_once("host-memory-pressure", "warning", "host memory usage is high", source="host", percent=memory_percent)
    disk_percent = host["disk"].get("percent")
    if disk_percent is not None and disk_percent >= WARNING_DISK_PERCENT:
        notify_once("host-disk-pressure", "warning", "host disk usage is high", source="host", percent=disk_percent)
    temperature = host.get("temperature_celsius")
    if temperature is not None and temperature >= WARNING_TEMPERATURE_CELSIUS:
        notify_once("host-temperature", "warning", "host temperature is high", source="host", celsius=temperature)
    for jail in host.get("fail2ban", {}).get("jails", []):
        banned = jail.get("currently_banned", 0)
        if banned:
            notify_once(
                f"fail2ban:{jail['name']}:{banned}",
                "warning",
                f"fail2ban has active bans in {jail['name']}",
                source="security",
                jail=jail["name"],
                banned=banned,
            )
    containers = [container for beaker in report["beakers"] for container in beaker["containers"]]
    all_containers_running = bool(containers) and all(container["status"] == "running" for container in containers)
    if report.get("status") == "degraded" and all_containers_running:
        unhealthy = ",".join(
            f"{container['name']}={container['health']}"
            for container in containers
            if container["health"] not in ("healthy", "none")
        )
        notify_once(f"overall-degraded:{unhealthy}", "warning", "overall beaker status is degraded", source="status")
    report["notifications"] = recent_notifications(5)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_status(report)
    if getattr(args, "discord", False):
        webhook = DiscordWebhook.from_env("LOG_DISCORD_WEBHOOK")
        if webhook:
            webhook.send_status(render_status(report))


def get_beaker_status(name):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    return beaker_status(name, path, docker_stats())
