import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
import psutil

from lab_cli.constants import *
from lab_cli.helpers import *
from lab_cli.notifications import notify, notify_once


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
        return psutil.boot_time()
    except (OSError, ValueError):
        return None
    return None


def last_os_upgrade():
    paths = [Path(path) for path in ("/var/log/apt/history.log", "/var/log/dpkg.log", "/var/log/yum.log", "/var/log/dnf.log")]
    existing = [path for path in paths if path.exists()]
    return max((path.stat().st_mtime for path in existing), default=None)


def os_version():
    result = command_result(["uname", "-r"], timeout=3)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unavailable"


def fail2ban_report():
    if not shutil.which("fail2ban-client"):
        return {"available": False, "reason": "fail2ban-client not installed", "jails": []}

    def fail2ban_command(*args):
        result = command_result(["sudo", "fail2ban-client", *args], timeout=5)
        if result.returncode != 0:
            return None, result.stderr.strip() or "permission denied reading the fail2ban socket"
        return result.stdout, None

    output, error = fail2ban_command("status")
    if error or not output:
        return {"available": False, "reason": error or "no fail2ban status returned", "jails": []}
    match = re.search(r"Jail list:\s*(.*)", output)
    jails = []
    jail_names = [item.strip() for item in (match.group(1).split(",") if match else []) if item.strip()]
    for jail in [name for name in jail_names if name == "sshd"]:
        jail_output, jail_error = fail2ban_command("status", jail)
        report = {"name": jail, "banned_ips": []}
        if jail_error:
            report.update(available=False, reason=jail_error)
            jails.append(report)
            continue
        for label, key in (("Currently banned", "currently_banned"), ("Total banned", "total_banned"), ("Currently failed", "currently_failed"), ("Total failed", "total_failed")):
            found = re.search(rf"{re.escape(label)}:\s*(\d+)", jail_output)
            if found:
                report[key] = int(found.group(1))
        banned = re.search(r"Banned IP list:\s*(.*)", jail_output)
        if banned and banned.group(1).strip():
            report["banned_ips"] = banned.group(1).split()
        jails.append(report)
    if "sshd" not in jail_names:
        jails.append({"name": "sshd", "available": False, "reason": "sshd jail not reported", "banned_ips": []})
    return {"available": True, "jails": jails}


def docker_inspect(container):
    result = command_result(["docker", "inspect", container], timeout=5)
    if result.returncode != 0:
        error = result.stderr.strip()
        if "no such object" in error.lower() or "no such container" in error.lower():
            return {}
        message = f"docker inspect {container} failed: {error or 'unknown error'}"
        print(f"warning: {message}", file=sys.stderr)
        notify_once(f"docker-inspect:{container}:{error}", "warning", message, source="status", container=container)
        return {}
    try:
        return json.loads(result.stdout)[0]
    except (IndexError, json.JSONDecodeError) as error:
        message = f"could not parse docker inspect {container}: {error}"
        print(f"warning: {message}", file=sys.stderr)
        notify_once(f"docker-inspect-parse:{container}:{error}", "warning", message, source="status", container=container)
        return {}


def docker_stats():
    result = command_result(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=10)
    if result.returncode != 0:
        message = f"docker stats failed: {result.stderr.strip() or 'unknown error'}"
        print(f"warning: {message}", file=sys.stderr)
        notify_once(f"docker-stats:{result.stderr.strip()}", "warning", message, source="status")
        return {}
    stats = {}
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
            name = item.get("Name") or item.get("Container")
            if name:
                stats[name] = item
        except json.JSONDecodeError as error:
            message = f"could not parse docker stats row: {error}"
            print(f"warning: {message}", file=sys.stderr)
            notify_once(f"docker-stats-parse:{error}", "warning", message, source="status")
    return stats


