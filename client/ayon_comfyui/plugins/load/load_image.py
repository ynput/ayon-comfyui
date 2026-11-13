"""Load image definition."""

from __future__ import annotations

import os
from typing import ClassVar

import clique

from ayon_core.lib.transcoding import IMAGE_EXTENSIONS

from ayon_comfyui.api.plugin import ComfyUILoader
from ayon_comfyui.api.rpc_stub import LoadType


class ImageLoader(ComfyUILoader):
    """Load images."""

    product_types: ClassVar[set[str]] = {"*"}
    representations: ClassVar[set[str]] = {"*"}
    extensions: ClassVar[set[str]] = {
        ext.lstrip(".") for ext in IMAGE_EXTENSIONS
    }
    label = "Load image(s) into current graph."
    icon = "image"
    order = -10

    load_type = LoadType.IMAGE

    def get_upload_files(self, context: dict) -> list[str]:
        """Return all images of the sequence, if it is one."""
        return self.expand_files_if_sequence(context)

    def expand_files_if_sequence(self, context: dict) -> list[str]:
        """Return all images in sequence if appliccable."""
        filepath = self.filepath_from_context(context=context)
        basename = os.path.basename(filepath)
        filedir = os.path.dirname(filepath)
        files = [f for f in os.listdir(filedir) if not os.path.isdir(f)]

        collections, _ = clique.assemble(files)
        collections: list[clique.Collection]
        for collection in collections:
            if collection.match(basename):
                return [os.path.join(filedir, f) for f in collection]
        return [filepath]
