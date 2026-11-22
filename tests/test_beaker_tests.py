import argparse
import subprocess
import unittest
from unittest.mock import patch

from cli import test_command
from cli.beaker_tests import servarr


class GluetunConnectivityTest(unittest.TestCase):
    @patch("cli.beaker_tests.servarr.subprocess.run")
    def test_runs_wget_in_gluetun_network_namespace(self, run):
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout='{"ip":"203.0.113.1"}\n',
            stderr="",
        )

        success, details = servarr.test_gluetun_connectivity()

        self.assertTrue(success)
        self.assertEqual(
            details.splitlines(),
            [
                'gluetun: {"ip":"203.0.113.1"}',
                'nzbget: {"ip":"203.0.113.1"}',
                'qbittorrent: {"ip":"203.0.113.1"}',
                'prowlarr: {"ip":"203.0.113.1"}',
            ],
        )
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                servarr.GLUETUN_CONNECTIVITY_COMMAND,
                *servarr.CONTAINER_CONNECTIVITY_COMMANDS.values(),
            ],
        )
        self.assertTrue(
            all(
                call.kwargs
                == {
                    "capture_output": True,
                    "text": True,
                    "timeout": 120,
                    "check": False,
                }
                for call in run.call_args_list
            )
        )

    @patch("cli.beaker_tests.servarr.subprocess.run")
    def test_reports_docker_failure(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 1, stdout="", stderr="container gluetun is not running"),
            *[
                subprocess.CompletedProcess([], 0, stdout='{"ip":"203.0.113.1"}', stderr="")
                for _ in servarr.CONTAINER_CONNECTIVITY_COMMANDS
            ],
        ]

        success, details = servarr.test_gluetun_connectivity()

        self.assertFalse(success)
        self.assertIn("gluetun: connectivity check failed", details)
        self.assertIn("container gluetun is not running", details)
        self.assertEqual(run.call_count, 1 + len(servarr.CONTAINER_CONNECTIVITY_COMMANDS))

    @patch("cli.beaker_tests.servarr.subprocess.run")
    def test_reports_timeout(self, run):
        run.side_effect = [
            subprocess.TimeoutExpired(servarr.GLUETUN_CONNECTIVITY_COMMAND, 120),
            *[
                subprocess.CompletedProcess([], 0, stdout='{"ip":"203.0.113.1"}', stderr="")
                for _ in servarr.CONTAINER_CONNECTIVITY_COMMANDS
            ],
        ]

        success, details = servarr.test_gluetun_connectivity()

        self.assertFalse(success)
        self.assertIn("gluetun: connectivity check could not complete", details)
        self.assertIn("timed out", details)


class BeakerTestCommandTest(unittest.TestCase):
    @patch("cli.test_command.load_config")
    def test_default_runs_only_beakers_with_configured_tests(self, load_config):
        load_config.return_value = {
            "nextcloud": {"aliases": [], "tests": []},
            "servarr": {"aliases": [], "tests": ["gluetun-connectivity"]},
        }

        with patch.object(test_command, "run_beaker_tests") as run_tests:
            test_command.cmd_test(argparse.Namespace(beakers=[]))

        run_tests.assert_called_once_with(["servarr"])

    @patch("cli.test_command.load_config")
    def test_unknown_alias_fails(self, load_config):
        load_config.return_value = {
            "servarr": {"aliases": [], "tests": ["gluetun-connectivity"]},
        }

        with self.assertRaisesRegex(SystemExit, "unknown beaker or alias"):
            test_command.cmd_test(argparse.Namespace(beakers=["unknown"]))

    @patch("cli.test_command.load_config")
    def test_beaker_without_tests_fails(self, load_config):
        load_config.return_value = {
            "nextcloud": {"aliases": [], "tests": []},
        }

        with self.assertRaisesRegex(SystemExit, "has no tests configured"):
            test_command.run_beaker_tests(["nextcloud"])
