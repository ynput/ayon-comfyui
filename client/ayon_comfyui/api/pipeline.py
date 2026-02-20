"""Actual host definition.

Will be launched as a subprocess.
"""

from __future__ import annotations

import logging
import os
from traceback import print_tb
from typing import Any

import pyblish.api
from ayon_core.host import (
    ApplicationInformation,
    HostBase,
    ILoadHost,
    IPublishHost,
    IWorkfileHost,
)
from ayon_core.pipeline import (
    deregister_creator_plugin_path,
    deregister_inventory_action_path,
    deregister_loader_plugin_path,
    deregister_workfile_build_plugin_path,
    get_current_project_name,
    register_creator_plugin_path,
    register_inventory_action_path,
    register_loader_plugin_path,
    register_workfile_build_plugin_path,
)
from ayon_core.settings import get_project_settings

from ayon_comfyui import COMFYUI_ADDON_ROOT
from ayon_comfyui.api.qt_rpc import QRPCManager

logging.basicConfig(force=True, stream=sys.stdout, level=logging.DEBUG)
log = logging.getLogger("ayon_comfyui")

PLUGINS_DIR = os.path.join(COMFYUI_ADDON_ROOT, "plugins")
PUBLISH_PATH = os.path.join(PLUGINS_DIR, "publish")
LOAD_PATH = os.path.join(PLUGINS_DIR, "load")
CREATE_PATH = os.path.join(PLUGINS_DIR, "create")
# [[maybe_unused]]
INVENTORY_PATH = os.path.join(PLUGINS_DIR, "inventory")
WORKFILE_BUILD_PATH = os.path.join(PLUGINS_DIR, "workfile_build")


class ComfyUIHost(HostBase, IWorkfileHost, ILoadHost, IPublishHost):
    """Main implementation of actual host operations."""

    name = "comfyui"

    _last_path: str = ""

    def __init__(self):
        super().__init__()
        # Establish connection?
        # If not done here then deperecate this.

    def get_app_information(self) -> ApplicationInformation:
        """Return application information."""
        return ApplicationInformation(
            app_name="ComfyUI",
            app_version="N/A",  # TODO(@sas): request this in future
        )

    def get_workfile_extensions(self) -> list[str]:
        """Return list of workfile extensions."""
        return [".json"]

    def install(self) -> None:
        """Install host context."""
        # Context
        project_name = get_current_project_name()
        project_settings = get_project_settings(project_name)

        register_loader_plugin_path(LOAD_PATH)
        register_creator_plugin_path(CREATE_PATH)
        # Not sure we'll use these.
        register_inventory_action_path(INVENTORY_PATH)
        register_workfile_build_plugin_path(WORKFILE_BUILD_PATH)

        # Pyblish
        pyblish.api.register_host("comfyui")
        pyblish.api.register_plugin_path(PUBLISH_PATH)

    def get_containers(self):
        return self.stub.list_instances()

    def get_context_data(self):
        return self.stub.load_context()

    def update_context_data(self, data, changes):
        self.stub.imprint_context(data)

    def get_current_workfile(self):
        # Not too great, relies on a workfile having been opened
        return self._last_path or None

    def open_workfile(self, filepath):
        self.stub.load_workfile(filepath)
        return True

    def save_workfile(self, dst_path=None):
        workfile: str = self.stub.query_workfile()
        if workfile and isinstance(dst_path, str):
            with open(dst_path, mode="w", encoding="utf-8") as f:
                f.write(workfile)
                self.__class__._last_path = dst_path  # noqa: SLF001

    @property
    def stub(self):
        return QRPCManager.get_instance().stub


def uninstall() -> None:
    """Cleanup registration data."""
    pyblish.api.deregister_plugin_path(PUBLISH_PATH)
    pyblish.api.deregister_host("comfyui")

    deregister_loader_plugin_path(LOAD_PATH)
    deregister_creator_plugin_path(CREATE_PATH)
    # Not sure we'll use these.
    deregister_inventory_action_path(INVENTORY_PATH)
    deregister_workfile_build_plugin_path(WORKFILE_BUILD_PATH)


def list_instances() -> list[dict[str, Any]]:
    """Get cached instances in metadata.

    Returns:
    List of dictionaries describing instances
    """
    stub = QRPCManager.get_instance().stub
    instances = stub.list_instances()

    return instances or []
