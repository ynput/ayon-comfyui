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
from unittest import mock

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

    def test_filesystem_roots_are_ignored_without_projects(self):
        drive = os.path.abspath(os.sep)
        os.environ[paths.ROOTS_ENV] = json.dumps({
            "work": str(self.work), "all": drive,
        })
        self.assertEqual(set(paths.configured_roots()), {"work"})
        self.assertEqual(paths.ignored_roots(), {
            "all": {"path": drive, "reason": paths.WHOLE_DRIVE}})
        self.assertIsNone(paths.resolve_rootless(
            "{root[all]}/" + self._below_drive(self.plate)))

    def _below_drive(self, path):
        real = Path(os.path.realpath(path))
        return real.relative_to(real.anchor).as_posix()

    def test_filesystem_roots_need_projects(self):
        # A whole drive narrowed to project folders, e.g. `P:\` with the
        # project folders right below it.
        real = Path(os.path.realpath(self.plate))
        rootless = "{root[drive]}/" + self._below_drive(self.plate)
        project = real.relative_to(real.anchor).parts[0]
        os.environ[paths.ROOTS_ENV] = json.dumps({"drive": real.anchor})
        os.environ[paths.PROJECTS_ENV] = json.dumps([project])
        self.assertEqual(set(paths.configured_roots()), {"drive"})
        self.assertEqual(paths.ignored_roots(), {})
        self.assertEqual(os.path.normcase(paths.resolve_rootless(rootless)),
                         os.path.normcase(str(real)))
        # Other folders of the drive stay out of reach.
        for other in ("{root[drive]}/not-a-project/x.exr",
                      f"{{root[drive]}}/{project}/../etc/passwd"):
            self.assertIsNone(paths.resolve_rootless(other), other)
        # Unset again: the drive is ignored at once.
        os.environ.pop(paths.PROJECTS_ENV)
        self.assertIsNone(paths.resolve_rootless(rootless))
        self.assertIn("drive", paths.ignored_roots())

    def test_is_filesystem_root(self):
        self.assertTrue(paths.is_filesystem_root(os.sep))
        self.assertFalse(paths.is_filesystem_root(str(self.work)))

    @unittest.skipUnless(os.name == "nt", "Windows drives and shares")
    def test_windows_drives_and_shares(self):
        for root in ("P:\\", "P:/", "\\\\nas\\share", "\\\\nas\\share\\"):
            self.assertTrue(paths.is_filesystem_root(root), root)
        for root in ("P:\\projects", "\\\\nas\\share\\projects"):
            self.assertFalse(paths.is_filesystem_root(root), root)

    def test_files_next_to_project_folders_are_refused(self):
        (self.work / "notes.txt").write_bytes(b"x")
        os.environ[paths.PROJECTS_ENV] = json.dumps(["notes.txt", "proj"])
        self.assertIsNone(paths.resolve_rootless("{root[work]}/notes.txt"))
        self.assertIsNotNone(paths.resolve_rootless(
            "{root[work]}/proj/sh010/plate.1001.exr"))

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


class ReferenceFallbackTests(unittest.TestCase):
    """Why AYON uploads files it was asked to reference."""

    FILES = ["{root[work]}/proj/a.1001.exr", "{root[work]}/proj/a.1002.exr"]

    def problem(self, **answer):
        return load_util.check_answer_problem(self.FILES, answer)

    def test_readable(self):
        self.assertIsNone(self.problem(roots=["work"], exists=[True, True]))

    def test_invalid_answer(self):
        self.assertIn("invalid answer", self.problem(exists=[True]))
        self.assertIn("invalid answer",
                      load_util.check_answer_problem(self.FILES, None))

    def test_whole_drive_root(self):
        problem = self.problem(
            roots=[], exists=[False, False],
            ignored_roots={"work": {"path": "P:\\",
                                    "reason": paths.WHOLE_DRIVE}},
        )
        self.assertIn("ignores its AYON root 'work' (P:\\)", problem)
        self.assertIn(paths.PROJECTS_ENV, problem)
        self.assertEqual(load_util.WHOLE_DRIVE, paths.WHOLE_DRIVE)

    def test_root_not_configured(self):
        # e.g. a plugin from before `ignored_roots`.
        problem = self.problem(roots=["other"], exists=[False, False])
        self.assertIn("no AYON root 'work'", problem)

    def test_missing_files(self):
        problem = self.problem(roots=["work"], exists=[True, False])
        self.assertIn("can't find 1 of the 2", problem)

    def test_fallback_is_reported(self):
        uploaded = [{"name": "a.1001.exr"}]
        reasons = []
        with mock.patch.object(load_util, "upload_input_images",
                               return_value=uploaded), \
                mock.patch.object(load_util, "rootless_paths",
                                  return_value=self.FILES), \
                mock.patch.object(load_util, "server_read_problem",
                                  return_value="Nope."):
            files = load_util.container_files(
                "http://comfy", "proj", ["a"], subfolder="x",
                reference=True, on_fallback=reasons.append,
            )
            self.assertEqual(files, {"path_reference": None,
                                     "image_upload_info": uploaded})
            self.assertEqual(reasons, ["Nope."])

            # Not asked to reference: nothing to report.
            load_util.container_files(
                "http://comfy", "proj", ["a"], subfolder="x",
                on_fallback=reasons.append,
            )
            self.assertEqual(reasons, ["Nope."])

            load_util.server_read_problem.return_value = None
            files = load_util.container_files(
                "http://comfy", "proj", ["a"], subfolder="x",
                reference=True, on_fallback=reasons.append,
            )
            self.assertEqual(files["path_reference"], {"files": self.FILES})
            self.assertEqual(reasons, ["Nope."])

    def test_outdated_plugin_is_reported(self):
        reasons = []
        with mock.patch.object(load_util, "upload_input_images",
                               return_value=[]):
            load_util.container_files(
                "http://comfy", "proj", ["a"], subfolder="x",
                reference=True, plugin_features=frozenset({"publish-v1"}),
                on_fallback=reasons.append,
            )
        self.assertIn("older than this addon", reasons[0])


if __name__ == "__main__":
    unittest.main()
