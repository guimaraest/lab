import base64
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from flask import Flask, Response, current_app


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
                return self._response(state, RATE_LIMIT_SECONDS - (now - last_attempt), cached=True)

            state = {"last_attempt": now, "return_code": None, "stdout": "", "stderr": ""}
            self._write_state(state)
            state = self._execute_status(state)
            self._write_state(state)
            return self._response(state, RATE_LIMIT_SECONDS - (time.time() - now), cached=False)

    def _read_state(self):
        try:
            return json.loads(self.cache_path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, state):
        descriptor, temporary_path = tempfile.mkstemp(dir=self.state_dir, prefix="status-")
        try:
            with os.fdopen(descriptor, "w") as state_file:
                json.dump(state, state_file)
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temporary_path, self.cache_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _execute_status(self, state):
        try:
            result = subprocess.run(
                [sys.executable, "cli.py", "status", "--json"],
                cwd=self.project_root,
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
    def _response(state, remaining, cached):
        try:
            raw_output = base64.b64decode(state.get("stdout", ""), validate=True)
        except (ValueError, TypeError):
            return 503, b'{"error":"status result is unavailable"}', cached, remaining
        if state.get("return_code") != 0:
            return 502, b'{"error":"lab status could not be collected"}', cached, remaining
        try:
            json.loads(raw_output)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 502, b'{"error":"lab status returned invalid JSON"}', cached, remaining
        return 200, raw_output, cached, remaining


def create_app(provider=None):
    app = Flask(__name__)
    app.config["STATUS_PROVIDER"] = provider or StatusProvider()

    @app.get("/status")
    def status():
        try:
            code, body, cached, remaining = current_app.config["STATUS_PROVIDER"].get_status()
        except OSError as error:
            return {"error": f"status service unavailable: {error}"}, 500
        response = Response(body, status=code, content_type="application/json; charset=utf-8")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Status-Cached"] = str(cached).lower()
        if cached:
            response.headers["Retry-After"] = str(max(1, int(remaining)))
        return response

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
