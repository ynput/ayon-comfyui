from __future__ import annotations

import json
import os
from pathlib import Path
from secrets import token_hex
from traceback import print_tb
from typing import MutableMapping

import folder_paths
import numpy as np
from comfy_api.latest import io, ui
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from torch import Tensor


class AyonSaveNode(io.ComfyNode):
    """A node that allows the user to Batch Save images with metadata."""

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.Image.Input("images_in", "Input Image"),
            io.Boolean.Input("recook", "Recook on publish", default=False),
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
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
            is_output_node=True,
        )

    # Ensure unique publish
    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return token_hex(16)

    @classmethod
    def execute(
        cls,
        images_in: Tensor | list[Tensor],
        recook: bool,  # Not used in code.
        ayon_info: str,
        prompt: MutableMapping = None,
        extra_pnginfo: list[MutableMapping] = None,
    ) -> io.NodeOutput:
        """Main execution function."""

        # parse ayon_info and retrieve settings from there.
        try:
            ayon_json = json.loads(ayon_info)
        except BaseException as e:
            print_tb(e)

        creator_attrs = ayon_json["creator_attributes"]

        keep_metadata = creator_attrs["keep_metadata"]
        file_prefix = creator_attrs["prefix"]
        use_unique_name = creator_attrs["use_unique_name"]
        unique_name = creator_attrs["unique_name"]

        compress_level = creator_attrs.get("compression_level", 4)

        output_dir = folder_paths.get_output_directory()

        # for:
        # folder_paths.get_save_image_path(
        #     filename_prefix = "renders/dragon"
        #     self.output_dir = "C:/ComfyUI/output"
        #     width = 1024
        #     height = 1024
        # )

        # full_output_folder = "C:/ComfyUI/output/renders"
        # filename = "dragon_1024x1024"
        # counter = 1 <- increments based on files that are already there
        # subfolder = "renders"
        # filename_prefix = "dragon"

        # I'm choosing to ignore the counter, and we're just going to overwrite the files.

        full_prefix = file_prefix
        if use_unique_name:
            full_prefix += f"_{unique_name}"

        full_output_folder, filename, counter, subfolder, filename_prefix = (
            folder_paths.get_save_image_path(
                f"AYON/{ayon_json['productName']}/{full_prefix}",
                output_dir,
                images_in[0].shape[1],
                images_in[0].shape[0],
            )
        )

        images_processed = []

        for idx, image in enumerate(images_in, start=1):
            image_data = 255.0 * image.cpu().numpy()
            img_pil = Image.fromarray(
                np.clip(image_data, 0, 255).astype(np.uint8)
            )
            # clip to 8 bit PNG. This could need work, png also supports 16 bit,1
            # if data needs to exist as float, and we need to export within OpenEXR,
            # we're screwed if we do this.

            metadata = None
            if keep_metadata:
                metadata = PngInfo()
                if prompt is not None:
                    metadata.add_text("prompt", json.dumps(prompt))
                if extra_pnginfo is not None:
                    for info in extra_pnginfo:
                        metadata.add_text(
                            info, json.dumps(extra_pnginfo[info])
                        )

            filename_out = f"{filename}_{idx:0>4}.png"
            img_path = os.path.join(full_output_folder, filename_out)

            # ensure path existence.

            Path(img_path).parent.mkdir(parents=True, exist_ok=True)
            img_pil.save(
                img_path, pnginfo=metadata, compress_level=compress_level
            )

            images_processed.append(
                ui.SavedResult(filename_out, subfolder, io.FolderType.output)
            )

        return io.NodeOutput(ui=ui.SavedImages(results=images_processed))
