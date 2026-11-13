"""Helpers for the publish plugins that run and collect ComfyUI outputs."""

from __future__ import annotations

import time

from ayon_comfyui.api.bridge import get_bridge
from ayon_comfyui.api.comfy_http import ComfyHttp
from ayon_comfyui.api.comfy_publish import PublishError

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
#: ... and to act on the published workflow while it isn't the active tab.
WORKFLOWS_FEATURE = "workflows-v1"


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


class RenderCancelled(PublishError):
    """The artist cancelled waiting for a ComfyUI render."""


class RenderWait:
    """Wait for a ComfyUI render without freezing the UI, and let it be
    cancelled.

    Publish plugins run on the Qt main thread, so waiting for a long render
    would otherwise freeze the Publisher (and make Windows report it as not
    responding), and its Stop button only acts between plugins. While
    waiting, a small window shows the render's progress with a "Cancel
    render" button. It's modal to the Publisher only: the publish works
    from the workflow it collected, so the artist may keep using ComfyUI
    and the other AYON tools meanwhile. Without a Qt application (e.g. a
    headless publish) it just sleeps.

    Use as a context manager; pass `sleep` and `progress` to
    `comfy_publish.wait_for_prompt`.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._status = "queued"
        self._started = time.monotonic()
        self._dialog = None
        self._app = None

    def __enter__(self) -> RenderWait:
        try:
            from qtpy import QtCore, QtWidgets  # noqa: PLC0415
        except ImportError:
            return self
        app = QtWidgets.QApplication.instance()
        if app is None or QtCore.QThread.currentThread() != app.thread():
            return self
        # Modal to the Publisher, which runs the publish. Without one, to
        # everything.
        parent = next(
            (
                widget
                for widget in app.topLevelWidgets()
                if type(widget).__name__ == "PublisherWindow"
                and widget.isVisible()
            ),
            None,
        )
        dialog = QtWidgets.QProgressDialog(
            self._text, "Cancel render", 0, 0, parent
        )
        dialog.setWindowTitle("AYON - ComfyUI")
        dialog.setWindowModality(
            QtCore.Qt.WindowModal
            if parent is not None
            else QtCore.Qt.ApplicationModal
        )
        # Closing it must not quit an application that has no other window.
        dialog.setAttribute(QtCore.Qt.WA_QuitOnClose, False)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumWidth(420)
        dialog.show()
        self._app = app
        self._dialog = dialog
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._dialog is not None:
            self._dialog.close()
            self._dialog.deleteLater()
            self._dialog = None

    @property
    def dialog(self):  # noqa: ANN201
        """The progress window, None without Qt (for tests)."""
        return self._dialog

    def progress(self, message: str) -> None:
        """Show the render's state (from `wait_for_prompt`)."""
        self._status = message

    def sleep(self, seconds: float) -> None:
        """Sleep while keeping the UI alive.

        Raises:
            RenderCancelled: When the artist pressed "Cancel render".
        """
        if self._dialog is None:
            time.sleep(seconds)
            return
        from qtpy import QtCore  # noqa: PLC0415

        deadline = time.monotonic() + seconds
        while True:
            elapsed = time.monotonic() - self._started
            self._dialog.setLabelText(
                f"{self._text}\n\n{self._status}\n{elapsed:.0f} s"
            )
            self._app.processEvents(QtCore.QEventLoop.AllEvents, 50)
            if self._dialog.wasCanceled():
                msg = "The ComfyUI render was cancelled."
                raise RenderCancelled(msg)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.05, remaining))
