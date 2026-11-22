from argparse import Namespace
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import beaker, lifecycle


class BeakerUpTest(unittest.TestCase):
    @patch("cli.beaker.beaker_up")
    @patch("cli.beaker.load_config", return_value={"cea": {"aliases": []}})
    def test_build_flag_is_forwarded(self, load_config, beaker_up):
        beaker.cmd_beaker(Namespace(name="cea", action="up", build=True))

        beaker_up.assert_called_once_with("cea", build=True)


class BeakerConsoleTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.lab_root = Path(self.temp_dir.name)
        self.beaker_path = self.lab_root / "minecraft"
        self.beaker_path.mkdir()
        (self.beaker_path / "docker-compose.yml").touch()

    @patch("cli.lifecycle.run")
    @patch("cli.lifecycle.load_config", return_value={"minecraft": {"main_service": "minecraft"}})
    def test_attaches_to_configured_main_service(self, load_config, run):
        run.return_value = subprocess.CompletedProcess([], 0)

        with patch.object(lifecycle, "LAB_ROOT", self.lab_root):
            lifecycle.beaker_console("minecraft")

        run.assert_called_once_with(
            [
                "docker",
                "compose",
                "--env-file",
                str(lifecycle.COMPOSE_ENV_FILE),
                "attach",
                "minecraft",
            ],
            cwd=self.beaker_path,
        )

    @patch("cli.lifecycle.run")
    @patch("cli.lifecycle.load_config", return_value={"minecraft": {"main_service": "minecraft"}})
    def test_attaches_to_explicit_service(self, load_config, run):
        run.return_value = subprocess.CompletedProcess([], 0)

        with patch.object(lifecycle, "LAB_ROOT", self.lab_root):
            lifecycle.beaker_console("minecraft", "playit")

        self.assertEqual(run.call_args.args[0][-2:], ["attach", "playit"])

    @patch("cli.lifecycle.load_config", return_value={"minecraft": {}})
    def test_requires_configured_main_service(self, load_config):
        with self.assertRaisesRegex(SystemExit, "no service specified or main_service configured"):
            lifecycle.beaker_console("minecraft")

    @patch("cli.lifecycle.run")
    @patch("cli.lifecycle.load_config", return_value={"minecraft": {"main_service": "minecraft"}})
    def test_returns_attach_failure_code(self, load_config, run):
        run.return_value = subprocess.CompletedProcess([], 127)

        with patch.object(lifecycle, "LAB_ROOT", self.lab_root):
            with self.assertRaises(SystemExit) as error:
                lifecycle.beaker_console("minecraft")

        self.assertEqual(error.exception.code, 127)


class BeakerLogsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.lab_root = Path(self.temp_dir.name)
        self.beaker_path = self.lab_root / "minecraft"
        self.beaker_path.mkdir()
        (self.beaker_path / "docker-compose.yml").touch()

    @patch("cli.lifecycle.run")
    def test_follows_beaker_logs(self, run):
        with patch.object(lifecycle, "LAB_ROOT", self.lab_root):
            lifecycle.beaker_logs("minecraft")

        run.assert_called_once_with(
            [
                "docker",
                "compose",
                "--env-file",
                str(lifecycle.COMPOSE_ENV_FILE),
                "logs",
                "--follow",
            ],
            cwd=self.beaker_path,
        )
