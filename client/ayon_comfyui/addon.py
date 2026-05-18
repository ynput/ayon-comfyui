"""Declare addon definition for ComfyUI.

This is not the actual addon itself.
It just sets up some preamble with launch hooks.

There appears to be some expected interface that
is shared between all hosts but, not documented at all.
"""

import os

from ayon_core.addon import AYONAddon, IHostAddon

from .version import __version__

COMFYUI_ADDON_ROOT = os.path.dirname(os.path.abspath(__file__))


class ComfyUIAddon(AYONAddon, IHostAddon):
    """Comfy UI Addon Definition."""

    name = "comfyui"
    host_name = "comfyui"
    label = "ComfyUI"
    version = __version__

    def add_implementation_envs(self, env, _app):
        defaults = {
            "LOGLEVEL": "DEBUG",
            "AYON_LOG_NO_COLORS": "1",
        }
        for key, value in defaults.items():
            if not env.get(key):
                env[key] = value

    def get_workfile_extensions(self) -> list[str]:  # noqa:PLR6301
        """Returns associated paths."""
        return [".json"]

    def get_launch_hook_paths(self, app: IHostAddon) -> list[str]:
        """Returns paths to launch hooks."""
        if app.host_name != self.host_name:
            return []
        return [os.path.join(COMFYUI_ADDON_ROOT, "hooks")]


def get_launch_script_path() -> str:
    """Returns script for launching logic implementation."""
    return os.path.join(COMFYUI_ADDON_ROOT, "api", "launch_script.py")
