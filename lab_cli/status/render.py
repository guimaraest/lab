import json
import re

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lab_cli.constants import *
from lab_cli.helpers import human_bytes
from lab_cli.status.collect import host_memory


BAR_WIDTH = 18


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


def ratio_bar(value, total, suffix=""):
    if value is None or total in (None, 0):
        return visual_bar(None)
    ratio = value / total
    return f"{visual_bar(ratio)} {suffix}".rstrip()


def docker_total_bytes(docker_disk):
    return sum(parse_size(item.get("size")) or 0 for item in docker_disk.values())


def beaker_total_bytes(beaker):
    total = beaker.get("folder_size") or 0
    for volume in beaker.get("volumes", []):
        total += volume.get("size") or parse_size(volume.get("size_human")) or 0
    return total


def storage_ratio_label(value, used_total):
    if value is None or not used_total:
        return "unavailable"
    return f"{value / used_total * 100:.1f}% of used"


def container_cpu_bar(container):
    value = container["stats"].get("CPUPerc", "")
    match = re.search(r"([\d.]+)", value)
    percent = float(match.group(1)) if match else None
    return ratio_bar(percent, 100, f"{percent:.1f}%" if percent is not None else "unavailable")


def container_ram_bar(container, host_total):
    value = container["stats"].get("MemUsage", "")
    match = re.match(r"\s*([\d.]+\s*[KMGTPE]?i?B)", value, re.IGNORECASE)
    used = parse_size(match.group(1)) if match else None
    return ratio_bar(used, host_total, value.split("/")[0].strip() if used is not None else "unavailable")


def container_row(container):
    stats = container["stats"]
    return [container["name"], container["status"], container["health"], container["uptime"], str(container["restart_count"]), stats.get("CPUPerc", "unavailable"), stats.get("MemUsage", "unavailable")]


def print_status(report):
    host = report["host"]
    disk = host["disk"]
    memory = host["memory"]
    cpu = host["cpu"]
    docker_disk = host["docker_disk"]
    docker_summary = ", ".join(f"{label}={docker_disk[label].get('size', 'unavailable')}" for label in ("images", "containers", "local volumes", "build cache") if label in docker_disk) or "unavailable"
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
    storage_text = "\n".join([
        f"RAM    {visual_bar((memory['used'] / memory['total']) if memory['total'] else None)} {memory['used_human']} / {memory['total_human']}",
        f"Disk   {visual_bar((disk['used'] / disk['total']) if disk['total'] else None)} {disk['used_human']} / {disk['total_human']}",
        f"Docker {visual_bar(docker_total / used_disk if docker_total and used_disk else None, color='#A78BFA')} {human_bytes(docker_total) if docker_total else 'unavailable'} ({storage_ratio_label(docker_total, used_disk)})",
    ])
    for beaker in report["beakers"]:
        beaker_total = beaker_total_bytes(beaker)
        storage_text += "\n" + f"{beaker['name']:<11} {visual_bar(beaker_total / used_disk if beaker_total and used_disk else None, color='#818CF8')} {human_bytes(beaker_total) if beaker_total else 'unavailable'} ({storage_ratio_label(beaker_total, used_disk)})"
    host_text = "\n".join([
        f"[bold]Status:[/bold] [{state_style}]{report['status']}[/{state_style}]",
        f"Uptime: {host['uptime']}    Last restart: {host['last_restart'] or 'unavailable'}",
        f"CPU: {cpu['usage_percent']}% used    Load: {', '.join(f'{item:.2f}' for item in cpu['load'])}",
        f"CPU temperature: {host['temperature_celsius']} C    Last OS upgrade: {host['last_os_upgrade'] or 'unavailable'}",
        "Fail2ban: " + "\n          ".join(fail2ban_lines),
    ])
    console.print(Panel(host_text, title="[bold #6366F1]Lab Host[/bold #6366F1]", border_style="#6366F1", expand=False))
    console.print(Panel(storage_text, title="[bold #6366F1]Storage[/bold #6366F1]", border_style="#818CF8", expand=False))

    table = Table(title="[bold #6366F1]Container Details[/bold #6366F1]", border_style="#818CF8", header_style="#A78BFA")
    for column in ("Beaker", "Container", "Status", "Health", "Uptime", "Restarts", "CPU", "RAM"):
        table.add_column(column)
    for beaker in report["beakers"]:
        for container in beaker["containers"]:
            style = "green" if container["status"] == "running" and container["health"] in ("healthy", "none") else "red"
            table.add_row(beaker["name"], container["name"], container["status"], container["health"], container["uptime"], str(container["restart_count"]), container_cpu_bar(container), container_ram_bar(container, memory["total"]), style=style)
    console.print(table)


def print_beaker_status(beaker):
    console = Console()
    host_total = host_memory()["total"]
    table = Table(title=f"[bold #6366F1]{beaker['name']}[/bold #6366F1]", border_style="#818CF8", header_style="#A78BFA")
    for column in ("Container", "Status", "Health", "Uptime", "Restarts", "CPU", "RAM"):
        table.add_column(column)
    for container in beaker["containers"]:
        table.add_row(
            container["name"],
            container["status"],
            container["health"],
            container["uptime"],
            str(container["restart_count"]),
            container_cpu_bar(container),
            container_ram_bar(container, host_total),
        )
    console.print(table)
