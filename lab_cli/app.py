import argparse
import json
import subprocess
import time
from pathlib import Path

import yaml

LAB_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).with_name("cli_config.yaml")
NETWORK = "lab-net"
COMPOSE_ENV_FILE = LAB_ROOT / ".env"

HEALTH_TIMEOUT = 100  # seconds to wait for a beaker before giving up
HEALTH_POLL_INTERVAL = 2


def run(cmd, cwd=None, capture=False):
    return subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)


def compose_command(*args):
    return ["docker", "compose", "--env-file", str(COMPOSE_ENV_FILE), *args]


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)["beakers"]


def beaker_aliases(beakers):
    aliases = {}
    for name, config in beakers.items():
        aliases[name] = name
        for alias in config.get("aliases", []):
            if alias in aliases and aliases[alias] != name:
                raise ValueError(f"duplicate beaker alias: {alias}")
            aliases[alias] = name
    return aliases


def network_exists(name):
    return run(["docker", "network", "inspect", name], capture=True).returncode == 0


def topological_order(beakers, selected=None):
    """order beakers so dependencies start before dependents"""
    ordered = []
    visited = set()
    aliases = beaker_aliases(beakers)

    def visit(name):
        name = aliases.get(name, name)
        if name in visited:
            return
        visited.add(name)
        for dep in beakers[name].get("depends_on", []):
            visit(dep)
        ordered.append(name)

    for name in selected or beakers:
        visit(name)
    return ordered


def container_names(beaker_path):
    result = run(
        compose_command("config", "--format", "json"),
        cwd=beaker_path,
        capture=True,
    )
    if result.returncode != 0:
        return []
    config = json.loads(result.stdout)
    return [svc.get("container_name", name) for name, svc in config.get("services", {}).items()]


def wait_healthy(beaker_path, name):
    """poll until every container in the beaker is healthy, or just running
    if it has no healthcheck defined"""
    names = container_names(beaker_path)
    if not names:
        return True

    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        all_ready = True
        for cname in names:
            inspect = run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}|{{.State.Status}}", cname],
                capture=True,
            )
            if inspect.returncode != 0:
                all_ready = False
                break
            health, status = inspect.stdout.strip().split("|")
            ready = health == "healthy" if health != "<no value>" else status == "running"
            if not ready:
                all_ready = False
                break
        if all_ready:
            return True
        time.sleep(HEALTH_POLL_INTERVAL)

    print(f"warning: '{name}' did not report healthy within {HEALTH_TIMEOUT}s, continuing anyway")
    return False


def cmd_init(args):
    if network_exists(NETWORK):
        print(f"network '{NETWORK}' already exists")
    else:
        run(["docker", "network", "create", NETWORK])
        print(f"created network '{NETWORK}'")


def selected_beakers(beakers, requested):
    aliases = beaker_aliases(beakers)
    selected = []
    for name in requested:
        if name not in aliases:
            raise SystemExit(f"unknown beaker or alias: {name}")
        selected.append(aliases[name])
    return selected


def cmd_up(args):
    beakers = load_config()
    selected = selected_beakers(beakers, args.beakers)

    for name in topological_order(beakers, selected or None):
        cfg = beakers[name]
        if not selected and not cfg.get("autostart", True):
            print(f"skipping '{name}' (autostart disabled)")
            continue

        path = LAB_ROOT / name
        if not (path / "docker-compose.yml").exists():
            print(f"skipping '{name}' (no docker-compose.yml)")
            continue

        print(f"starting '{name}'...")
        up_command = compose_command("up", "-d")
        if args.build:
            up_command.append("--build")
        run(up_command, cwd=path)
        wait_healthy(path, name)
        if args.logs:
            run(compose_command("logs"), cwd=path)


def cmd_down(args):
    beakers = load_config()
    selected = selected_beakers(beakers, args.beakers)
    names = topological_order(beakers, selected or None)

    for name in reversed(names):
        path = LAB_ROOT / name
        if not (path / "docker-compose.yml").exists():
            print(f"skipping '{name}' (no docker-compose.yml)")
            continue

        print(f"stopping '{name}'...")
        run(compose_command("down"), cwd=path)


def cmd_status(args):
    result = run(["docker", "ps", "--format", "{{json .}}"], capture=True)
    containers = [json.loads(line) for line in result.stdout.splitlines() if line]

    if args.json:
        print(json.dumps(containers, indent=2))
        return

    for c in containers:
        print(f"{c['Names']:<20} {c['Status']:<25} {c['Image']}")


def main():
    parser = argparse.ArgumentParser(prog="lab", description="lab beaker orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the shared docker network")
    up_parser = sub.add_parser("up", help="start beakers in dependency order")
    up_parser.add_argument(
        "beakers",
        nargs="*",
        metavar="BEAKER_OR_ALIAS",
        help="beaker names or aliases (defaults to all autostart beakers)",
    )
    up_parser.add_argument("--build", action="store_true", help="build images before starting")
    up_parser.add_argument("--logs", action="store_true", help="show logs after starting")

    down_parser = sub.add_parser("down", help="stop beakers in reverse dependency order")
    down_parser.add_argument(
        "beakers",
        nargs="*",
        metavar="BEAKER_OR_ALIAS",
        help="beaker names or aliases (defaults to all beakers)",
    )

    status_parser = sub.add_parser("status", help="show running containers")
    status_parser.add_argument("--json", action="store_true", help="output as json")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "up":
        cmd_up(args)
    elif args.command == "down":
        cmd_down(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()