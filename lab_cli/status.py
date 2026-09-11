import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from constants import *


def host_cpu_usage():
    def read_times():
        fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        values = [int(value) for value in fields]
        return sum(values), values[3] + (values[4] if len(values) > 4 else 0)

    try:
        first_total, first_idle = read_times()
        time.sleep(0.1)
        second_total, second_idle = read_times()
        total_delta = second_total - first_total
        idle_delta = second_idle - first_idle
        return round(100 * (total_delta - idle_delta) / total_delta, 1) if total_delta else 0.0
    except (OSError, ValueError, IndexError):
        return None


def host_memory():
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
        total = values["MemTotal"]
        available = values["MemAvailable"]
        used = total - available
        return {"used": used, "total": total, "percent": round(100 * used / total, 1)}
    except (OSError, KeyError, ValueError):
        return {"used": None, "total": None, "percent": None}


def host_temperature():
    readings = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            readings.append(int(path.read_text().strip()) / 1000)
        except (OSError, ValueError):
            continue
    if readings:
        return max(readings)

    output = command_text(["sensors"], timeout=3)
    temperatures = [float(value) for value in re.findall(r"([+-]?\d+(?:\.\d+)?)°C", output)]
    return max(temperatures) if temperatures else None


def boot_time():
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def last_os_upgrade():
    candidates = [
        Path("/var/log/apt/history.log"),
        Path("/var/log/dpkg.log"),
        Path("/var/log/yum.log"),
        Path("/var/log/dnf.log"),
    ]
    existing = [path for path in candidates if path.exists()]
    return max((path.stat().st_mtime for path in existing), default=None)


def fail2ban_report():
    if not shutil.which("fail2ban-client"):
        return {"available": False, "jails": []}
    output = command_text(["fail2ban-client", "status"], timeout=5)
    if not output:
        return {"available": False, "jails": []}
    match = re.search(r"Jail list:\s*(.*)", output)
    jails = []
    for jail in [item.strip() for item in (match.group(1).split(",") if match else []) if item.strip()]:
        jail_output = command_text(["fail2ban-client", "status", jail], timeout=5)
        report = {"name": jail}
        for label, key in (
            ("Currently banned", "currently_banned"),
            ("Total banned", "total_banned"),
            ("Currently failed", "currently_failed"),
            ("Total failed", "total_failed"),
        ):
            found = re.search(rf"{re.escape(label)}:\s*(\d+)", jail_output)
            if found:
                report[key] = int(found.group(1))
        jails.append(report)
    return {"available": True, "jails": jails}


def docker_inspect(container):
    result = command_result(["docker", "inspect", container], timeout=5)
    if result.returncode != 0:
        print(f"warning: docker inspect {container} failed: {result.stderr.strip() or 'unknown error'}", file=sys.stderr)
        return {}
    try:
        return json.loads(result.stdout)[0]
    except (IndexError, json.JSONDecodeError) as error:
        print(f"warning: could not parse docker inspect {container}: {error}", file=sys.stderr)
        return {}


def docker_stats():
    result = command_result(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=10)
    if result.returncode != 0:
        print(f"warning: docker stats failed: {result.stderr.strip() or 'unknown error'}", file=sys.stderr)
        return {}
    stats = {}
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
            name = item.get("Name") or item.get("Container")
            if name:
                stats[name] = item
        except json.JSONDecodeError as error:
            print(f"warning: could not parse docker stats row: {error}", file=sys.stderr)
            continue
    return stats


def container_status(container, stats):
    inspected = docker_inspect(container)
    state = inspected.get("State", {})
    started = state.get("StartedAt")
    started_timestamp = None
    if started:
        try:
            started_timestamp = datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    if state.get("Status") == "running" and container not in stats:
        print(f"warning: docker stats returned no row for running container {container}", file=sys.stderr)
    return {
        "name": container,
        "status": state.get("Status", "unavailable"),
        "health": state.get("Health", {}).get("Status", "none"),
        "started_at": started,
        "uptime": format_duration(time.time() - started_timestamp) if started_timestamp else "unavailable",
        "restart_count": state.get("RestartCount", 0),
        "stats": stats.get(container, {}),
    }


def beaker_domains(name):
    def real_domains(values):
        return [
            value for value in values
            if value and "yourdomain.com" not in value and value not in {"localhost", "example.com"}
        ]

    domains = []
    if name == "nextcloud":
        domains.extend(real_domains(parse_env_file().get("NEXTCLOUD_TRUSTED_DOMAINS", "").split()))
    if name == "cloudflared":
        config_path = LAB_ROOT / "cloudflared" / "config.yml"
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text()) or {}
            domains.extend(real_domains(entry.get("hostname") for entry in config.get("ingress", [])))
    return sorted(set(domain for domain in domains if domain))


