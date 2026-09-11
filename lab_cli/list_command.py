from constants import *


def cmd_list(args):
    for name, config in load_config().items():
        aliases = ", ".join(config.get("aliases", [])) or "none"
        dependencies = ", ".join(config.get("depends_on", [])) or "none"
        autostart = str(config.get("autostart", True)).lower()
        print(f"{name}: autostart={autostart} aliases={aliases} depends_on={dependencies}")
