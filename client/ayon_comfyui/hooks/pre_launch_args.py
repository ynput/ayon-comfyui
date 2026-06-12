"""Attempt to get arguments from server pre-launch."""

from __future__ import annotations

import platform
import subprocess
from typing import ClassVar, Optional

from ayon_applications import LaunchTypes, PreLaunchHook
from ayon_comfyui import get_launch_script_path
from ayon_core.lib import (
    get_ayon_launcher_args,
    is_dev_mode_enabled,
    is_using_ayon_console,
)


def get_launch_kwargs(kwargs: Optional[dict] = None) -> dict:
    """Returns Explicit setting of kwargs for Popen.

    A client process to the launched ComfyUI should use these.

    Expected behavior
    - ayon_console opens window with logs
    - ayon has stdout/stderr available for capturing
    """
    if kwargs is None:
        kwargs = {}

    if platform.system().lower() != "windows":
        return kwargs

    if is_using_ayon_console():
        kwargs.update({"creationflags": subprocess.CREATE_NEW_CONSOLE})
    else:
        kwargs.update(
            {
                "creationflags": subprocess.CREATE_NO_WINDOW,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
        )
    return kwargs


class ComfyPrelaunchHook(PreLaunchHook):
    """Launch arguments preparation.

    Set launch arguments so that it launches the ComfyUI profiles launcher.
    """

    app_groups: ClassVar[set] = {"comfyui"}

    order: ClassVar[int] = 20
    launch_types: ClassVar[set] = {LaunchTypes.local}

    def execute(self) -> None:
        script_path = get_launch_script_path()
        # uses ayon_console to launch a script, respecting dev mode.
        dev_args = ["--use-dev"] if is_dev_mode_enabled() else []

        new_launch_args = get_ayon_launcher_args(*dev_args, "run", script_path)

        self.launch_context.launch_args = new_launch_args

        self.launch_context.kwargs = get_launch_kwargs(
            self.launch_context.kwargs
        )
