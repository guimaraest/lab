import argparse

from constants import *
from lab_cli.lifecycle import cmd_down, cmd_init, cmd_up
from lab_cli.status import cmd_status


def main():
    parser = argparse.ArgumentParser(prog="lab", description="lab beaker orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the shared docker network")

    up_parser = sub.add_parser("up", help="start beakers in dependency order")
    up_parser.add_argument(
        "beakers",
        nargs="*",
        metavar="BEAKER_OR_ALIAS",
        help="beaker names or aliases (defaults to all autostart beakers)",
    )
    up_parser.add_argument("--build", action="store_true", help="build images before starting")
    up_parser.add_argument("--logs", action="store_true", help="show logs after starting")

    down_parser = sub.add_parser("down", help="stop beakers in reverse dependency order")
    down_parser.add_argument(
        "beakers",
        nargs="*",
        metavar="BEAKER_OR_ALIAS",
        help="beaker names or aliases (defaults to all beakers)",
    )

    status_parser = sub.add_parser("status", help="show detailed host and beaker status")
    status_parser.add_argument("--json", action="store_true", help="output structured JSON")

    args = parser.parse_args()
    commands = {
        "init": cmd_init,
        "up": cmd_up,
        "down": cmd_down,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
