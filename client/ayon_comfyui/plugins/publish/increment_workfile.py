from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pyblish.api

if TYPE_CHECKING:
    from ayon_core.host import IWorkfileHost

from ayon_core.host.interfaces import SaveWorkfileOptionalData
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import get_errored_plugins_from_context
from ayon_core.pipeline.version_start import get_versioning_start
from ayon_core.pipeline.workfile import (
    save_next_version,
)


class IncrementWorkfile(pyblish.api.InstancePlugin):
    """Increment the current workfile.

    Saves the current scene with an increased version number.
    """

    label = "Increment Workfile"
    order = pyblish.api.IntegratorOrder + 9.0
    hosts = ["comfyui"]
    families = ["workfile"]
    optional = True

    def process(self, instance):
        errored_plugins = get_errored_plugins_from_context(instance.context)
        if errored_plugins:
            raise RuntimeError(
                "Skipping incrementing current file because publishing failed."
            )

        version = None
        context = instance.context
        current_filepath: str = context.data["currentFile"]
        host: IWorkfileHost = registered_host()

        if not instance.data["do_increment"]:
            self.log.info("Not incremented since first publish")
            version = get_versioning_start(
                instance.context.data.get("projectName"),
                host.name,
                task_name=instance.context.data["taskEntity"]["name"],
                task_type=instance.context.data["taskEntity"]["taskType"],
                product_type="workfile",
            )
            if version > 1:
                version -= 1

        current_filename = os.path.basename(current_filepath)

        save_next_version(
            version=version,
            description=(f"Incremented by publishing from {current_filename}"),
            # Optimize the save by reducing needed queries for context
            prepared_data=SaveWorkfileOptionalData(
                project_entity=context.data.get("projectEntity"),
                project_settings=context.data.get("project_settings"),
                anatomy=context.data.get("anatomy"),
            ),
        )

        new_scene_path = host.get_current_workfile()

        self.log.info(f"Incremented workfile to: {new_scene_path}")
