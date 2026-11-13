"""Define collector for the frame range of generated images."""

import pyblish.api


class CollectFrameRange(pyblish.api.InstancePlugin):
    """Collect the frame range of generated images.

    Each image is one frame, starting at 1, without handles. Extract Review
    needs `frameStart`, `frameEnd` and `fps`; the frame rate comes from the
    task.
    """

    order = pyblish.api.CollectorOrder + 0.151
    label = "Collect Frame Range"
    hosts = ["comfyui"]
    families = ["image"]

    def process(self, instance: pyblish.api.Instance) -> None:
        """Set the frame range from the number of collected images."""
        review_files = next(
            (
                repre["files"]
                for repre in instance.data.get("representations", [])
                if "review" in repre.get("tags", [])
            ),
            None,
        )
        if not review_files:
            return

        frame_count = 1 if isinstance(review_files, str) else len(review_files)
        instance.data.update({
            "frameStart": 1,
            "frameEnd": frame_count,
            "handleStart": 0,
            "handleEnd": 0,
            "frameStartHandle": 1,
            "frameEndHandle": frame_count,
            "fps": instance.data.get("fps") or instance.context.data["fps"],
        })
        self.log.debug("Frame range: 1-%s", frame_count)