def compose_config(path):
    result = command_result(compose_command("config", "--format", "json"), cwd=path, timeout=10)
    if result.returncode != 0:
        print(
            f"warning: docker compose config for {path.name} failed: "
            f"{result.stderr.strip() or 'unknown error'}",
            file=sys.stderr,
        )
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        print(f"warning: could not parse compose config for {path.name}: {error}", file=sys.stderr)
        return {}


def docker_volume_df():
    result = command_result(["docker", "system", "df", "-v"], timeout=15)
    if result.returncode != 0:
        return {}
    sizes = {}
    in_volume_section = False
    for line in result.stdout.splitlines():
        if line.startswith("Local Volumes space usage:"):
            in_volume_section = True
            continue
        if in_volume_section and line.startswith("Build cache usage:"):
            break
        if not in_volume_section:
            continue
        match = re.match(r"^\s*(\S+)\s+\d+\s+(\S+)\s*$", line)
        if match:
            sizes[match.group(1)] = match.group(2)
    return sizes


def volume_size(volume_name, fallback_sizes):
    inspect = command_result(["docker", "volume", "inspect", volume_name], timeout=5)
    if inspect.returncode != 0:
        print(
            f"warning: docker volume inspect {volume_name} failed: "
            f"{inspect.stderr.strip() or 'unknown error'}",
            file=sys.stderr,
        )
        fallback = fallback_sizes.get(volume_name)
        return {"bytes": None, "human": fallback} if fallback else None
    try:
        mountpoint = json.loads(inspect.stdout)[0]["Mountpoint"]
    except (IndexError, KeyError, json.JSONDecodeError) as error:
        print(f"warning: could not find mountpoint for volume {volume_name}: {error}", file=sys.stderr)
        return None
    output = command_text(["du", "-sb", mountpoint], timeout=15)
    try:
        return int(output.split()[0])
    except (IndexError, ValueError):
        fallback = fallback_sizes.get(volume_name)
        if fallback:
            return {"bytes": None, "human": fallback}
        print(f"warning: could not measure volume {volume_name} at {mountpoint}", file=sys.stderr)
        return None


def beaker_volumes(path):
    config = compose_config(path)
    fallback_sizes = docker_volume_df()
    volume_names = set()
    for key, volume in config.get("volumes", {}).items():
        if volume.get("Name") or volume.get("name"):
            volume_names.add(volume.get("Name") or volume["name"])
        elif key:
            volume_names.add(key)
    result = []
    for name in sorted(volume_names):
        size = volume_size(name, fallback_sizes)
        if isinstance(size, dict):
            result.append({"name": name, "size": size["bytes"], "size_human": size["human"]})
        else:
            result.append({"name": name, "size": size, "size_human": human_bytes(size)})
    return result


def docker_disk_usage():
    result = command_result(["docker", "system", "df", "--format", "{{json .}}"], timeout=15)
    if result.returncode != 0:
        result = command_result(["docker", "system", "df"], timeout=15)
        if result.returncode != 0:
            print(f"warning: docker system df failed: {result.stderr.strip() or 'unknown error'}", file=sys.stderr)
            return {}
        usage = {}
        for line in result.stdout.splitlines():
            match = re.match(r"^(Images|Containers|Local Volumes|Build Cache)\s+(.+?)\s+(\S+)\s+(\S+)\s+(.+)$", line.strip())
            if match:
                row_type, total, active, size, reclaimable = match.groups()
                usage[row_type.lower()] = {
                    "total": total,
                    "active": active,
                    "size": size,
                    "reclaimable": reclaimable,
                }
        return usage
    usage = {}
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row_type = row.get("Type") or row.get("type")
        if row_type:
            usage[row_type.lower()] = {
                "total": row.get("Total") or row.get("total") or row.get("TotalCount"),
                "total_count": row.get("TotalCount") or row.get("total_count"),
                "active": row.get("Active") or row.get("active"),
                "size": row.get("Size") or row.get("size"),
                "reclaimable": row.get("Reclaimable") or row.get("reclaimable"),
            }
    return usage


def beaker_status(name, path, stats):
    containers = [container_status(container, stats) for container in container_names(path)]
    started_values = [item["started_at"] for item in containers if item["started_at"]]
    started_timestamp = None
    if started_values:
        started_timestamp = min(
            datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            for value in started_values
        )
    folder_size = None
    du_output = command_text(["du", "-sb", str(path)], timeout=10)
    if du_output:
        try:
            folder_size = int(du_output.split()[0])
        except (ValueError, IndexError):
            pass
    return {
        "name": name,
        "path": str(path),
        "domains": beaker_domains(name),
        "folder_size": folder_size,
        "folder_size_human": human_bytes(folder_size),
        "volumes": beaker_volumes(path),
        "uptime": format_duration(time.time() - started_timestamp) if started_timestamp else "unavailable",
        "containers": containers,
    }


