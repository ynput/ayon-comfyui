from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

import pyblish.api
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import KnownPublishError
from ayon_core.pipeline.publish.lib import get_instance_staging_dir

if TYPE_CHECKING:
    from ayon_comfyui.api.pipeline import ComfyUIHost


class SaveCurrentScene(pyblish.api.ContextPlugin):
    """Save the collected workflow to its workfile before extraction.

    That's the workflow as `CollectComfyUIWorkflow` collected it, so the
    published workfile matches what was validated and what a recook
    renders, even when the artist kept working in its tab or switched tabs
    since. Its tab is only marked as saved when it still shows exactly that.

    The workfile instance publishes a copy, so saving the workfile again
    while publishing (e.g. "AYON > Save Workfile" in the tab) doesn't change
    what's published.
    """

    label = "Save current file"
    order = pyblish.api.ExtractorOrder - 0.49
    hosts = ["comfyui"]

    def process(self, context: pyblish.api.Context) -> None:
        current_file: str | None = context.data.get("currentFile")
        if not current_file:
            self.log.debug("Skipping save, current workflow is unsaved.")
            return

        workflow = (context.data.get("comfyuiApiPrompt") or {}).get("workflow")
        if not isinstance(workflow, dict):
            msg = "The ComfyUI workflow to publish wasn't collected."
            raise KnownPublishError(msg)

        host: ComfyUIHost = registered_host()
        self.log.debug(f"Saving current file: {current_file}")  # noqa: G004
        try:
            target = context.data.get("comfyuiWorkflow")
            with host.stub.target_workflow(target):
                host.stub.save_workfile_snapshot(current_file, workflow)
        except OSError as exc:
            msg = f"Unable to save the workfile '{current_file}': {exc}"
            raise KnownPublishError(msg) from exc

        self._stage_workfile(context, current_file)

    def _stage_workfile(
        self, context: pyblish.api.Context, current_file: str
    ) -> None:
        folder, filename = os.path.split(current_file)
        for instance in context:
            if "workfile" not in self._families(instance) or not (
                instance.data.get("publish", True)
                and instance.data.get("active", True)
            ):
                continue
            for representation in instance.data.get("representations", []):
                if representation.get("files") != filename or (
                    os.path.normpath(representation.get("stagingDir", ""))
                    != os.path.normpath(folder)
                ):
                    continue
                staging_dir = get_instance_staging_dir(instance)
                shutil.copy2(current_file, os.path.join(staging_dir, filename))
                representation["stagingDir"] = staging_dir
                self.log.debug("Staged the workfile in %s", staging_dir)

    @staticmethod
    def _families(instance: pyblish.api.Instance) -> set[str]:
        return {
            instance.data.get("productType"),
            instance.data.get("family"),
            *instance.data.get("families", []),
        }
