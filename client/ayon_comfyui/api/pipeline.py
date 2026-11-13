"""Actual host definition.

Will be launched as a subprocess.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Generator
from typing import Any
from uuid import uuid4

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
    Anatomy,
    get_current_project_name,
    deregister_creator_plugin_path,
    deregister_loader_plugin_path,
    register_creator_plugin_path,
    register_loader_plugin_path,
)

from ayon_comfyui import COMFYUI_ADDON_ROOT
from ayon_comfyui.api.consts import LOG_LEVEL
from ayon_comfyui.api.bridge import get_stub
from ayon_comfyui.api.rpc_stub import RPCStub

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")

PLUGINS_DIR = os.path.join(COMFYUI_ADDON_ROOT, "plugins")
PUBLISH_PATH = os.path.join(PLUGINS_DIR, "publish")
LOAD_PATH = os.path.join(PLUGINS_DIR, "load")
CREATE_PATH = os.path.join(PLUGINS_DIR, "create")


class ComfyUIHost(HostBase, IWorkfileHost, ILoadHost, IPublishHost):
    """Main implementation of actual host operations."""

    name = "comfyui"

    def __init__(self) -> None:
        super().__init__()
        # Workfiles AYON opened or saved in this session.
        self._known_workfiles: set[str] = set()
        # Project name -> normalized `<root>/<project name>` folders.
        self._project_dirs_cache: dict[str, list[str]] = {}

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

    def get_current_workfile(self) -> str | None:
        """Return the AYON workfile path of the active ComfyUI workflow.

        ComfyUI has no notion of files on disk, so we store the AYON workfile
        path in the graph (`extra.AYON.workfile_path`) on open and save.

        That path comes from the browser and travels with the workflow, e.g.
        in a workflow file someone shared. Since AYON saves to it, it's
        only trusted when AYON opened or saved it in this session, or when
        it's a `.json` file inside the current project's folders.
        """
        path = self.stub.get_workfile_path()
        if not path:
            return None
        if not self._is_trusted_workfile(path):
            log.warning(
                "Ignoring workfile path '%s' stored in the ComfyUI workflow: "
                "AYON didn't open or save it in this session and it isn't a "
                ".json file inside the project's folders.",
                path,
            )
            return None
        return path

    def open_workfile(self, filepath: str) -> bool:
        """Open workfile in a ComfyUI workflow tab."""
        self.stub.load_workfile(filepath)
        self._known_workfiles.add(_normalize_path(filepath))
        return True

    def _is_trusted_workfile(self, path: str) -> bool:
        normalized = _normalize_path(path)
        if normalized in self._known_workfiles:
            return True
        if os.path.splitext(normalized)[1] != ".json":
            return False
        return any(
            normalized.startswith(directory + os.sep)
            for directory in self._get_trusted_dirs()
        )

    def _get_trusted_dirs(self) -> list[str]:
        """Folders whose `.json` files may be this project's workfiles.

        That's `<root>/<project name>` for each of the project's anatomy
        roots (roots themselves are usually shared by all projects), plus
        the current task's work directory for templates laid out
        differently.
        """
        project_name = get_current_project_name()
        dirs = []
        workdir = os.environ.get("AYON_WORKDIR")
        if workdir:
            dirs.append(_normalize_path(workdir))
        if project_name:
            project_dirs = self._project_dirs_cache.get(project_name)
            if project_dirs is None:
                try:
                    anatomy_roots = Anatomy(project_name).roots
                    project_dirs = [
                        _normalize_path(os.path.join(str(root), project_name))
                        for root in anatomy_roots.values()
                        if str(root)
                    ]
                except Exception:  # noqa: BLE001
                    log.warning(
                        "Unable to get the roots of project '%s'",
                        project_name,
                        exc_info=True,
                    )
                    project_dirs = []
                self._project_dirs_cache[project_name] = project_dirs
            dirs.extend(project_dirs)
        # An empty prefix (e.g. a root of '/') would accept any path.
        return [d.rstrip(os.sep) for d in dirs if d.rstrip(os.sep)]

    def save_workfile(self, dst_path: str | None = None) -> None:
        """Save the active ComfyUI workflow to `dst_path`.

        When `dst_path` is not passed, saves to the current workfile path,
        unless the user switched tabs since it was queried.
        """
        in_place = dst_path is None
        if in_place:
            dst_path = self.get_current_workfile()
            if not dst_path:
                msg = (
                    "The active ComfyUI workflow is not an AYON workfile yet. "
                    "Use the Workfiles tool to save it."
                )
                raise RuntimeError(msg)

        self.stub.save_workfile(dst_path, in_place=in_place)
        self._known_workfiles.add(_normalize_path(dst_path))

    @property
    def stub(self) -> RPCStub:
        """Retrieve stub to interact with the paired ComfyUI tab."""
        return get_stub()


def _normalize_path(path: str) -> str:
    # `realpath` so a symlink can't point a trusted path somewhere else.
    return os.path.normcase(os.path.realpath(path))


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
    instances = get_stub().list_instances()

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
    stub = get_stub()

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
        containers: list[dict[str, str]] = get_stub().list_containers()
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
