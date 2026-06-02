"""Declare addon definition for ComfyUI.

This is not the actual addon itself.
It just sets up some preamble with launch hooks.

There appears to be some expected interface that
is shared between all hosts but, not documented at all.
"""

import os

from ayon_api import get_task_by_id, get_folder_by_id

from ayon_core.addon import AYONAddon, IHostAddon, click_wrap

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

    def cli(self, addon_click_group) -> None:
        main_group = click_wrap.group(
            self._cli_main, name=self.name, help="Applications addon"
        )
        (
            main_group.command(
                self._cli_run_server,
                name="run-server",
                help="Run the ComfyUI server"
            )
            .option("--project-name", required=True, help="Project name")
            .option("--entity-id", required=True, help="Entity id")
        )
        addon_click_group.add_command(
            main_group.to_click_obj()
        )

    def _cli_main(self) -> None:
        """Main CLI command."""
        pass

    def _cli_run_server(
        self,
        project_name: str = None,
        entity_id: str = None,
    ) -> None:
        """Run server command."""
        from .api.launch_logic import main

        # differentiate between task and workfile
        # --- on task i also prolly need to support `open last workfile`
        task = get_task_by_id(
            project_name, entity_id, fields=["name", "folderId"]
        )
        folder = get_folder_by_id(
            project_name, task["folderId"], fields=["path"]
        )
        self.log.debug(f"{task = }, {folder = }")

        # gotta prepare env for profile selector to find all required data
        os.environ["AYON_PROJECT_NAME"] = project_name
        os.environ["AYON_HOST_NAME"] = self.host_name  # needed?
        os.environ["AYON_TASK_NAME"] = task["name"]
        os.environ["AYON_FOLDER_PATH"] = folder["path"]
        main()


def get_launch_script_path() -> str:
    """Returns script for launching logic implementation."""
    return os.path.join(COMFYUI_ADDON_ROOT, "api", "launch_script.py")
