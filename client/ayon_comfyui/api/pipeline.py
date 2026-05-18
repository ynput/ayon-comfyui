"""Actual host definition.

Will be launched as a subprocess.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Generator
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
    AYON_CONTAINER_ID,
    deregister_creator_plugin_path,
    deregister_loader_plugin_path,
    register_creator_plugin_path,
    register_loader_plugin_path,
)

from ayon_comfyui import COMFYUI_ADDON_ROOT
from ayon_comfyui.api.consts import LOG_LEVEL
from ayon_comfyui.api.qt_rpc import QRPCManager, RPCStub

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")

PLUGINS_DIR = os.path.join(COMFYUI_ADDON_ROOT, "plugins")
PUBLISH_PATH = os.path.join(PLUGINS_DIR, "publish")
LOAD_PATH = os.path.join(PLUGINS_DIR, "load")
CREATE_PATH = os.path.join(PLUGINS_DIR, "create")

from uuid import uuid4


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

        register_loader_plugin_path(LOAD_PATH)
        register_creator_plugin_path(CREATE_PATH)

        # Pyblish
        pyblish.api.register_host("comfyui")
        pyblish.api.register_plugin_path(PUBLISH_PATH)

    def get_containers(self):
        return ls()

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
    def stub(self) -> RPCStub:
        """Retrieve stub to interact with client."""
        return QRPCManager.get_instance().stub


def uninstall() -> None:
    """Cleanup registration data."""
    pyblish.api.deregister_plugin_path(PUBLISH_PATH)
    pyblish.api.deregister_host("comfyui")

    deregister_loader_plugin_path(LOAD_PATH)
    deregister_creator_plugin_path(CREATE_PATH)


def list_instances() -> list[dict[str, Any]]:
    """Get cached instances in metadata.

    Returns:
    List of dictionaries describing instances
    """
    stub = QRPCManager.get_instance().stub
    instances = stub.list_instances()

    return instances or []


def containerise(  # noqa: PLR0913, PLR0917
    name: str,
    namespace: str,
    context: dict,
    image_upload_info: dict | list[dict],
    loader: str | None = None,
    suffix: str | None = "_CON",
) -> dict:
    """Imprint layer with metadata.

    Containerisation enables a tracking of version, author and origin
    for loaded assets.

    Arguments:
        name (str): Name of resulting assembly
        namespace (str): Namespace under which to host container
        context (dict): Asset information
        image_upload_info (dict, list[dict]): Uploaded image information,
                                  gotten back from /upload/image endpoint
        loader (str, optional): Name of loader used to produce this container.
        suffix (str, optional): Suffix of container, defaults to `_CON`.

    Returns:
        container (str): Name of container assembly
    """
    # TODO(@sas): Retrieve filename and store in container dict.

    container_name = name + suffix

    if isinstance(image_upload_info, dict):
        image_upload_info = [image_upload_info]

    data = {
        "schema": "ayon:container-3.0",
        "id": AYON_CONTAINER_ID,
        "name": name,
        "namespace": namespace,
        "loader": str(loader),
        "image_upload_info": image_upload_info,
        "representation": context["representation"]["id"],
        "container_uuid": str(uuid4()),
        "container_name": container_name,
    }
    stub = QRPCManager.get_instance().stub

    # TODO(@sas): Expand stub logic to keep track of containers separately,
    #             for my own sanity. That way, we can track representation
    #             instead of instance_id, and we might also want to enforce
    #             some uuid to keep track of every instance we make, since
    #             I can forsee people wanting to import the same image twice.
    #             It seems that regular implementations separate this through
    #             ls() and list_instances(), I guess. We will cleanly separate
    #             them.

    stub.add_containers(data)
    return data


def ls() -> Generator[dict[str, str], None, None]:
    """Yields valid containers.

    Equivalent to ayon core api.ls().
    """
    try:
        rpcman = QRPCManager.get_instance()
        containers: list[dict[str, str]] = rpcman.stub.list_containers()
    except BaseException:  # noqa: BLE001
        return

    if not containers:
        return

    for container in containers:
        # Validate ID
        if not (con_id := container.get("id")) or "container" not in con_id:
            continue

        container["objectName"] = container.get("name")
        # Explicitly set namespace so that name shows up in UI
        container["namespace"] = (
            container.get("name")
            if container["namespace"] is None
            else container["namespace"]
        )
        yield container
