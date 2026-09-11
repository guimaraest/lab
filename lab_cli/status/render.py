import json
import re

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lab_cli.constants import *
from lab_cli.helpers import command_result, compose_command, human_bytes
from lab_cli.status.collect import host_memory


BAR_WIDTH = 18
CONTAINER_BAR_WIDTH = 8


def visual_bar(ratio, width=BAR_WIDTH, color="#818CF8"):
    if ratio is None:
        return "[dim]░" * width + "[/dim]"
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * width)
    return f"[{color}]{'█' * filled}[/{color}][dim]{'░' * (width - filled)}[/dim]"


def parse_size(value):
    if value is None:
        return None
    match = re.match(r"^\s*([\d.]+)\s*([KMGTPE]?i?B)\s*$", str(value), re.IGNORECASE)
    if not match:
        return None
    units = {"b": 1, "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4, "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}
    return float(match.group(1)) * units.get(match.group(2).lower(), 1)


def ratio_bar(value, total, suffix="", width=BAR_WIDTH):
    if value is None or total in (None, 0):
        return visual_bar(None, width=width)
    ratio = value / total
    return f"{visual_bar(ratio, width=width)} {suffix}".rstrip()


def docker_total_bytes(docker_disk):
    return sum(parse_size(item.get("size")) or 0 for item in docker_disk.values())


def beaker_total_bytes(beaker):
    total = beaker.get("folder_size") or 0
    for volume in beaker.get("volumes", []):
        total += volume.get("size") or parse_size(volume.get("size_human")) or 0
    return total + beaker_image_bytes(beaker)


def beaker_image_bytes(beaker):
    config = command_result(
        compose_command("config", "--format", "json"),
        cwd=beaker.get("path"),
        timeout=10,
    )
    if config.returncode != 0:
        return 0
    try:
        services = json.loads(config.stdout).get("services", {}).values()
    except json.JSONDecodeError:
        return 0
    images = {service.get("image") for service in services if service.get("image")}
    total = 0
    for image in images:
        result = command_result(["docker", "image", "inspect", image, "--format", "{{.Size}}"], timeout=5)
        try:
            total += int(result.stdout.strip()) if result.returncode == 0 else 0
        except ValueError:
            continue
    return total


def storage_ratio_label(value, used_total):
    if value is None or not used_total:
        return "unavailable"
    return f"{value / used_total * 100:.1f}% of used"


def container_cpu_bar(container):
    value = container["stats"].get("CPUPerc", "")
    match = re.search(r"([\d.]+)", value)
    percent = float(match.group(1)) if match else None
    return ratio_bar(percent, 100, f"{percent:.1f}%" if percent is not None else "unavailable", CONTAINER_BAR_WIDTH)


def container_ram_bar(container, host_total):
    value = container["stats"].get("MemUsage", "")
    match = re.match(r"\s*([\d.]+\s*[KMGTPE]?i?B)", value, re.IGNORECASE)
    used = parse_size(match.group(1)) if match else None
    return ratio_bar(used, host_total, value.split("/")[0].strip().lower() if used is not None else "unavailable", CONTAINER_BAR_WIDTH)


