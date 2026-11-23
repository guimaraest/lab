import argparse
import fcntl
from contextlib import contextmanager

from cli.constants import *
from cli.beaker import cmd_beaker
from cli.data_tree import cmd_data_tree
from cli.lifecycle import cmd_down, cmd_init, cmd_restart, cmd_up
from cli.helpers import load_config
from cli.list_command import cmd_list
from cli.logs import log, print_recent_logs
from cli.notifications import notify_server_up
from cli.power import cmd_power_report, cmd_record
from cli.status import cmd_status
from cli.test_command import cmd_test


@contextmanager
def mutating_command_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another lab command is already running - try again once it finishes")
        yield


def main():
    parser = argparse.ArgumentParser(
        prog="lab",
        description="Manage the lab's Docker Compose beakers, host status, and power records.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create or verify the shared Docker networks", description="Create the internal lab-net and external ext-net Docker networks, or verify existing networks.")
    sub.add_parser("list", help="list configured beakers", description="List configured beakers with enabled, autostart, alias, dependency, and test settings.")
    logs_parser = sub.add_parser("logs", help="show recent lab notifications", description="Show the newest warning and status notifications from the local notification log.")
    logs_parser.add_argument("--limit", type=int, default=50, help="number of recent notifications to show (default: 50)")
    data_tree_parser = sub.add_parser("data-tree", help="show the data directory tree", description="Print DATA_PATH from .env using the system 'tree' command.")
    data_tree_parser.add_argument(
        "-L",
        "--level",
        type=int,
        default=4,
        metavar="LEVEL",
        help="maximum directory depth (default: 4)",
    )

    def add_run_arguments(parser):
        parser.description = (
            "start beakers in dependency order; low tolerance is the default, "
            "while high tolerance uses more patient health checks"
        )
        parser.add_argument(
            "beakers",
            nargs="*",
            metavar="BEAKER_OR_ALIAS",
            help="beaker names or aliases (defaults to all autostart beakers)",
        )
        add_lifecycle_arguments(parser)

    def add_lifecycle_arguments(parser):
        parser.add_argument("--build", action="store_true", help="build images before starting")
        parser.add_argument("--logs", action="store_true", help="show Compose logs after starting")
        parser.add_argument("-d", "--detach", action="store_true", help="return without waiting for container health")
        parser.add_argument(
            "--tolerance",
            choices=["low", "high"],
            default="low",
            help="healthcheck tolerance; high allows more retries (default: low)",
        )

    up_parser = sub.add_parser("up", help="start selected or autostart beakers", description="Start enabled beakers in dependency order. With no names, start enabled autostart beakers; naming beakers selects them explicitly.")
    add_run_arguments(up_parser)
    run_parser = sub.add_parser("run", help="alias for up", description="Alias for 'lab up'. Start enabled beakers in dependency order.")
    add_run_arguments(run_parser)
    restart_parser = sub.add_parser(
        "restart",
        help="restart beakers configured for restart",
        description=(
            "Restart enabled beakers with allow_restart set, in dependency order. "
            "Each retry stops the selected stack in reverse order, then starts it. "
            "If all retries fail, stop every beaker."
        ),
    )
    add_lifecycle_arguments(restart_parser)

    down_parser = sub.add_parser("down", help="stop selected or all beakers", description="Stop beakers in reverse dependency order. With no names, stop all configured beakers.")
    down_parser.add_argument(
        "beakers",
        nargs="*",
        metavar="BEAKER_OR_ALIAS",
        help="beaker names or aliases (defaults to all beakers)",
    )

    test_parser = sub.add_parser("test", help="run configured beaker tests", description="Run configured tests for named beakers, or for every beaker with tests.")
    test_parser.add_argument(
        "beakers",
        nargs="*",
        metavar="BEAKER_OR_ALIAS",
        help="beaker names or aliases (defaults to beakers with tests)",
    )

    status_parser = sub.add_parser("status", help="show host and beaker status", description="Collect host, Docker, network, and beaker status; report high-severity conditions as notifications.")
    status_parser.add_argument("--json", action="store_true", help="output structured JSON")
    status_parser.add_argument("--save-log", action="store_true", help="send the full report through the log system")
    sub.add_parser("server-up", help="record a server-up warning", description="Record the server-up warning and forward it to the configured warning webhook.")

    record_parser = sub.add_parser("record", help="record a power or system event", description="Append a UTC power meter snapshot or system event to cli/power.log.")
    record_sub = record_parser.add_subparsers(dest="event", required=True)
    record_sub.add_parser("periodic", help="record a meter snapshot", description="Read available power meters and append a UTC snapshot to cli/power.log.")
    record_sub.add_parser("shutdown", help="record a shutdown boundary", description="Append a UTC shutdown event to cli/power.log to close power measurement intervals.")
    record_sub.add_parser("poweron", help="record a power-on boundary", description="Append a UTC power-on event to cli/power.log to begin new power measurement intervals.")

    power_parser = sub.add_parser("power", help="report measured power usage", description="Report measured power use from the local power log.")
    power_sub = power_parser.add_subparsers(dest="power_action", required=True)
    power_report_parser = power_sub.add_parser("report", help="report measured power use for a month", description="Calculate measured energy intervals overlapping a UTC calendar month.")
    power_report_parser.add_argument("--month", metavar="YYYY-MM", help="UTC month (defaults to the current month)")

    beaker_parser = sub.add_parser("beaker", help="manage one beaker", description="Inspect or control one beaker by configured name or alias.")
    beaker_parser.add_argument("name", metavar="NAME", help="beaker name or alias")
    beaker_sub = beaker_parser.add_subparsers(dest="action", required=True)
    beaker_sub.add_parser("status", help="show beaker status", description="Show container status and resource use for this beaker.")
    beaker_up_parser = beaker_sub.add_parser("up", help="start the beaker", description="Start this enabled beaker and, unless detached, wait for its containers to become healthy.")
    add_lifecycle_arguments(beaker_up_parser)
    beaker_sub.add_parser("down", help="stop the beaker", description="Stop and remove this beaker's Compose containers.")
    beaker_restart_parser = beaker_sub.add_parser(
        "restart",
        help="stop and start the beaker",
        description="Stop and start this enabled beaker, waiting for health unless detached.",
    )
    add_lifecycle_arguments(beaker_restart_parser)
    beaker_sub.add_parser("listen", help="follow beaker logs", description="Follow the Compose logs for this beaker.")
    console_parser = beaker_sub.add_parser("attach", help="attach to a service console", description="Attach to a Compose service's console; defaults to the configured main_service.")
    console_parser.add_argument(
        "service",
        nargs="?",
        metavar="SERVICE",
        help="Compose service to attach to (defaults to the configured main service)",
    )
    beaker_sub.add_parser("test", help="run configured beaker tests", description="Run this beaker's configured tests.")
    flag_parser = beaker_sub.add_parser("flag", help="change a beaker setting", description="Update the beaker's autostart setting in config.yaml.")
    flag_parser.add_argument("flag_name", choices=["autostart"])
    flag_parser.add_argument("flag_value", choices=["true", "false"])

    args = parser.parse_args()
    commands = {
        "init": cmd_init,
        "list": cmd_list,
        "logs": lambda args: print_recent_logs(args.limit),
        "data-tree": cmd_data_tree,
        "up": cmd_up,
        "run": cmd_up,
        "restart": cmd_restart,
        "down": cmd_down,
        "test": cmd_test,
        "status": cmd_status,
        "server-up": lambda args: notify_server_up(),
        "record": cmd_record,
        "power": cmd_power_report,
        "beaker": cmd_beaker,
    }
    mutating = args.command in {"init", "up", "run", "restart", "down"} or (
        args.command == "beaker" and args.action in {"up", "down", "restart"}
    )
    command = commands[args.command]
    details = {"command": args.command}
    if args.command == "beaker":
        details.update({"action": args.action, "beaker": args.name})
    if args.command != "record":
        log("info", f"{args.command} command started", **details)
    needs_beaker_config = args.command not in {"record", "power"}
    if mutating:
        with mutating_command_lock():
            if needs_beaker_config:
                load_config()
            command(args)
    else:
        if needs_beaker_config:
            load_config()
        command(args)


if __name__ == "__main__":
    main()
