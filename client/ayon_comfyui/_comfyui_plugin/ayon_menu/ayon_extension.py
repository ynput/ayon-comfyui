"""Define Entrypoint for all AYON related plugins and nodes.

Using the V3 API to remain compatible for a loooooong time.
"""

from threading import Thread

from comfy_api.latest import ComfyExtension, io
from typing_extensions import override

from .nodes.context_node import AyonContextNode
from .nodes.load_image_node import AyonLoadImageNode
from .nodes.publish_node import AyonSaveNode
from .ws_server import run_server


class AyonComfyUIExtension(ComfyExtension):
    """Main Ayon Extension"""

    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [AyonSaveNode, AyonContextNode, AyonLoadImageNode]


async def comfy_entrypoint() -> AyonComfyUIExtension:
    print("Running internal websocket server for Ayon...")
    Thread(target=run_server).start()
    return AyonComfyUIExtension()
