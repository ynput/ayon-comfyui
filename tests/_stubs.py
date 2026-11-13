"""Import addon modules without importing AYON.

`ayon_comfyui/__init__.py` and `ayon_comfyui/api/__init__.py` import
`ayon_core`, which isn't available outside AYON. The modules under test
don't need it, so register empty package modules that only point at the
source folders; their submodules then import normally.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"


def stub_packages() -> None:
    """Register `ayon_comfyui` and `ayon_comfyui.api` without their init."""
    for name, folder in (
        ("ayon_comfyui", CLIENT_DIR / "ayon_comfyui"),
        ("ayon_comfyui.api", CLIENT_DIR / "ayon_comfyui" / "api"),
    ):
        if name in sys.modules:
            continue
        module = types.ModuleType(name)
        module.__path__ = [str(folder)]
        sys.modules[name] = module


stub_packages()