def container_status(container, stats):
    inspected = docker_inspect(container)
    state = inspected.get("State", {})
    started = state.get("StartedAt")
    started_timestamp = None
    if started:
        try:
            parsed = datetime.fromisoformat(started.replace("Z", "+00:00"))
            started_timestamp = parsed.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    if state.get("Status") == "running" and container not in stats:
        message = f"docker stats returned no row for running container {container}"
        print(f"warning: {message}", file=sys.stderr)
        notify("warning", message, source="status", container=container)
    restart_count = state.get("RestartCount", 0)
    if restart_count:
        notify_once(
            f"container-restart:{container}:{restart_count}",
            "warning",
            f"container {container} has restarted",
            source="status",
            container=container,
            restart_count=restart_count,
        )
    return {"name": container, "status": state.get("Status", "unavailable"), "health": state.get("Health", {}).get("Status", "none"), "started_at": started, "uptime": format_duration(time.time() - started_timestamp) if started_timestamp else "unavailable", "restart_count": restart_count, "stats": stats.get(container, {})}


def beaker_domains(name):
    def real_domains(values):
        return [value for value in values if value and "yourdomain.com" not in value and value not in {"localhost", "example.com"}]
    domains = []
    if name == "nextcloud":
        domains.extend(real_domains(parse_env_file().get("NEXTCLOUD_TRUSTED_DOMAINS", "").split()))
    if name == "cloudflared":
        config_path = LAB_ROOT / "cloudflared" / "config.yml"
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text()) or {}
            domains.extend(real_domains(entry.get("hostname") for entry in config.get("ingress", [])))
    return sorted(set(domains))


def compose_config(path):
    result = command_result(compose_command("config", "--format", "json"), cwd=path, timeout=10)
    if result.returncode != 0:
        message = f"docker compose config for {path.name} failed: {result.stderr.strip() or 'unknown error'}"
        print(f"warning: {message}", file=sys.stderr)
        notify("warning", message, source="status", beaker=path.name)
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        message = f"could not parse compose config for {path.name}: {error}"
        print(f"warning: {message}", file=sys.stderr)
        notify("warning", message, source="status", beaker=path.name)
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
        match = re.match(r"^\s*(\S+)\s+\d+\s+(\S+)\s*$", line) if in_volume_section else None
        if match:
            sizes[match.group(1)] = match.group(2)
    return sizes


def volume_size(name, fallback_sizes):
    inspect = command_result(["docker", "volume", "inspect", name], timeout=5)
    if inspect.returncode != 0:
        fallback = fallback_sizes.get(name)
        return {"bytes": None, "human": fallback} if fallback else None
    try:
        mountpoint = json.loads(inspect.stdout)[0]["Mountpoint"]
    except (IndexError, KeyError, json.JSONDecodeError):
        return None
    output = command_text(["du", "-sb", mountpoint], timeout=15)
    try:
        return int(output.split()[0])
    except (IndexError, ValueError):
        fallback = fallback_sizes.get(name)
        return {"bytes": None, "human": fallback} if fallback else None


def beaker_volumes(path):
    config = compose_config(path)
    fallback_sizes = docker_volume_df()
    names = set()
    for key, volume in config.get("volumes", {}).items():
        names.add(volume.get("Name") or volume.get("name") or key)
    result = []
    for name in sorted(names):
        size = volume_size(name, fallback_sizes)
        result.append({"name": name, "size": size.get("bytes"), "size_human": size.get("human")} if isinstance(size, dict) else {"name": name, "size": size, "size_human": human_bytes(size)})
    return result


def docker_disk_usage():
    result = command_result(["docker", "system", "df", "--format", "{{json .}}"], timeout=15)
    if result.returncode != 0:
        return {}
    usage = {}
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        row_type = row.get("Type") or row.get("type")
        if row_type:
            usage[row_type.lower()] = {"total": row.get("Total") or row.get("TotalCount"), "total_count": row.get("TotalCount"), "active": row.get("Active"), "size": row.get("Size"), "reclaimable": row.get("Reclaimable")}
    return usage


