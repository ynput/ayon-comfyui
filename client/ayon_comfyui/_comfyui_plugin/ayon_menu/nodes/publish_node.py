from __future__ import annotations

import numpy as np
from comfy_api.latest import io, ui
from PIL import Image
from torch import Tensor


class AyonSaveNode(io.ComfyNode):
    """A node that allows the user to Batch Save images with metadata."""

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.Image.Input("image_in", "Input Image"),
            io.String.Input("ayon_info", "info"),
        ]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="AYON Image Save",
            display_name="AYON Image Save",
            category="AYON",
            inputs=AyonSaveNode.define_inputs(),
            hidden=[io.Hidden.unique_id],
            is_output_node=True,
        )

    @classmethod
    def execute(
        cls,
        images_in: Tensor | list[Tensor],
        ayon_info: str,
        unique_id: str,
    ) -> io.NodeOutput:
        """Main execution function."""

        images_processed = []

        if isinstance(images_in, Tensor):
            images_in = [images_in]

        for idx, image in enumerate(images_in):
            image_data = float(255) * image.cpu().numpy()
            img_pil = Image.fromarray(np.clip(image_data, 0, 255).astype(np.uint8))
            # clip to 8 bit PNG. This could need work, png also supports 16 bit,
            # if data needs to exist as float, and we need to export within OpenEXR,
            #

            images_processed.append(img_pil)

        # Save images

        image_files = []

        return io.NodeOutput(ui=ui.SavedImages(image_files))
