from __future__ import annotations

from ayon_comfyui.api.plugin import ComfyUIAutoCreator


class CreateWorkfile(ComfyUIAutoCreator):
    identifier = "io.ayon.creators.comfyui.workfile"
    label = "Workfile"
    product_type = "workfile"

    default_variant = "Main"

    def get_detail_description(self):
        return """Auto creator Workfiles."""
