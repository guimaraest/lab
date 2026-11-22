import shutil
import subprocess
from pathlib import Path

from cli.helpers import parse_env_file


def cmd_data_tree(args):
    if args.level < 1:
        raise SystemExit("tree depth must be at least 1")

    data_path = parse_env_file().get("DATA_PATH")
    if not data_path:
        raise SystemExit("DATA_PATH is not configured in the repository .env file")

    path = Path(data_path).expanduser()
    if not path.is_dir():
        raise SystemExit(f"DATA_PATH is not a directory: {path}")

    tree = shutil.which("tree")
    if tree is None:
        raise SystemExit("the 'tree' command is required but was not found in PATH")

    try:
        result = subprocess.run([tree, "-L", str(args.level), str(path)], check=False)
    except OSError as error:
        raise SystemExit(f"could not run tree: {error}") from error

    if result.returncode != 0:
        raise SystemExit(result.returncode)
