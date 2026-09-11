import json
import re
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lab_cli.constants import *
from lab_cli.helpers import command_result, compose_command, human_bytes
from lab_cli.status.collect import host_memory
from lab_cli.status.colors import DEGRADED, DIM, ERROR, HEALTHY, INDIGO, INDIGO_FILL, INDIGO_LIGHT


BAR_WIDTH = 18
CONTAINER_BAR_WIDTH = 8


@dataclass(frozen=True)
class MetricBar:
    label: str
    value: str
    ratio: float | None = None
    color: str = INDIGO_FILL

    def render(self):
        return visual_bar(self.ratio, color=self.color)


def key_value_panel(title, values, border=INDIGO):
    table = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    table.add_column("label", style="bold", no_wrap=True)
    table.add_column("value", no_wrap=False)
    for label, value in values:
        table.add_row(label.lower(), str(value).lower())
    return Panel(table, title=f"[bold {border}]{title.lower()}[/bold {border}]", border_style=border, expand=False)


def visual_bar(ratio, width=BAR_WIDTH, color="#818CF8"):
    if ratio is None:
        return f"[{DIM}]░" * width + f"[/{DIM}]"
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * width)
    return f"[{color}]{'█' * filled}[/{color}][{DIM}]{'░' * (width - filled)}[/{DIM}]"


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
            fail2ban_lines.append(
                f"jail {jail['name']}: failures {jail.get('currently_failed', 'unavailable')} current / "
                f"{jail.get('total_failed', 'unavailable')} total; bans "
                f"{jail.get('currently_banned', 'unavailable')} current / "
                f"{jail.get('total_banned', 'unavailable')} total; ips: "
                f"{', '.join(jail.get('banned_ips', [])) or 'none'}"
            )
    else:
        fail2ban_lines.append(f"status unavailable: {fail2ban.get('reason', 'unknown error')}")

    console = Console()
    state_style = {"healthy": "green", "degraded": "yellow", "unknown": "yellow"}.get(report["status"], "red")
    used_disk = disk["used"]
    docker_total = docker_total_bytes(docker_disk)
    console.print(key_value_panel("os", [
        ("status", f"[{state_style}]{report['status']}[/{state_style}]"),
        ("os version", host.get("os_version", "unavailable")),
        ("uptime", host["uptime"]),
        ("last restart", host["last_restart"] or "unavailable"),
        ("cpu", f"{cpu['usage_percent']}% used"),
        ("load", ", ".join(f"{item:.2f}" for item in cpu["load"])),
        ("temperature", f"{host['temperature_celsius']} c"),
        ("last os upgrade", host["last_os_upgrade"] or "unavailable"),
    ]))

    cloudflare = host.get("cloudflare", {})
    console.print(key_value_panel("networking", [
        ("cloudflare tunnel", cloudflare.get("state", "unavailable")),
        ("tunnel id", cloudflare.get("tunnel_id", "unavailable")),
        ("domains", ", ".join(cloudflare.get("domains", [])) or "none configured"),
        ("accesses", cloudflare.get("access_count", "unavailable")),
        ("docker network", NETWORK),
        ("fail2ban", "\n".join(fail2ban_lines)),
    ], border=INDIGO_LIGHT))

    storage_table = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    storage_table.add_column("resource", width=11, no_wrap=True)
    storage_table.add_column("usage", no_wrap=True)
    storage_table.add_column("size", no_wrap=True)
    storage_table.add_column("share", no_wrap=True)
    storage_metrics = [
        MetricBar("ram", f"{memory['used_human']} / {memory['total_human']}", memory["used"] / memory["total"] if memory["total"] else None),
        MetricBar("disk", f"{disk['used_human']} / {disk['total_human']}", disk["used"] / disk["total"] if disk["total"] else None),
        MetricBar("docker", human_bytes(docker_total) if docker_total else "unavailable", docker_total / used_disk if docker_total and used_disk else None),
    ]
    for metric in storage_metrics:
        total = memory["total"] if metric.label == "ram" else disk["total"] if metric.label == "disk" else used_disk
        value = memory["used"] if metric.label == "ram" else disk["used"] if metric.label == "disk" else docker_total
        storage_table.add_row(metric.label, metric.render(), metric.value.lower(), storage_ratio_label(value, total).lower())
    for beaker in report["beakers"]:
        beaker_total = beaker_total_bytes(beaker)
        metric = MetricBar(str(beaker["name"]).lower(), human_bytes(beaker_total) if beaker_total else "unavailable", beaker_total / used_disk if beaker_total and used_disk else None)
        storage_table.add_row(metric.label, metric.render(), metric.value.lower(), storage_ratio_label(beaker_total, used_disk).lower())
    console.print(Panel(storage_table, title=f"[bold {INDIGO}]storage[/bold {INDIGO}]", border_style=INDIGO_FILL, expand=False))

    table = Table(title=f"[bold {INDIGO}]container details[/bold {INDIGO}]", border_style=INDIGO_FILL, header_style=INDIGO_LIGHT, padding=(0, 1), expand=False)
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
    table = Table(title=f"[bold {INDIGO}]{str(beaker['name']).lower()}[/bold {INDIGO}]", border_style=INDIGO_FILL, header_style=INDIGO_LIGHT, padding=(0, 1), expand=False)
    for column in ("container", "status", "health", "uptime", "restarts", "cpu", "ram"):
        table.add_column(column, no_wrap=True, overflow="ellipsis")
    for container in beaker["containers"]:
        table.add_row(
            *[str(value).lower() for value in (container["name"], container["status"], container["health"], container["uptime"], container["restart_count"])],
            container_cpu_bar(container),
            container_ram_bar(container, host_total),
        )
    console.print(table)
