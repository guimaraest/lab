import argparse
import fcntl
from contextlib import contextmanager

from lab_cli.constants import *
from lab_cli.beaker import cmd_beaker
from lab_cli.lifecycle import cmd_down, cmd_init, cmd_restart, cmd_up
from lab_cli.helpers import load_config
from lab_cli.list_command import cmd_list
from lab_cli.notifications import print_recent_notifications
from lab_cli.status import cmd_status


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
    parser = argparse.ArgumentParser(prog="lab", description="lab beaker orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the shared docker network")
    sub.add_parser("list", help="list configured beakers")
    logs_parser = sub.add_parser("logs", help="show recent lab notifications")
    logs_parser.add_argument("--limit", type=int, default=50, help="number of recent notifications to show (default: 50)")

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
        parser.add_argument("--build", action="store_true", help="build images before starting")
        parser.add_argument("--logs", action="store_true", help="show logs after starting")
        parser.add_argument("-d", "--detach", action="store_true", help="start and return without waiting for health")
        parser.add_argument(
            "--tolerance",
            choices=["low", "high"],
            default="low",
            help="healthcheck tolerance (default: low)",
        )

    up_parser = sub.add_parser("up", help="start beakers in dependency order")
    add_run_arguments(up_parser)
    run_parser = sub.add_parser("run", help="start beakers in dependency order")
    add_run_arguments(run_parser)
    restart_parser = sub.add_parser(
        "restart",
        help="restart all autostart beakers in dependency order",
        description=(
            "restart all autostart beakers; low tolerance is the default, while "
            "high tolerance is intended for the scheduled ofelia restart"
        ),
    )
    restart_parser.add_argument(
        "--tolerance",
        choices=["low", "high"],
        default="low",
        help="healthcheck tolerance for this restart",
    )

    down_parser = sub.add_parser("down", help="stop beakers in reverse dependency order")
    down_parser.add_argument(
        "beakers",
        nargs="*",
        metavar="BEAKER_OR_ALIAS",
        help="beaker names or aliases (defaults to all beakers)",
    )

    status_parser = sub.add_parser("status", help="show detailed host and beaker status")
    status_parser.add_argument("--json", action="store_true", help="output structured JSON")

    beaker_parser = sub.add_parser("beaker", help="run an action for one beaker")
    beaker_parser.add_argument("name", metavar="NAME", help="beaker name or alias")
    beaker_sub = beaker_parser.add_subparsers(dest="action", required=True)
    beaker_sub.add_parser("status", help="show beaker status")
    beaker_sub.add_parser("up", help="start the beaker")
    beaker_sub.add_parser("down", help="stop the beaker")
    beaker_sub.add_parser(
        "restart",
        help="restart the beaker using low healthcheck tolerance",
        description="restart this beaker using the default low healthcheck tolerance",
    )
    beaker_sub.add_parser("logs", help="show beaker logs")
    flag_parser = beaker_sub.add_parser("flag", help="change a beaker flag")
    flag_parser.add_argument("flag_name", choices=["autostart"])
    flag_parser.add_argument("flag_value", choices=["true", "false"])

    args = parser.parse_args()
    commands = {
        "init": cmd_init,
        "list": cmd_list,
        "logs": lambda args: print_recent_notifications(args.limit),
        "up": cmd_up,
        "run": cmd_up,
        "restart": cmd_restart,
        "down": cmd_down,
        "status": cmd_status,
        "beaker": cmd_beaker,
    }
    mutating = args.command in {"init", "up", "run", "restart", "down"} or (
        args.command == "beaker" and args.action in {"up", "down", "restart"}
    )
    command = commands[args.command]
    if mutating:
        with mutating_command_lock():
            load_config()
            command(args)
    else:
        load_config()
        command(args)


if __name__ == "__main__":
    main()
