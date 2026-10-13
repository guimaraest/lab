import base64
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path("/source")
STATE_DIR = Path("/var/cache/status_endpoint")
RATE_LIMIT_SECONDS = 60
COMMAND_TIMEOUT_SECONDS = 55


class StatusProvider:
    def __init__(self, project_root=PROJECT_ROOT, state_dir=STATE_DIR):
        self.project_root = Path(project_root)
        self.state_dir = Path(state_dir)
        self.lock_path = self.state_dir / "status.lock"
        self.cache_path = self.state_dir / "status.json"

    def get_status(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            state = self._read_state()
            now = time.time()
            last_attempt = state.get("last_attempt")
            if isinstance(last_attempt, (int, float)) and now - last_attempt < RATE_LIMIT_SECONDS:
                return self._cached_response(state, RATE_LIMIT_SECONDS - (now - last_attempt), cached=True)

            state = {"last_attempt": now, "return_code": None, "stdout": "", "stderr": ""}
            self._write_state(state)
            state = self._execute_status(state)
            self._write_state(state)
            return self._cached_response(state, RATE_LIMIT_SECONDS - (time.time() - now), cached=False)

    def _read_state(self):
        try:
            return json.loads(self.cache_path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, state):
        encoded = json.dumps(state)
        descriptor, temporary_path = tempfile.mkstemp(dir=self.state_dir, prefix="status-")
        try:
            with os.fdopen(descriptor, "w") as state_file:
                state_file.write(encoded)
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temporary_path, self.cache_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _execute_status(self, state):
        try:
            with tempfile.TemporaryDirectory(prefix="lab-status-") as temporary_directory:
                working_root = Path(temporary_directory) / "lab"
                shutil.copytree(
                    self.project_root,
                    working_root,
                    ignore=shutil.ignore_patterns(
                        ".git",
                        ".venv",
                        "venv",
                        "__pycache__",
                        "*.pyc",
                        "lab.lock",
                        "lab_logs.log",
                        "lab_warnings.log",
                    ),
                    symlinks=True,
                )
                result = subprocess.run(
                    [sys.executable, str(working_root / "cli.py"), "status", "--json"],
                    cwd=working_root,
                    capture_output=True,
                    timeout=COMMAND_TIMEOUT_SECONDS,
                    check=False,
                )
            state["return_code"] = result.returncode
            state["stdout"] = base64.b64encode(result.stdout).decode("ascii")
            state["stderr"] = result.stderr.decode("utf-8", errors="replace")[-4096:]
            if result.returncode != 0:
                print(f"lab status --json failed: {state['stderr'] or 'unknown error'}", file=sys.stderr)
        except subprocess.TimeoutExpired as error:
            state["return_code"] = -1
            state["stdout"] = base64.b64encode(error.stdout or b"").decode("ascii")
            state["stderr"] = f"lab status --json timed out after {COMMAND_TIMEOUT_SECONDS} seconds"
            print(state["stderr"], file=sys.stderr)
        except OSError as error:
            state["return_code"] = -1
            state["stderr"] = f"could not run lab status --json: {error}"
            print(state["stderr"], file=sys.stderr)
        return state

    @staticmethod
    def _cached_response(state, remaining, cached):
        try:
            return_code = state.get("return_code")
            raw_output = base64.b64decode(state.get("stdout", ""), validate=True)
        except (ValueError, TypeError):
            return 503, b'{"error":"status result is unavailable"}', cached, max(1, int(remaining))
        if return_code == 0:
            try:
                json.loads(raw_output)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return 502, b'{"error":"lab status returned invalid JSON"}', cached, max(1, int(remaining))
            return 200, raw_output, cached, max(0, int(remaining))
        return 502, b'{"error":"lab status could not be collected"}', cached, max(1, int(remaining))


class StatusHandler(BaseHTTPRequestHandler):
    provider = StatusProvider()

    def do_GET(self):
        if self.path != "/status":
            self.send_error(404)
            return
        try:
            status, body, cached, retry_after = self.provider.get_status()
        except OSError as error:
            self.send_error(500, f"status service unavailable: {error}")
            return

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Status-Cached", str(cached).lower())
        if retry_after:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.send_error(405, "only GET /status is supported")

    def log_message(self, format_string, *args):
        print(f"{self.client_address[0]} - {format_string % args}", file=sys.stderr)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", 8080), StatusHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()