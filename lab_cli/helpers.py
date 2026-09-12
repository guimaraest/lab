import json
import subprocess
import sys

import yaml

from lab_cli.constants import *


def run(cmd, cwd=None, capture=False, timeout=None):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")


def command_result(cmd, cwd=None, timeout=5):
    return run(cmd, cwd=cwd, capture=True, timeout=timeout)


def command_text(cmd, cwd=None, timeout=5):
    result = command_result(cmd, cwd=cwd, timeout=timeout)
    return result.stdout.strip() if result.returncode == 0 else ""


def compose_command(*args):
    return ["docker", "compose", "--env-file", str(COMPOSE_ENV_FILE), *args]


def load_settings():
    with CONFIG_PATH.open() as config_file:
        settings = yaml.safe_load(config_file) or {}
    validate_config(settings)
    return settings


def load_config():
    return load_settings()["beakers"]


def validate_config(settings):
    beakers = settings.get("beakers")
    if not isinstance(beakers, dict):
        raise SystemExit("invalid config: 'beakers' must be a mapping")
    retries = settings.get("restart_max_retries")
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 1:
        raise SystemExit("invalid config: 'restart_max_retries' must be a positive integer")

    warned = set()
    def warn(message):
        if message not in warned:
            print(f"warning: {message}", file=sys.stderr)
            warned.add(message)

    for name, config in beakers.items():
        for dependency in config.get("depends_on", []):
            if dependency not in beakers:
                warn(f"beaker '{name}' depends on unknown beaker '{dependency}'")

    visiting = []
    visited = set()
    def visit(name):
        if name in visiting:
            cycle = visiting[visiting.index(name):] + [name]
            warn(f"circular dependency: {' -> '.join(cycle)}")
            return
        if name in visited or name not in beakers:
            return
        visiting.append(name)
        for dependency in beakers[name].get("depends_on", []):
            visit(dependency)
        visiting.pop()
        visited.add(name)

    for name in beakers:
        visit(name)

    for name, config in beakers.items():
        if not config.get("allow_restart", False):
            continue
        dependencies = set()
        stack = list(config.get("depends_on", []))
        while stack:
            dependency = stack.pop()
            if dependency in dependencies or dependency not in beakers:
                continue
            dependencies.add(dependency)
            stack.extend(beakers[dependency].get("depends_on", []))
        for dependency in dependencies:
            if dependency != "ofelia" and not beakers[dependency].get("allow_restart", False):
                warn(
                    f"beaker '{name}' cannot be safely restarted without its "
                    f"non-restartable dependency '{dependency}' also cycling"
                )

    return settings


def beaker_aliases(beakers):
    aliases = {}
    for name, config in beakers.items():
        aliases[name] = name
        for alias in config.get("aliases", []):
            if alias in aliases and aliases[alias] != name:
                raise ValueError(f"duplicate beaker alias: {alias}")
            aliases[alias] = name
    return aliases


def selected_beakers(beakers, requested):
    aliases = beaker_aliases(beakers)
    selected = []
    for name in requested:
        if name not in aliases:
            raise SystemExit(f"unknown beaker or alias: {name}")
        selected.append(aliases[name])
    return selected


def topological_order(beakers, selected=None):
    ordered = []
    visited = set()
    visiting = set()
    aliases = beaker_aliases(beakers)

    def visit(name):
        name = aliases.get(name, name)
        if name in visited:
            return
        if name in visiting or name not in beakers:
            return
        visiting.add(name)
        for dependency in beakers[name].get("depends_on", []):
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in selected or beakers:
        visit(name)
    return ordered


def container_names(beaker_path):
    result = command_result(compose_command("config", "--format", "json"), cwd=beaker_path, timeout=10)
    if result.returncode != 0:
        return []
    try:
        config = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return [service.get("container_name", name) for name, service in config.get("services", {}).items()]


def parse_env_file():
    values = {}
    if not COMPOSE_ENV_FILE.exists():
        return values
    for line in COMPOSE_ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def format_duration(seconds):
    if seconds is None:
        return "unavailable"
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def human_bytes(value):
    if value is None:
        return "unavailable"
    value = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024


def spinner_frame(index):
    return "|/-\\"[index % 4]
