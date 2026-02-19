"""Define Entrypoint for all AYON related plugins and nodes.

Using the V3 API to remain compatible for a loooooong time.
"""

from threading import Thread

from comfy_api.latest import ComfyExtension, io
from typing_extensions import override

from .ensure_modules import ensure_wsrpc

# make sure aiohttp_wsrpc dependency is present
ensure_wsrpc()

# we can only continue if wsrpc is actually there.
from .nodes.context_node import AyonContextNode  # noqa: E402
from .nodes.publish_node import AyonSaveNode  # noqa: E402
from .RPC import run_server  # noqa: E402


class AyonComfyUIExtension(ComfyExtension):
    """Main Ayon Extension"""

    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [AyonSaveNode, AyonContextNode]

    def __del__(self):
        """Not needed."""
        print(f"{self.__class__.__qualname__} __del__")


async def comfy_entrypoint() -> AyonComfyUIExtension:
    print("Running internal ayon server...")
    Thread(target=run_server).start()
    return AyonComfyUIExtension()