def host_status():
    memory = host_memory()
    disk = shutil.disk_usage("/")
    boot = boot_time()
    upgrade = last_os_upgrade()
    return {
        "uptime": format_duration(time.time() - boot) if boot else "unavailable",
        "last_restart": datetime.fromtimestamp(boot).isoformat(timespec="seconds") if boot else None,
        "cpu": {"usage_percent": host_cpu_usage(), "load": list(__import__("os").getloadavg())},
        "memory": {
            "used": memory["used"],
            "used_human": human_bytes(memory["used"]),
            "total": memory["total"],
            "total_human": human_bytes(memory["total"]),
            "percent": memory["percent"],
        },
        "temperature_celsius": host_temperature(),
        "disk": {
            "used": disk.used,
            "used_human": human_bytes(disk.used),
            "free": disk.free,
            "free_human": human_bytes(disk.free),
            "total": disk.total,
            "total_human": human_bytes(disk.total),
            "percent": round(100 * disk.used / disk.total, 1),
        },
        "docker_disk": docker_disk_usage(),
        "last_os_upgrade": datetime.fromtimestamp(upgrade).isoformat(timespec="seconds") if upgrade else None,
        "fail2ban": fail2ban_report(),
    }


def overall_state(beakers):
    containers = [container for beaker in beakers for container in beaker["containers"]]
    if not containers:
        return "unknown"
    return "healthy" if all(
        container["status"] == "running" and container["health"] in ("healthy", "none")
        for container in containers
    ) else "degraded"


def print_container(container):
    stats = container["stats"]
    cpu = stats.get("CPUPerc", "unavailable")
    memory = stats.get("MemUsage", "unavailable")
    print(
        f"    {container['name']}: {container['status']} / health={container['health']} "
        f"uptime={container['uptime']} restarts={container['restart_count']} "
        f"cpu={cpu} ram={memory}"
    )


def print_status(report):
    host = report["host"]
    disk = host["disk"]
    memory = host["memory"]
    cpu = host["cpu"]
    print(f"Lab status: {report['status']}")
    print(f"Host uptime: {host['uptime']} | last restart: {host['last_restart'] or 'unavailable'}")
    print(f"CPU: {cpu['usage_percent']}% used | load: {', '.join(f'{item:.2f}' for item in cpu['load'])}")
    print(f"RAM: {memory['used_human']} / {memory['total_human']} ({memory['percent']}%)")
    print(f"Disk /: {disk['free_human']} free / {disk['total_human']} ({disk['percent']}% used)")
    docker_disk = host["docker_disk"]
    if docker_disk:
        disk_parts = []
        for label in ("images", "containers", "local volumes", "build cache"):
            if label in docker_disk:
                disk_parts.append(f"{label}={docker_disk[label].get('size', 'unavailable')}")
        print(f"Docker disk: {', '.join(disk_parts)}")
    else:
        print("Docker disk: unavailable")
    print(f"CPU temperature: {host['temperature_celsius']} C | last OS upgrade: {host['last_os_upgrade'] or 'unavailable'}")
    print(f"Fail2ban: {host['fail2ban']}")
    print()
    for beaker in report["beakers"]:
        domains = ", ".join(beaker["domains"]) or "none configured"
        print(
            f"{beaker['name']}: folder={beaker['folder_size_human']} "
            f"uptime={beaker['uptime']} domains={domains}"
        )
        if beaker["volumes"]:
            print("  volumes: " + ", ".join(
                f"{volume['name']}={volume['size_human']}" for volume in beaker["volumes"]
            ))
        for container in beaker["containers"]:
            print_container(container)


def cmd_status(args):
    configured = load_config()
    stats = docker_stats()
    beakers = []
    for name in configured:
        path = LAB_ROOT / name
        if (path / "docker-compose.yml").exists():
            beakers.append(beaker_status(name, path, stats))

    report = {"status": overall_state(beakers), "host": host_status(), "beakers": beakers}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_status(report)


def get_beaker_status(name):
    path = LAB_ROOT / name
    if not (path / "docker-compose.yml").exists():
        raise SystemExit(f"beaker '{name}' has no docker-compose.yml")
    return beaker_status(name, path, docker_stats())


def print_beaker_status(beaker):
    domains = ", ".join(beaker["domains"]) or "none configured"
    print(
        f"{beaker['name']}: folder={beaker['folder_size_human']} "
        f"uptime={beaker['uptime']} domains={domains}"
    )
    for container in beaker["containers"]:
        print_container(container)
