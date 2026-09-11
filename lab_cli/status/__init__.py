import json

from lab_cli.constants import *
from lab_cli.status.collect import beaker_status, build_report, docker_stats
from lab_cli.status.render import print_beaker_status, print_status


def cmd_status(args):
    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_status(report)


def get_beaker_status(name):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    return beaker_status(name, path, docker_stats())
