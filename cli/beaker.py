from cli.constants import *
from cli.helpers import *
from cli.lifecycle import beaker_console, beaker_down, beaker_logs, beaker_up, restart_beaker
from cli.status import get_beaker_status, print_beaker_status
from cli.test_command import run_beaker_tests


def set_autostart(name, value):
    settings = load_settings()
    config = settings["beakers"]
    if name not in config:
        raise SystemExit(f"unknown beaker: {name}")
    config[name]["autostart"] = value
    with CONFIG_PATH.open("w") as config_file:
        yaml.safe_dump(settings, config_file, sort_keys=False)
    print(f"{name}: autostart={str(value).lower()}")


def cmd_beaker(args):
    config = load_config()
    name = beaker_aliases(config).get(args.name)
    if name is None:
        raise SystemExit(f"unknown beaker or alias: {args.name}")

    if args.action == "status":
        print_beaker_status(get_beaker_status(name))
    elif args.action == "up":
        beaker_up(
            name,
            build=getattr(args, "build", False),
            tolerance=getattr(args, "tolerance", "low"),
            detach=getattr(args, "detach", False),
            logs=getattr(args, "logs", False),
        )
    elif args.action == "down":
        beaker_down(name)
    elif args.action == "restart":
        restart_beaker(
            name,
            build=getattr(args, "build", False),
            tolerance=getattr(args, "tolerance", "low"),
            detach=getattr(args, "detach", False),
            logs=getattr(args, "logs", False),
        )
    elif args.action == "listen":
        beaker_logs(name)
    elif args.action == "attach":
        beaker_console(name, args.service)
    elif args.action == "test":
        run_beaker_tests([name])
    elif args.action == "flag":
        set_autostart(name, args.flag_value)
