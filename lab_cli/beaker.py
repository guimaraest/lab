from lab_cli.constants import *
from lab_cli.helpers import *
from lab_cli.lifecycle import beaker_down, beaker_logs, beaker_up, restart_beaker
from lab_cli.status import get_beaker_status, print_beaker_status


def set_autostart(name, value):
    config = load_config()
    if name not in config:
        raise SystemExit(f"unknown beaker: {name}")
    config[name]["autostart"] = value
    with CONFIG_PATH.open("w") as config_file:
        yaml.safe_dump({"beakers": config}, config_file, sort_keys=False)
    print(f"{name}: autostart={str(value).lower()}")


def cmd_beaker(args):
    config = load_config()
    name = beaker_aliases(config).get(args.name)
    if name is None:
        raise SystemExit(f"unknown beaker or alias: {args.name}")

    if args.action == "status":
        print_beaker_status(get_beaker_status(name))
    elif args.action == "up":
        beaker_up(name)
    elif args.action == "down":
        beaker_down(name)
    elif args.action == "restart":
        restart_beaker(name)
    elif args.action == "logs":
        beaker_logs(name)
    elif args.action == "flag":
        set_autostart(name, args.flag_value)
