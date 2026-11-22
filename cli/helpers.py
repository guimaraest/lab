import json
import os
import re
import subprocess
import sys

import yaml

from cli.constants import *
from cli.notifications import notify


def run(cmd, cwd=None, capture=False, timeout=None, env=None):
    if cmd[:2] == ["docker", "compose"]:
        env = compose_environment(env, cwd=cwd)
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")


def command_result(cmd, cwd=None, timeout=5):
    return run(cmd, cwd=cwd, capture=True, timeout=timeout)


def command_text(cmd, cwd=None, timeout=5):
    result = command_result(cmd, cwd=cwd, timeout=timeout)
    return result.stdout.strip() if result.returncode == 0 else ""


def compose_command(*args):
    return ["docker", "compose", *args]


def load_settings():
    with CONFIG_PATH.open() as config_file:
        settings = yaml.safe_load(config_file) or {}
    validate_config(settings)
    return settings


def read_beaker_manifest(name):
    manifest_path = LAB_ROOT / name / ".beaker"
    if not manifest_path.is_file():
        raise SystemExit(f"beaker '{name}' is missing {manifest_path.relative_to(LAB_ROOT)}")
    try:
        with manifest_path.open() as manifest_file:
            manifest = yaml.safe_load(manifest_file) or {}
    except yaml.YAMLError as error:
        raise SystemExit(f"invalid beaker manifest '{manifest_path.relative_to(LAB_ROOT)}': {error}")
    if not isinstance(manifest, dict):
        raise SystemExit(f"invalid beaker manifest '{manifest_path.relative_to(LAB_ROOT)}': expected a mapping")
    for field in ("aliases", "tests", "environment"):
        values = manifest.get(field)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise SystemExit(
                f"invalid beaker manifest '{manifest_path.relative_to(LAB_ROOT)}': '{field}' must be a list of strings"
            )
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in manifest["environment"]):
        raise SystemExit(
            f"invalid beaker manifest '{manifest_path.relative_to(LAB_ROOT)}': invalid environment variable key"
        )
    for field in ("aliases", "tests"):
        if len(manifest[field]) != len(set(manifest[field])):
            raise SystemExit(f"invalid beaker manifest '{manifest_path.relative_to(LAB_ROOT)}': duplicate {field}")
    main_service = manifest.get("main_service")
    if not isinstance(main_service, str) or not main_service.strip():
        raise SystemExit(
            f"invalid beaker manifest '{manifest_path.relative_to(LAB_ROOT)}': 'main_service' must be a non-empty string"
        )
    if len(manifest["environment"]) != len(set(manifest["environment"])):
        raise SystemExit(
            f"invalid beaker manifest '{manifest_path.relative_to(LAB_ROOT)}': duplicate environment keys"
        )
    return manifest


def load_config(settings=None):
    settings = settings or load_settings()
    beakers = settings["beakers"]
    for name, config in beakers.items():
        manifest = read_beaker_manifest(name)
        config.update({field: manifest[field] for field in ("aliases", "main_service", "tests")})
    return beakers


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
            notify("warning", message, source="config")
            warned.add(message)

    for name, config in beakers.items():
        if not isinstance(config, dict):
            raise SystemExit(f"invalid config: beaker '{name}' must be a mapping")
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


def beaker_enabled(config):
    return config.get("enabled", True)


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


def container_names(beaker_path, actual_only=False):
    result = command_result(
        compose_command("ps", "--all", "--quiet"),
        cwd=beaker_path,
        timeout=10,
    )
    if result.returncode == 0:
        container_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if container_ids:
            inspected = command_result(
                ["docker", "inspect", "--format", "{{.Name}}", *container_ids],
                timeout=10,
            )
            if inspected.returncode == 0:
                return [line.strip().lstrip("/") for line in inspected.stdout.splitlines() if line.strip()]
            return []
        if actual_only:
            return []
    elif actual_only:
        return []

    result = command_result(compose_command("config", "--format", "json"), cwd=beaker_path, timeout=10)
    if result.returncode != 0:
        return []
    try:
        config = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return [service.get("container_name", name) for name, service in config.get("services", {}).items()]


def parse_env_file():
    if not COMPOSE_ENV_FILE.exists():
        return {}
    raw_values = {}
    for line in COMPOSE_ENV_FILE.read_text().splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        if value.startswith(("'", '"')):
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end >= 0 else value[1:]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        raw_values[key] = value

    resolved = {}
    resolving = set()

    def resolve(key):
        if key in resolved:
            return resolved[key]
        if key in resolving:
            return ""
        resolving.add(key)
        value = raw_values.get(key, "")
        def substitute(match):
            name = match.group(1)
            return os.environ[name] if name in os.environ else resolve(name)

        value = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", substitute, value)
        resolving.remove(key)
        resolved[key] = value
        return value

    for key in raw_values:
        resolve(key)
    return resolved


def compose_environment(base=None, cwd=None):
    environment = dict(os.environ if base is None else base)
    file_values = parse_env_file()
    working_directory = Path(cwd or Path.cwd()).resolve()
    if not working_directory.is_relative_to(LAB_ROOT):
        raise SystemExit(f"cannot determine Compose environment outside the repository: '{working_directory}'")
    while working_directory != LAB_ROOT.parent and working_directory != working_directory.parent:
        if (working_directory / ".beaker").is_file():
            name = working_directory.relative_to(LAB_ROOT).as_posix()
            manifest = read_beaker_manifest(name)
            keys = set(manifest["environment"])
            for key in file_values:
                if key not in keys:
                    environment.pop(key, None)
            for key in keys:
                if key not in environment and key in file_values:
                    environment[key] = file_values[key]
            return environment
        if working_directory == LAB_ROOT:
            break
        working_directory = working_directory.parent
    raise SystemExit(f"cannot determine Compose environment: no .beaker manifest found from '{cwd or Path.cwd()}'")


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
