import json
import time

from constants import *


def network_exists(name):
    return run(["docker", "network", "inspect", name], capture=True).returncode == 0


def wait_healthy(beaker_path, name):
    names = container_names(beaker_path)
    if not names:
        return True

    deadline = time.time() + HEALTH_TIMEOUT
    frame = 0
    while time.time() < deadline:
        all_ready = True
        waiting_for = []
        for container in names:
            inspect = run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}|{{.State.Status}}", container],
                capture=True,
            )
            if inspect.returncode != 0:
                all_ready = False
                waiting_for.append(f"{container} (starting)")
                continue
            health, status = inspect.stdout.strip().split("|", 1)
            ready = health == "healthy" if health != "<no value>" else status == "running"
            if not ready:
                all_ready = False
                waiting_for.append(f"{container} ({health if health != '<no value>' else status})")
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
        time.sleep(HEALTH_POLL_INTERVAL)

    print()
    print(f"warning: '{name}' did not report healthy within {HEALTH_TIMEOUT}s, continuing anyway")
    return False


def cmd_init(args):
    if network_exists(NETWORK):
        print(f"network '{NETWORK}' already exists")
    else:
        run(["docker", "network", "create", NETWORK])
        print(f"created network '{NETWORK}'")


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
        run(command, cwd=path)
        if not args.detach:
            wait_healthy(path, name)
        if args.logs:
            run(compose_command("logs"), cwd=path)


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


def beaker_up(name, build=False):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    print(f"starting '{name}'...")
    command = compose_command("up", "-d")
    if build:
        command.append("--build")
    run(command, cwd=path)
    wait_healthy(path, name)


def beaker_down(name):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    print(f"stopping '{name}'...")
    run(compose_command("down"), cwd=path)


def beaker_logs(name):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    run(compose_command("logs"), cwd=path)
