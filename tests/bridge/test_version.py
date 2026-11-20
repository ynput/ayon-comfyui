"""Tests that the ComfyUI plugin has the version of the addon it ships with.

On shared ComfyUI servers the plugin is installed without the addon, so it
has its own `version.py`. `create_package.py` writes it together with the
addon's `version.py`, from `package.py` (the release automation runs it when
bumping the version); a version bumped by hand must be bumped in all three.

    python tests/bridge/test_version.py
"""

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "client/ayon_comfyui/_comfyui_plugin/ayon_menu"
PLUGIN_VERSION = PLUGIN_DIR / "version.py"
FAILS = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def import_create_package():
    sys.path.insert(0, str(REPO))
    try:
        return importlib.import_module("create_package")
    finally:
        sys.path.remove(str(REPO))


def main():
    create_package = import_create_package()
    version = create_package.ADDON_VERSION
    files = {
        Path(path).resolve(): content
        for path, content in create_package.get_client_version_files(
            create_package.ADDON_CLIENT_DIR).items()
    }
    check(PLUGIN_VERSION.resolve() in files,
          "create_package.py writes the plugin's version.py")
    for path, content in files.items():
        check(path.read_text(encoding="utf-8") == content,
              f"{path.relative_to(REPO)} has version {version} of "
              "package.py (else run create_package.py)")

    print("FAILURES:", FAILS or "none")
    return 1 if FAILS else 0


def test_version():
    """Run all version checks (for pytest)."""
    assert main() == 0, FAILS


if __name__ == "__main__":
    sys.exit(main())
