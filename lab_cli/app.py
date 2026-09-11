import argparse

from constants import *
from lab_cli.beaker import cmd_beaker
from lab_cli.lifecycle import cmd_down, cmd_init, cmd_up
from lab_cli.list_command import cmd_list
from lab_cli.status import cmd_status


def main():
    parser = argparse.ArgumentParser(prog="lab", description="lab beaker orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the shared docker network")
    sub.add_parser("list", help="list configured beakers")

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

    beaker_parser = sub.add_parser("beaker", help="run an action for one beaker")
    beaker_parser.add_argument("name", metavar="NAME", help="beaker name or alias")
    beaker_sub = beaker_parser.add_subparsers(dest="action", required=True)
    beaker_sub.add_parser("status", help="show beaker status")
    beaker_sub.add_parser("up", help="start the beaker")
    beaker_sub.add_parser("down", help="stop the beaker")
    beaker_sub.add_parser("logs", help="show beaker logs")
    flag_parser = beaker_sub.add_parser("flag", help="change a beaker flag")
    flag_parser.add_argument("flag_name", choices=["autostart"])
    flag_parser.add_argument("flag_value", choices=["true", "false"])

    args = parser.parse_args()
    commands = {
        "init": cmd_init,
        "list": cmd_list,
        "up": cmd_up,
        "down": cmd_down,
        "status": cmd_status,
        "beaker": cmd_beaker,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
