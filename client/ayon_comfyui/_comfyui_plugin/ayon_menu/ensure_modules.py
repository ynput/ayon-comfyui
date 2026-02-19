"""This module is entirely illegal to the safety standards of ComfyUI,
as it relies on module installing through subprocessing pip.
This is tantamount to malware, so, ideally, we'd use something else,
but when something is deployed serverside, we lose control.

Right now modules that would be required for this to not run are
- wsrpc-aiohttp (protocol for remote procedure calls over websocket)
- (TBD) OpenEXR
"""

import importlib.util
import subprocess
import sys


def ensure_wsrpc():
    """Ensure presence of wsrpc_aiohttp module.

    This sucks.
    Since we have no control over how and where the plugin is launched,
    we have to inject the module here.

    This is also explicitly forbidden, but since we're not trying to
    get our custom nodes 'officially' published by ComfyUI, it's permitted
    for now. Should that change in the future, then wsrpc reliant
    functionality can be rewritten."""

    if not importlib.util.find_spec("wsrpc_aiohttp"):
        exec_ = sys.executable
        subprocess.run([exec_, "-m", "pip", "install", "wsrpc-aiohttp"])
