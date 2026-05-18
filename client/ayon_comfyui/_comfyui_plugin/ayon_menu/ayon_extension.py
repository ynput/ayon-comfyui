"""Define Entrypoint for all AYON related plugins and nodes.

Using the V3 API to remain compatible for a loooooong time.
"""

from threading import Thread

from comfy_api.latest import ComfyExtension, io
from typing_extensions import override

from .nodes.context_node import AyonContextNode
from .nodes.load_nodes import (
    AyonLoad3DModelNode,
    AyonLoadImageNode,
    AyonLoadVideoNode,
)
from .nodes.publish_nodes import (
    AyonSave3DModelNode,
    AyonSaveNode,
    AyonSaveVideoNode,
)
from .ws_server import run_server


class AyonComfyUIExtension(ComfyExtension):
    """Main Ayon Extension"""

    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [
            AyonSaveNode,
            AyonSaveVideoNode,
            AyonSave3DModelNode,
            AyonContextNode,
            AyonLoadImageNode,
            AyonLoadVideoNode,
            AyonLoad3DModelNode,
        ]


async def comfy_entrypoint() -> AyonComfyUIExtension:
    print("Running internal websocket server for Ayon...")
    Thread(target=run_server).start()
    return AyonComfyUIExtension()
