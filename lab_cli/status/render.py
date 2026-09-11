import json

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lab_cli.constants import *


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
    host_text = "\n".join([
        f"[bold]Status:[/bold] [{state_style}]{report['status']}[/{state_style}]",
        f"Uptime: {host['uptime']}    Last restart: {host['last_restart'] or 'unavailable'}",
        f"CPU: {cpu['usage_percent']}% used    Load: {', '.join(f'{item:.2f}' for item in cpu['load'])}",
        f"RAM: {memory['used_human']} / {memory['total_human']} ({memory['percent']}%)",
        f"Disk /: {disk['free_human']} free / {disk['total_human']} ({disk['percent']}% used)",
        f"Docker disk: {docker_summary}",
        f"CPU temperature: {host['temperature_celsius']} C    Last OS upgrade: {host['last_os_upgrade'] or 'unavailable'}",
        "Fail2ban: " + "\n          ".join(fail2ban_lines),
    ])
    console.print(Panel(host_text, title="[bold #6366F1]Lab Host[/bold #6366F1]", border_style="#6366F1", expand=False))

    table = Table(title="[bold #6366F1]Beaker Containers[/bold #6366F1]", border_style="#818CF8", header_style="#A78BFA")
    for column in ("Beaker", "Container", "Status", "Health", "Uptime", "Restarts", "CPU", "RAM"):
        table.add_column(column)
    for beaker in report["beakers"]:
        for container in beaker["containers"]:
            style = "green" if container["status"] == "running" and container["health"] in ("healthy", "none") else "red"
            table.add_row(beaker["name"], *container_row(container), style=style)
    console.print(table)
    for beaker in report["beakers"]:
        domains = ", ".join(beaker["domains"]) or "none configured"
        volumes = ", ".join(f"{volume['name']}={volume['size_human']}" for volume in beaker["volumes"]) or "none"
        console.print(f"[bold #6366F1]{beaker['name']}[/bold #6366F1]  folder={beaker['folder_size_human']}  uptime={beaker['uptime']}  domains={domains}  volumes={volumes}")


def print_beaker_status(beaker):
    console = Console()
    table = Table(title=f"[bold #6366F1]{beaker['name']}[/bold #6366F1]", border_style="#818CF8", header_style="#A78BFA")
    for column in ("Container", "Status", "Health", "Uptime", "Restarts", "CPU", "RAM"):
        table.add_column(column)
    for container in beaker["containers"]:
        table.add_row(*container_row(container))
    console.print(table)
