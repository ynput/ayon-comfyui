"""Load 3d model definition."""

from __future__ import annotations

from typing import ClassVar

from ayon_comfyui.api.plugin import ComfyUILoader
from ayon_comfyui.api.rpc_stub import LoadType


class ModelLoader(ComfyUILoader):
    """Load model.

    TODO(@sas): Only supports exports for singular models,
    expand so that sequences of objs/glbs can be properly loaded,
    but maybe, we have to make multiple Loader nodes as any File3D type
    isn't batchable.
    """

    product_types: ClassVar[set[str]] = {"model"}
    # Published representations are named by their extension, without dot.
    representations: ClassVar[set[str]] = {"*"}
    extensions: ClassVar[set[str]] = {
        "gltf",
        "glb",
        "obj",
        "fbx",
        "stl",
        "spz",
        "splat",
        "ply",
        "ksplat",
    }
    label = "Load model into current graph."
    icon = "robot"
    order = -10.2

    load_type = LoadType.MODEL3D
