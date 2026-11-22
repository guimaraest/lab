import argparse
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import data_tree


class DataTreeCommandTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.data_path = Path(self.temp_dir.name)
        self.env_patch = patch(
            "cli.data_tree.parse_env_file",
            return_value={"DATA_PATH": str(self.data_path)},
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    @patch("cli.data_tree.subprocess.run")
    @patch("cli.data_tree.shutil.which", return_value="/usr/bin/tree")
    def test_defaults_to_depth_four(self, which, run):
        run.return_value = subprocess.CompletedProcess([], 0)

        data_tree.cmd_data_tree(argparse.Namespace(level=4))

        which.assert_called_once_with("tree")
        run.assert_called_once_with(
            ["/usr/bin/tree", "-L", "4", str(self.data_path)],
            check=False,
        )

    @patch("cli.data_tree.subprocess.run")
    @patch("cli.data_tree.shutil.which", return_value="/usr/bin/tree")
    def test_uses_requested_depth(self, which, run):
        run.return_value = subprocess.CompletedProcess([], 0)

        data_tree.cmd_data_tree(argparse.Namespace(level=2))

        self.assertEqual(run.call_args.args[0][2], "2")

    def test_rejects_non_positive_depth(self):
        with self.assertRaisesRegex(SystemExit, "at least 1"):
            data_tree.cmd_data_tree(argparse.Namespace(level=0))

    @patch("cli.data_tree.shutil.which", return_value=None)
    def test_reports_missing_tree_command(self, which):
        with self.assertRaisesRegex(SystemExit, "tree.*not found"):
            data_tree.cmd_data_tree(argparse.Namespace(level=4))

    @patch("cli.data_tree.parse_env_file", return_value={})
    def test_reports_missing_data_path(self, parse_env):
        with self.assertRaisesRegex(SystemExit, "DATA_PATH is not configured"):
            data_tree.cmd_data_tree(argparse.Namespace(level=4))

    @patch("cli.data_tree.shutil.which", return_value="/usr/bin/tree")
    def test_reports_nonexistent_data_path(self, which):
        with patch(
            "cli.data_tree.parse_env_file",
            return_value={"DATA_PATH": str(self.data_path / "missing")},
        ):
            with self.assertRaisesRegex(SystemExit, "DATA_PATH is not a directory"):
                data_tree.cmd_data_tree(argparse.Namespace(level=4))

    @patch("cli.data_tree.subprocess.run")
    @patch("cli.data_tree.shutil.which", return_value="/usr/bin/tree")
    def test_propagates_tree_failure(self, which, run):
        run.return_value = subprocess.CompletedProcess([], 2)

        with self.assertRaises(SystemExit) as error:
            data_tree.cmd_data_tree(argparse.Namespace(level=4))

        self.assertEqual(error.exception.code, 2)
