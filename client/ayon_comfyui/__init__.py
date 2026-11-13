"""The AYON ComfyUI addon.

On launch, AYON either starts ComfyUI locally or uses a running (remote)
ComfyUI, then connects to the AYON bridge route of the ComfyUI plugin as a
websocket client and pairs the ComfyUI browser tab with this session.
"""

from .addon import COMFYUI_ADDON_ROOT, ComfyUIAddon, get_launch_script_path
from .version import __version__

__all__ = [
    "COMFYUI_ADDON_ROOT",
    "ComfyUIAddon",
    "__version__",
    "get_launch_script_path",
]
