from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pyblish.api

if TYPE_CHECKING:
    from ayon_comfyui.api.pipeline import ComfyUIHost

from ayon_core.host.interfaces import SaveWorkfileOptionalData
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import get_errored_plugins_from_context
from ayon_core.pipeline.workfile import (
    save_next_version,
)

from ayon_comfyui.api.bridge_client import BridgeError


class IncrementWorkfile(pyblish.api.InstancePlugin):
    """Increment the current workfile.

    Saves the published workflow (tab) with an increased version number,
    including what the artist changed in it while publishing. That's also
    when it's no longer the active tab; when it was closed, nothing is
    saved.
    """

    label = "Increment Workfile"
    order = pyblish.api.IntegratorOrder + 9.0
    hosts = ["comfyui"]
    families = ["workfile"]
    optional = True

    def process(self, instance):
        context = instance.context
        errored_plugins = get_errored_plugins_from_context(context)
        if errored_plugins:
            raise RuntimeError(
                "Skipping incrementing current file because publishing failed."
            )

        version = None
        current_filepath: str = context.data["currentFile"]
        host: ComfyUIHost = registered_host()

        current_filename = os.path.basename(current_filepath)
        workflow = context.data.get("comfyuiWorkflow")
        # The artist may have opened another task's workfile while
        # publishing; `save_next_version` saves into the current context.
        current = host.get_current_context()
        published = (context.data.get("folderPath"), context.data.get("task"))
        if (current.get("folder_path"), current.get("task_name")) != published:
            self.log.warning(
                "Not incrementing the workfile: the AYON context changed "
                "to %s/%s while publishing %s/%s.",
                current.get("folder_path"), current.get("task_name"),
                *published,
            )
            return
        try:
            with host.stub.target_workflow(workflow):
                save_next_version(
                    version=version,
                    description=(
                        f"Incremented by publishing from {current_filename}"
                    ),
                    # Optimize the save by reducing needed queries for context
                    prepared_data=SaveWorkfileOptionalData(
                        project_entity=context.data.get("projectEntity"),
                        project_settings=context.data.get("project_settings"),
                        anatomy=context.data.get("anatomy"),
                    ),
                )
                new_scene_path = host.get_current_workfile()
        except BridgeError as exc:
            if exc.code != "workflow_closed":
                raise
            # Published fine; there's just no tab left to version up.
            self.log.warning(
                "Not incrementing the workfile: the ComfyUI workflow '%s' "
                "was closed while publishing.",
                (workflow or {}).get("workflow_label"),
            )
            return
        self.log.info(f"Incremented workfile to: {new_scene_path}")  # noqa: G004
