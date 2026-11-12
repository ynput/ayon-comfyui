from __future__ import annotations

from typing import TYPE_CHECKING

import pyblish.api
from ayon_core.pipeline import registered_host

if TYPE_CHECKING:
    from ayon_comfyui.api.pipeline import ComfyUIHost


class SaveCurrentScene(pyblish.api.ContextPlugin):
    """Save the current workfile before extraction.

    This ensures the published workfile matches the current state of the
    ComfyUI workflow that is being published.
    """

    label = "Save current file"
    order = pyblish.api.ExtractorOrder - 0.49
    hosts = ["comfyui"]

    def process(self, context: pyblish.api.Context) -> None:
        current_file: str | None = context.data.get("currentFile")
        if not current_file:
            self.log.debug("Skipping save, current workflow is unsaved.")
            return

        host: ComfyUIHost = registered_host()
        if host.get_current_workfile() != current_file:
            msg = (
                "The active ComfyUI workflow changed during publishing. "
                f"Expected workfile: {current_file}"
            )
            raise RuntimeError(msg)

        self.log.debug(f"Saving current file: {current_file}")  # noqa: G004
        host.save_workfile(current_file)
