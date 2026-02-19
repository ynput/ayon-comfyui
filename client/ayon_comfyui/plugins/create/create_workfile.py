from __future__ import annotations

from ayon_comfyui.api.plugin import ComfyUIAutoCreator


class CreateWorkfile(ComfyUIAutoCreator):
    identifier = "workfile"
    label = "Workfile"
    product_type = "workfile"

    default_variant = "Main"

    def get_detail_description(self):
        return """Auto creator Workfiles.
        """

    def apply_settings(self, project_settings):
        # plugin_settings = (
        #     project_settings["photoshop"]["create"]["WorkfileCreator"]
        # )

        self.active_on_create = True
        self.enabled = True
