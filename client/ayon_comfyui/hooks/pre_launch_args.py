"""Attempt to get arguments from server pre-launch."""

from __future__ import annotations

import os
import platform
import subprocess
from typing import ClassVar, Optional

from ayon_applications import LaunchTypes, PreLaunchHook
from ayon_comfyui.addon import get_launch_script_path
from ayon_core.lib import (
    get_ayon_launcher_args,
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

    Hook add python executable and script path to AE implementation before
    AE executable and add last workfile path to launch arguments.

    TODO: REVISE THIS, LIFTED FROM AFTEREFFECTS
    """

    app_groups: ClassVar[set] = {"comfyui"}

    order: ClassVar[int] = 20
    launch_types: ClassVar[set] = {LaunchTypes.local}

    def execute(self) -> None:
        """Abstract execute method where logic of hook is."""
        self.log.warning(msg=str(self.launch_context.launch_args))
        self.log.warning(msg=str(self.launch_context.kwargs))
        self.log.warning(msg=str(self.launch_context.env))

        script_path = get_launch_script_path()
        # uses ayon_console to launch a script.
        new_launch_args = get_ayon_launcher_args(
            "--use-dev", "run", script_path
        )

        # uses ayon_console to launch a script.
        new_launch_args = get_ayon_launcher_args(
            "--use-dev", "run", script_path
        )

        # self.launch_context.redirect_output = False  # LET STDOUT SCREAM!!

        self.launch_context.launch_args = new_launch_args

        self.launch_context.kwargs = get_launch_kwargs(
            self.launch_context.kwargs
        )

        return
        # Pop executable
        executable_path = self.launch_context.launch_args.pop(0)

        # Pop rest of launch arguments - There should not be other arguments!
        remainders = []
        while self.launch_context.launch_args:
            remainders.append(self.launch_context.launch_args.pop(0))

        script_path = get_launch_script_path()

        new_launch_args = get_ayon_launcher_args(
            "run", script_path, executable_path
        )
        # Add workfile path if exists
        workfile_path = self.data["last_workfile_path"]
        if (
            self.data.get("start_last_workfile")
            and workfile_path
            and os.path.exists(workfile_path)
        ):
            new_launch_args.append(workfile_path)

        workfile_startup = self.data.get("workfile_startup", False)
        # set the env variable AYON_COMFYUI_WORKFILES_ON_LAUNCH to bool str
        self.launch_context.env["AYON_COMFYUI_WORKFILES_ON_LAUNCH"] = str(
            workfile_startup
        ).lower()

        # Append as whole list as these arguments should not be separated
        self.launch_context.launch_args.append(new_launch_args)

        if remainders:
            self.launch_context.launch_args.extend(remainders)

        self.launch_context.kwargs = get_launch_kwargs(
            self.launch_context.kwargs
        )
