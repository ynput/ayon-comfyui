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


def split_api_prompt(api_prompt: dict) -> tuple[dict, dict]:
    """Split the tab's `getApiPrompt` result into data and queue extras.

    Returns:
        The result without `extra_data`, safe to keep in publish data, and
        the `extra_data` to queue the prompt with: the tab's Comfy.org
        credentials for API nodes and its preview method, exactly what the
        tab sends when it queues itself. Never store or log those.
    """
    data = dict(api_prompt)
    extra = data.pop("extra_data", None)
    return data, extra if isinstance(extra, dict) else {}


#: ComfyUI plugin feature the host-driven publish needs (see the relay's
#: `FEATURES` in `_comfyui_plugin/ayon_menu/bridge.py`).
PUBLISH_FEATURE = "publish-v1"


def missing_plugin_feature(feature: str) -> str | None:
    """Return why the ComfyUI plugin can't do `feature`, or None if it can."""
    client = get_bridge().client
    if not client.registered or feature in client.plugin_features:
        # Not connected: the call that needs it explains that instead.
        return None
    return (
        f"The AYON plugin on ComfyUI at {get_bridge().comfy_url} is too old "
        f"for this AYON addon (it lacks '{feature}'). Update the AYON "
        "ComfyUI plugin on that ComfyUI server to the version shipped with "
        "this addon."
    )


def get_comfy_http() -> ComfyHttp:
    """Return an HTTP client for the ComfyUI of this AYON session."""
    return ComfyHttp(get_bridge().comfy_url)


def responsive_sleep(seconds: float) -> None:
    """Sleep, but keep the Qt UI (e.g. the Publisher) responsive.

    Publish plugins run on the Qt main thread, so waiting for a long render
    would otherwise freeze the Publisher and make Windows report it as not
    responding. Only non-input events are processed (repaints, timers), so
    nothing can be clicked meanwhile, and the Publisher only queues its next
    step after a plugin returns.
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
        app.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents, 50)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.05, remaining))
