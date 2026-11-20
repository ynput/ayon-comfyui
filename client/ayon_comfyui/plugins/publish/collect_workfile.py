import os

import pyblish.api


class CollectWorkfile(pyblish.api.InstancePlugin):
    """Collect current workflow path for publish.

    The workfile itself is saved by `SaveCurrentScene` before extraction so
    the published file matches the current state of the graph.
    """

    order = pyblish.api.CollectorOrder - 0.49
    label = "Collect Workfile"
    hosts = ["comfyui"]
    families = ["workfile"]

    default_variant = "Main"

    def process(self, instance):

        current_workfile: str | None = instance.context.data["currentFile"]
        if not current_workfile:
            # Reported to the artist by `ValidateCurrentSaveFile` of core
            self.log.warning(
                "Current workflow is not saved as an AYON workfile."
            )
            return

        staging_dir, filename = os.path.split(current_workfile)
        ext = os.path.splitext(filename)[1]

        # creating representation
        instance.data.setdefault("representations", []).append(
            {
                "name": ext[1:],
                "ext": ext[1:],
                "files": filename,
                "stagingDir": staging_dir,
            }
        )
