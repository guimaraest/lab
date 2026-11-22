from cli.helpers import beaker_aliases, load_config
from cli.beaker_tests import servarr


TESTS_BY_BEAKER = {
    "servarr": servarr.TESTS,
}


def run_beaker_tests(names):
    beakers = load_config()
    for name in names:
        if name not in beakers:
            raise SystemExit(f"unknown beaker: {name}")
        configured_tests = beakers[name]["tests"]
        if not configured_tests:
            raise SystemExit(f"beaker '{name}' has no tests configured")

        beaker_tests = TESTS_BY_BEAKER.get(name, {})
        for test_name in configured_tests:
            test = beaker_tests.get(test_name)
            if test is None:
                raise SystemExit(
                    f"beaker '{name}' configures unknown test '{test_name}'"
                )

    passed = True
    for name in names:
        for test_name in beakers[name]["tests"]:
            print(f"{name}: {test_name}")
            success, details = TESTS_BY_BEAKER[name][test_name]()
            if details:
                print(details)
            print(f"{'PASS' if success else 'FAIL'}: {name} {test_name}")
            passed = passed and success

    if not passed:
        raise SystemExit(1)


def cmd_test(args):
    beakers = load_config()
    aliases = beaker_aliases(beakers)
    if args.beakers:
        selected = []
        for requested in args.beakers:
            name = aliases.get(requested)
            if name is None:
                raise SystemExit(f"unknown beaker or alias: {requested}")
            selected.append(name)
    else:
        selected = [name for name, config in beakers.items() if config["tests"]]
        if not selected:
            print("no beaker tests are configured")
            return

    run_beaker_tests(selected)
