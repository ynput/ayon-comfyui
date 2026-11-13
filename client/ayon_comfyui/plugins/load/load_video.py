"""Load video definition."""

from __future__ import annotations

from typing import ClassVar

from ayon_core.lib.transcoding import VIDEO_EXTENSIONS

from ayon_comfyui.api.plugin import ComfyUILoader
from ayon_comfyui.api.rpc_stub import LoadType


class VideoLoader(ComfyUILoader):
    """Load video."""

    product_types: ClassVar[set[str]] = {"*"}
    representations: ClassVar[set[str]] = {"*"}
    extensions: ClassVar[set[str]] = {
        ext.lstrip(".") for ext in VIDEO_EXTENSIONS
    }
    label = "Load video into current graph."
    icon = "image"
    order = -10.1

    load_type = LoadType.VIDEO
