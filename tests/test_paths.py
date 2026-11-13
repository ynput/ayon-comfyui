"""Tests for resolving AYON rootless paths on the ComfyUI server.

Covers `_comfyui_plugin/ayon_menu/paths.py` (no ComfyUI needed) and that
the AYON host's session proof matches what the plugin checks.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _stubs  # noqa: E402, F401

from ayon_comfyui.api import load_util  # noqa: E402

PATHS_FILE = (
    _stubs.CLIENT_DIR / "ayon_comfyui" / "_comfyui_plugin" / "ayon_menu"
    / "paths.py"
)
spec = importlib.util.spec_from_file_location("ayon_paths", PATHS_FILE)
paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paths)


class RootlessPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.work = base / "work"
        (self.work / "proj" / "sh010").mkdir(parents=True)
        (self.work / "other" / "sh010").mkdir(parents=True)
        (base / "secret").mkdir()
        self.plate = self.work / "proj" / "sh010" / "plate.1001.exr"
        self.plate.write_bytes(b"x")
        (self.work / "other" / "sh010" / "plate.1001.exr").write_bytes(b"x")
        self.env = {
            paths.ROOTS_ENV: json.dumps({"work": str(self.work)}),
        }
        self._old = {key: os.environ.get(key) for key in (
            paths.ROOTS_ENV, paths.PROJECTS_ENV)}
        os.environ.update(self.env)
        os.environ.pop(paths.PROJECTS_ENV, None)

    def tearDown(self):
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_resolves_below_root(self):
        resolved = paths.resolve_rootless(
            "{root[work]}/proj/sh010/plate.1001.exr")
        self.assertEqual(os.path.normcase(resolved),
                         os.path.normcase(os.path.realpath(self.plate)))
        self.assertIsNone(paths.resolve_rootless("{root[nope]}/proj/x.exr"))
        self.assertIsNone(paths.resolve_rootless("/etc/passwd"))
        self.assertIsNone(paths.resolve_rootless(None))

    def test_refuses_escapes(self):
        for path in (
            "{root[work]}/../secret/token.txt",
            "{root[work]}/proj/../../secret/token.txt",
            "{root[work]}/C:/Windows/win.ini",
            "{root[work]}/proj/plate.exr:stream",
        ):
            self.assertIsNone(paths.resolve_rootless(path), path)
            self.assertIsNone(
                paths.resolve_rootless(path, strict=False), path)

    def test_filesystem_roots_are_ignored(self):
        roots = paths._read_roots(json.dumps({
            "work": str(self.work), "all": os.path.abspath(os.sep),
        }))
        self.assertEqual(set(roots), {"work"})

    def test_project_scoping(self):
        os.environ[paths.PROJECTS_ENV] = json.dumps(["proj"])
        self.assertIsNotNone(paths.resolve_rootless(
            "{root[work]}/proj/sh010/plate.1001.exr"))
        self.assertIsNone(paths.resolve_rootless(
            "{root[work]}/other/sh010/plate.1001.exr"))
        os.environ[paths.PROJECTS_ENV] = "other, proj"
        self.assertIsNotNone(paths.resolve_rootless(
            "{root[work]}/other/sh010/plate.1001.exr"))

    def test_lexical_resolution_matches_strict(self):
        path = "{root[work]}/proj/sh010/plate.1001.exr"
        self.assertEqual(
            os.path.normcase(paths.resolve_rootless(path, strict=False)),
            os.path.normcase(paths.resolve_rootless(path)),
        )

    def test_host_proof_matches_plugin(self):
        secret = "s" * 43
        self.assertEqual(load_util.session_proof(secret),
                         paths.session_proof(secret))
        self.assertNotEqual(paths.session_proof(secret), secret)


if __name__ == "__main__":
    unittest.main()