def cloudflare_status():
    config_path = LAB_ROOT / "cloudflared" / "config.yml"
    domains = []
    tunnel_id = None
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text()) or {}
        tunnel_id = config.get("tunnel")
        domains = [entry["hostname"] for entry in config.get("ingress", []) if entry.get("hostname")]

    metrics = ""
    for url in ("http://127.0.0.1:20241/metrics", "http://127.0.0.1:2000/metrics"):
        result = command_result(["curl", "-fsS", "--max-time", "2", url], timeout=3)
        if result.returncode == 0:
            metrics = result.stdout
            break

    access_count = None
    for metric in ("cloudflared_tunnel_total_requests", "cloudflared_tunnel_request_count", "cloudflared_proxy_connect_requests_total"):
        match = re.search(rf"^{metric}(?:\{{[^}}]*\}})?\s+([\d.eE+-]+)$", metrics, re.MULTILINE)
        if match:
            access_count = sum(float(value) for value in re.findall(rf"^{metric}(?:\{{[^}}]*\}})?\s+([\d.eE+-]+)$", metrics, re.MULTILINE))
            break

    tunnel_state = "unavailable"
    cloudflare_container = docker_inspect("cloudflared")
    if cloudflare_container:
        tunnel_state = cloudflare_container.get("State", {}).get("Status", "unavailable")
        health = cloudflare_container.get("State", {}).get("Health", {}).get("Status")
        if health:
            tunnel_state = health
    return {"tunnel_id": tunnel_id, "domains": domains, "state": tunnel_state, "access_count": access_count}


def beaker_status(name, path, stats):
    containers = [container_status(container, stats) for container in container_names(path)]
    starts = [item["started_at"] for item in containers if item["started_at"]]
    started_timestamp = min(
        datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc).timestamp()
        for value in starts
    ) if starts else None
    folder_size = None
    output = command_text(["du", "-sb", str(path)], timeout=10)
    if output:
        try:
            folder_size = int(output.split()[0])
        except (ValueError, IndexError):
            pass
    return {"name": name, "path": str(path), "domains": beaker_domains(name), "folder_size": folder_size, "folder_size_human": human_bytes(folder_size), "volumes": beaker_volumes(path), "uptime": format_duration(time.time() - started_timestamp) if started_timestamp else "unavailable", "containers": containers}


def host_status():
    memory = host_memory()
    disk = shutil.disk_usage("/")
    boot = boot_time()
    upgrade = last_os_upgrade()
    return {"uptime": format_duration(time.time() - boot) if boot else "unavailable", "boot_time": boot, "last_restart": datetime.fromtimestamp(boot).isoformat(timespec="seconds") if boot else None, "os_version": os_version(), "cpu": {"usage_percent": host_cpu_usage(), "load": list(os.getloadavg())}, "memory": {"used": memory["used"], "used_human": human_bytes(memory["used"]), "total": memory["total"], "total_human": human_bytes(memory["total"]), "percent": memory["percent"]}, "temperature_celsius": host_temperature(), "disk": {"used": disk.used, "used_human": human_bytes(disk.used), "free": disk.free, "free_human": human_bytes(disk.free), "total": disk.total, "total_human": human_bytes(disk.total), "percent": round(100 * disk.used / disk.total, 1)}, "docker_disk": docker_disk_usage(), "last_os_upgrade": datetime.fromtimestamp(upgrade).isoformat(timespec="seconds") if upgrade else None, "fail2ban": fail2ban_report(), "cloudflare": cloudflare_status()}


def overall_state(beakers):
    containers = [container for beaker in beakers for container in beaker["containers"]]
    if not containers:
        return "unknown"
    return "healthy" if all(container["status"] == "running" and container["health"] in ("healthy", "none") for container in containers) else "degraded"


def build_report():
    beakers = []
    stats = docker_stats()
    for name in load_config():
        path = LAB_ROOT / name
        if (path / "docker-compose.yml").exists():
            beakers.append(beaker_status(name, path, stats))
    return {"status": overall_state(beakers), "host": host_status(), "beakers": beakers}
