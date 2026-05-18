from __future__ import annotations

import hashlib
import json
import os

import folder_paths
import node_helpers
import numpy as np
import torch
from comfy_api.latest import io, ui
from PIL import Image, ImageOps, ImageSequence


class AyonLoadImageNode(io.ComfyNode):
    """Container node loading a specified image."""

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.String.Input("ayon_container_info", "AYON context"),
        ]

    @staticmethod
    def define_outputs() -> list[io.Output]:
        return [
            io.Image.Output("image"),
            io.Mask.Output("mask"),
        ]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="AYON Load Image",
            display_name="AYON Load Image",
            category="AYON",
            inputs=AyonLoadImageNode.define_inputs(),
            outputs=AyonLoadImageNode.define_outputs(),
            is_output_node=True,
        )

    # See if image is unique
    @classmethod
    def fingerprint_inputs(cls, ayon_container_info: str):
        container = json.loads(ayon_container_info)
        upload_infos = container["image_upload_info"]

        input_dir = folder_paths.get_input_directory()
        for upload_info in upload_infos:
            image_path = os.path.join(
                input_dir, upload_info["subfolder"], upload_info["name"]
            )
            image_path = os.path.normpath(image_path)

            m = hashlib.sha256()
            with open(image_path, "rb") as f:
                m.update(f.read())
        return m.digest().hex()

    @classmethod
    def execute(cls, ayon_container_info: str):
        """Mimic nodes.py/LoadImage with container info imprinted on node."""
        container = json.loads(ayon_container_info)
        upload_infos = container["image_upload_info"]

        input_dir = folder_paths.get_input_directory()
        image_paths = [
            os.path.join(
                input_dir, upload_info["subfolder"], upload_info["name"]
            )
            for upload_info in upload_infos
        ]
        image_paths = [
            os.path.normpath(image_path) for image_path in image_paths
        ]

        output_images = []
        output_savedimages = []
        output_masks = []
        w, h = None, None

        for upload_info, image_path in zip(upload_infos, image_paths):
            img: Image = node_helpers.pillow(Image.open, image_path)
            saved_result = ui.SavedResult(
                upload_info["name"],
                upload_info["subfolder"],
                io.FolderType.input,
            )
            output_savedimages.append(saved_result)
            for i in ImageSequence.Iterator(img):
                i: Image.Image = node_helpers.pillow(
                    ImageOps.exif_transpose, i
                )

                if i.mode == "I":
                    i = i.point(lambda i: i * (1 / 255))
                image: Image.Image = i.convert("RGB")

                if len(output_images) == 0:
                    w = image.size[0]
                    h = image.size[1]

                if image.size[0] != w or image.size[1] != h:
                    continue

                image = np.array(image).astype(np.float32) / 255.0
                image = torch.from_numpy(image)[None,]
                if "A" in i.getbands():
                    mask = (
                        np.array(i.getchannel("A")).astype(np.float32) / 255.0
                    )
                    mask = 1.0 - torch.from_numpy(mask)
                elif i.mode == "P" and "transparency" in i.info:
                    mask = (
                        np.array(i.convert("RGBA").getchannel("A")).astype(
                            np.float32
                        )
                        / 255.0
                    )
                    mask = 1.0 - torch.from_numpy(mask)
                else:
                    mask = torch.zeros(
                        (h, w), dtype=torch.float32, device="cpu"
                    )
                output_images.append(image)
                output_masks.append(mask.unsqueeze(0))

                if img.format == "MPO":
                    break  # ignore all frames except the first one for MPO format

        if len(output_images) > 1:
            output_image = torch.cat(output_images, dim=0)
            output_mask = torch.cat(output_masks, dim=0)
        else:
            output_image = output_images[0]
            output_mask = output_masks[0]

        return io.NodeOutput(
            output_image,
            output_mask,
            ui=ui.SavedImages(output_savedimages),
        )

    @classmethod
    def validate_inputs(cls, ayon_container_info):
        """Basic existence check."""
        container = json.loads(ayon_container_info)
        upload_infos = container["image_upload_info"]

        input_dir = folder_paths.get_input_directory()
        image_paths = [
            os.path.join(
                input_dir, upload_info["subfolder"], upload_info["name"]
            )
            for upload_info in upload_infos
        ]
        image_paths = [
            os.path.normpath(image_path) for image_path in image_paths
        ]

        for image_path, upload_info in zip(image_paths, upload_infos):
            if not os.path.exists(image_path):
                subpath = os.path.normpath(
                    os.path.join(upload_info["subfolder"], upload_info["name"])
                )
                return f"Image doesn't exits at {subpath}"

        return True
