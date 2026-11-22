from cli.constants import *
from cli.helpers import *


def cmd_list(args):
    for name, config in load_config().items():
        aliases = ", ".join(config.get("aliases", [])) or "none"
        dependencies = ", ".join(config.get("depends_on", [])) or "none"
        enabled = str(beaker_enabled(config)).lower()
        autostart = str(config.get("autostart", True)).lower()
        tests = ", ".join(config["tests"]) or "none"
        print(
            f"{name}: enabled={enabled} autostart={autostart} aliases={aliases} "
            f"depends_on={dependencies} tests={tests}"
        )
