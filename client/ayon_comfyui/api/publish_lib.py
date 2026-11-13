"""Helpers for the publish plugins that run and collect ComfyUI outputs."""

from __future__ import annotations

import time

from ayon_comfyui.api.bridge import get_bridge
from ayon_comfyui.api.comfy_http import ComfyHttp

#: Families of the instances made by the AYON save nodes' creators.
OUTPUT_FAMILIES = ["image", "render", "model"]

#: `instance.data` key with the ComfyUI run of an output instance:
#: {promptId, prompt, workflow, outputNodeId, recooked, outputs}.
COMFYUI_KEY = "comfyui"


def get_comfy_http() -> ComfyHttp:
    """Return an HTTP client for the ComfyUI of this AYON session."""
    return ComfyHttp(get_bridge().comfy_url)


def responsive_sleep(seconds: float) -> None:
    """Sleep, but keep the Qt UI (e.g. the Publisher) responsive.

    Publish plugins run on the Qt main thread, so waiting for a long render
    would otherwise freeze the Publisher and make Windows report it as not
    responding. The Publisher only queues its next step after a plugin
    returns, so processing events meanwhile doesn't start other plugins.
    """
    try:
        from qtpy import QtCore, QtWidgets  # noqa: PLC0415
    except ImportError:
        time.sleep(seconds)
        return
    app = QtWidgets.QApplication.instance()
    if app is None or QtCore.QThread.currentThread() != app.thread():
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.05, remaining))
