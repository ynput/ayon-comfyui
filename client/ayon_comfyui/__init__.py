"""The Ayon ComfyUI addon.

We should:
- On launch, check settings
- If not set to connect to external running ComfyUI, run local
- Establish a websocket connection as a Client.
  (comfyUI is running a server through a plugin
  on port 55055 endpoint ws:/x.x.x.x:port/ws)
"""

from .addon import COMFYUI_ADDON_ROOT, ComfyUIAddon, get_launch_script_path
from .version import __version__

__all__ = [
    "COMFYUI_ADDON_ROOT",
    "ComfyUIAddon",
    "__version__",
    "get_launch_script_path",
]