def print_status(report):
    host = report["host"]
    disk = host["disk"]
    memory = host["memory"]
    cpu = host["cpu"]
    docker_disk = host["docker_disk"]
    fail2ban = host["fail2ban"]
    fail2ban_lines = []
    if fail2ban.get("available"):
        for jail in fail2ban["jails"]:
            fail2ban_lines.append(f"{jail['name']}: failed {jail.get('currently_failed', 'unavailable')} / {jail.get('total_failed', 'unavailable')}, banned {jail.get('currently_banned', 'unavailable')} / {jail.get('total_banned', 'unavailable')} ({', '.join(jail.get('banned_ips', [])) or 'no IPs'})")
    else:
        fail2ban_lines.append(f"unavailable: {fail2ban.get('reason', 'unknown error')}")

    console = Console()
    state_style = {"healthy": "green", "degraded": "yellow", "unknown": "yellow"}.get(report["status"], "red")
    used_disk = disk["used"]
    docker_total = docker_total_bytes(docker_disk)
    host_text = "\n".join([
        f"[bold]status:[/bold] [{state_style}]{report['status']}[/{state_style}]",
        f"uptime: {host['uptime']}    last restart: {host['last_restart'] or 'unavailable'}",
        f"cpu: {cpu['usage_percent']}% used    load: {', '.join(f'{item:.2f}' for item in cpu['load'])}",
        f"cpu temperature: {host['temperature_celsius']} c    last os upgrade: {host['last_os_upgrade'] or 'unavailable'}",
        "fail2ban: " + "\n          ".join(fail2ban_lines),
    ]).lower()
    console.print(Panel(host_text, title="[bold #6366F1]lab host[/bold #6366F1]", border_style="#6366F1", expand=False))

    storage_table = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    storage_table.add_column("resource", width=11, no_wrap=True)
    storage_table.add_column("usage", no_wrap=True)
    storage_table.add_column("size", no_wrap=True)
    storage_table.add_column("share", no_wrap=True)
    storage_table.add_row("ram", visual_bar((memory["used"] / memory["total"]) if memory["total"] else None), f"{memory['used_human']} / {memory['total_human']}".lower(), storage_ratio_label(memory["used"], memory["total"]).lower())
    storage_table.add_row("disk", visual_bar((disk["used"] / disk["total"]) if disk["total"] else None), f"{disk['used_human']} / {disk['total_human']}".lower(), storage_ratio_label(disk["used"], disk["total"]).lower())
    storage_table.add_row("docker", visual_bar(docker_total / used_disk if docker_total and used_disk else None), human_bytes(docker_total).lower() if docker_total else "unavailable", storage_ratio_label(docker_total, used_disk).lower())
    for beaker in report["beakers"]:
        beaker_total = beaker_total_bytes(beaker)
        storage_table.add_row(
            str(beaker["name"]).lower(),
            visual_bar(beaker_total / used_disk if beaker_total and used_disk else None),
            human_bytes(beaker_total).lower() if beaker_total else "unavailable",
            storage_ratio_label(beaker_total, used_disk).lower(),
        )
    console.print(Panel(storage_table, title="[bold #6366F1]storage[/bold #6366F1]", border_style="#818CF8", expand=False))

    table = Table(title="[bold #6366F1]container details[/bold #6366F1]", border_style="#818CF8", header_style="#A78BFA", padding=(0, 1), expand=False)
    for column in ("beaker", "container", "status", "health", "uptime", "restarts", "cpu", "ram"):
        table.add_column(column, no_wrap=True, overflow="ellipsis")
    for beaker in report["beakers"]:
        for container in beaker["containers"]:
            style = "green" if container["status"] == "running" and container["health"] in ("healthy", "none") else "red"
            table.add_row(*[str(value).lower() for value in (beaker["name"], container["name"], container["status"], container["health"], container["uptime"], container["restart_count"])], container_cpu_bar(container), container_ram_bar(container, memory["total"]), style=style)
    console.print(table)


def print_beaker_status(beaker):
    console = Console()
    host_total = host_memory()["total"]
    table = Table(title=f"[bold #6366F1]{str(beaker['name']).lower()}[/bold #6366F1]", border_style="#818CF8", header_style="#A78BFA", padding=(0, 1), expand=False)
    for column in ("container", "status", "health", "uptime", "restarts", "cpu", "ram"):
        table.add_column(column, no_wrap=True, overflow="ellipsis")
    for container in beaker["containers"]:
        table.add_row(
            *[str(value).lower() for value in (container["name"], container["status"], container["health"], container["uptime"], container["restart_count"])],
            container_cpu_bar(container),
            container_ram_bar(container, host_total),
        )
    console.print(table)
