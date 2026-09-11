from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).with_name("cli_config.yaml")
NETWORK = "lab-net"
COMPOSE_ENV_FILE = LAB_ROOT / ".env"
HEALTH_TIMEOUT = 100
HEALTH_POLL_INTERVAL = 2
