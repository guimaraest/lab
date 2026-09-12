import json

from lab_cli.constants import *
from lab_cli.notifications import notify, recent_notifications
from lab_cli.status.collect import beaker_status, build_report, docker_stats
from lab_cli.status.render import print_beaker_status, print_status


def cmd_status(args):
    report = build_report()
    report["notifications"] = recent_notifications(5)
    containers = [container for beaker in report["beakers"] for container in beaker["containers"]]
    all_containers_running = bool(containers) and all(container["status"] == "running" for container in containers)
    if report.get("status") == "degraded" and all_containers_running:
        notify("warning", "overall beaker status is degraded", source="status")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_status(report)


def get_beaker_status(name):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    return beaker_status(name, path, docker_stats())
