"""Define Entrypoint for all AYON related plugins and nodes.

Using the V3 API to remain compatible for a loooooong time.
"""

from comfy_api.latest import ComfyExtension, io
from server import PromptServer
from typing_extensions import override

from .bridge import BRIDGE
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
from .paths import add_routes as add_path_routes

# Routes on ComfyUI's own server that the AYON host and the paired ComfyUI
# tab connect to.
BRIDGE.add_routes(PromptServer.instance.routes)
# Lets AYON check which files this server can read by path.
add_path_routes(PromptServer.instance.routes)


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
    return AyonComfyUIExtension()
