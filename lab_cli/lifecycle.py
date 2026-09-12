import argparse
import json
import os
import sys
import time

from lab_cli.constants import *
from lab_cli.helpers import *
from lab_cli.notifications import notify


def network_exists(name):
    return run(["docker", "network", "inspect", name], capture=True).returncode == 0


def wait_healthy(beaker_path, name, tolerance="low"):
    names = container_names(beaker_path)
    if not names:
        return True

    config = load_settings()["beakers"].get(name, {})
    poll_interval = (
        HIGH_TOLERANCE_HEALTH_POLL_INTERVAL
        if tolerance == "high"
        else config.get("wait_seconds", LOW_TOLERANCE_HEALTH_POLL_INTERVAL)
    )
    health_timeout = (
        HIGH_TOLERANCE_HEALTH_TIMEOUT
        if tolerance == "high"
        else LOW_TOLERANCE_HEALTH_TIMEOUT
    )
    deadline = time.time() + health_timeout
    frame = 0
    while time.time() < deadline:
        all_ready = True
        waiting_for = []
        for container in names:
            inspect = run(
                ["docker", "inspect", "--format", "{{json .State.Health}}", container],
                capture=True,
            )
            if inspect.returncode != 0:
                message = f"docker health inspect failed for {container}: {inspect.stderr.strip() or 'unknown error'}"
                print(f"warning: {message}", file=sys.stderr)
                notify("warning", message, source="healthcheck", beaker=name, container=container)
                all_ready = False
                waiting_for.append(f"{container} (starting)")
                continue
            try:
                health_state = json.loads(inspect.stdout.strip())
            except json.JSONDecodeError as error:
                message = f"could not parse docker health inspect for {container}: {error}"
                print(f"warning: {message}", file=sys.stderr)
                notify("warning", message, source="healthcheck", beaker=name, container=container)
                all_ready = False
                waiting_for.append(f"{container} (invalid health data)")
                continue
            if health_state is None:
                status_inspect = run(
                    ["docker", "inspect", "--format", "{{.State.Status}}", container],
                    capture=True,
                )
                status = status_inspect.stdout.strip()
                if status_inspect.returncode != 0 or not status:
                    message = f"could not read docker state for {container}: {status_inspect.stderr.strip() or 'unknown error'}"
                    print(f"warning: {message}", file=sys.stderr)
                    notify("warning", message, source="healthcheck", beaker=name, container=container)
                    all_ready = False
                    waiting_for.append(f"{container} (unavailable)")
                    continue
                health = status
                ready = status == "running"
            elif isinstance(health_state, dict) and isinstance(health_state.get("Status"), str):
                health = health_state["Status"]
                ready = health == "healthy"
            else:
                message = f"unexpected docker health data for {container}: {health_state!r}"
                print(f"warning: {message}", file=sys.stderr)
                notify("warning", message, source="healthcheck", beaker=name, container=container)
                all_ready = False
                waiting_for.append(f"{container} (invalid health data)")
                continue
            if not ready:
                all_ready = False
                waiting_for.append(f"{container} ({health})")
        if all_ready:
            print(f"\r{name}: ready" + " " * 20, flush=True)
            return True
        print(
            f"\r{name}: waiting {spinner_frame(frame)} "
            f"({', '.join(waiting_for) or 'starting'})",
            end="",
            flush=True,
        )
        frame += 1
        time.sleep(poll_interval)

    print()
    message = f"'{name}' did not report healthy within {health_timeout}s, continuing anyway"
    print(f"warning: {message}")
    notify("warning", message, source="healthcheck", beaker=name)
    return False


def cmd_init(args):
    if network_exists(NETWORK):
        print(f"network '{NETWORK}' already exists")
    else:
        run(["docker", "network", "create", NETWORK])
        print(f"created network '{NETWORK}'")
        notify("status", f"created network '{NETWORK}'", source="lifecycle")


def cmd_up(args):
    beakers = load_config()
    selected = selected_beakers(beakers, args.beakers)

    for name in topological_order(beakers, selected or None):
        config = beakers[name]
        if not selected and not config.get("autostart", True):
            print(f"skipping '{name}' (autostart disabled)")
            continue

        path = LAB_ROOT / name
        if not (path / "docker-compose.yml").exists():
            print(f"skipping '{name}' (no docker-compose.yml)")
            continue

        print(f"starting '{name}'...")
        command = compose_command("up", "-d")
        if args.build:
            command.append("--build")
        env = None
        if args.tolerance == "high":
            env = os.environ.copy()
            env["HEALTHCHECK_RETRIES"] = str(HIGH_TOLERANCE_HEALTHCHECK_RETRIES)
        run(command, cwd=path, env=env)
        if not args.detach:
            wait_healthy(path, name, tolerance=args.tolerance)
        if args.logs:
            run(compose_command("logs"), cwd=path)


def cmd_restart(args):
    settings = load_settings()
    beakers = settings["beakers"]
    selected = [name for name, config in beakers.items() if config.get("allow_restart", False)]
    order = [name for name in topological_order(beakers) if name in selected]
    retries = settings.get("restart_max_retries", 5)

    tolerance = getattr(args, "tolerance", "low")
    for attempt in range(1, retries + 1):
        print(f"restart attempt {attempt}/{retries}...")
        notify("status", "restart attempt started", source="restart", attempt=attempt, total_attempts=retries)
        for name in reversed(order):
            beaker_down(name)
        healthy = True
        for name in order:
            if not beaker_up(name, tolerance=tolerance):
                healthy = False
                break
        if healthy:
            print("scheduled restart completed successfully")
            notify("status", "scheduled restart completed successfully", source="restart", attempt=attempt)
            return

    message = (
        "restart retries exhausted; bringing the entire server down "
        "because the stack could not be verified"
    )
    print(message)
    notify("error", message, source="restart", attempts=retries)
    # Shut down the full graph so no service remains in a partially verified state.
    cmd_down(argparse.Namespace(beakers=[]))


def cmd_down(args):
    beakers = load_config()
    selected = selected_beakers(beakers, args.beakers)

    for name in reversed(topological_order(beakers, selected or None)):
        path = LAB_ROOT / name
        if not (path / "docker-compose.yml").exists():
            print(f"skipping '{name}' (no docker-compose.yml)")
            continue

        print(f"stopping '{name}'...")
        run(compose_command("down"), cwd=path)


def beaker_up(name, build=False, tolerance="low"):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    print(f"starting '{name}'...")
    command = compose_command("up", "-d")
    if build:
        command.append("--build")
    env = None
    if tolerance == "high":
        env = os.environ.copy()
        env["HEALTHCHECK_RETRIES"] = str(HIGH_TOLERANCE_HEALTHCHECK_RETRIES)
    run(command, cwd=path, env=env)
    return wait_healthy(path, name, tolerance=tolerance)


def beaker_down(name):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    print(f"stopping '{name}'...")
    run(compose_command("down"), cwd=path)


def restart_beaker(name):
    beaker_down(name)
    beaker_up(name)


def beaker_logs(name):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    run(compose_command("logs"), cwd=path)
