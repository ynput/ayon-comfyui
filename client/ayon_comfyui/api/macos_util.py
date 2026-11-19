"""macOS helpers to run the ComfyUI host as a background (Dock-less) app.

The host process (`ayon run launch_script.py`) has to live as long as
ComfyUI: it runs the RPC/static servers and shows the AYON tools. Unlike
DCCs with an embedded Python (Blender, Maya...), there is no other process to
hand that work to. Without this, macOS shows it as a second AYON app in the
Dock for the whole session.

Set AYON_COMFYUI_SHOW_IN_DOCK=1 to keep the Dock icon (debugging).
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("ayon_comfyui")

# NSApplicationActivationPolicyAccessory: no Dock icon / menu bar,
# but the app may still show windows and be activated.
_POLICY_ACCESSORY = 1


def _ns_app():  # noqa: ANN202
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSApplication
    except ImportError:
        log.debug("AppKit (pyobjc) not available, keeping Dock icon.")
        return None
    return NSApplication.sharedApplication()


def hide_from_dock() -> None:
    """Turn the process into an accessory app. Call after QApplication."""
    if os.getenv("AYON_COMFYUI_SHOW_IN_DOCK") == "1":
        return
    app = _ns_app()
    if app is None:
        return
    try:
        app.setActivationPolicy_(_POLICY_ACCESSORY)
    except Exception:  # noqa: BLE001
        log.debug("Could not hide host from Dock", exc_info=True)


def bring_to_front() -> None:
    """Activate the app so its windows come to the front of other apps.

    Needed for an accessory app: it never becomes active by itself, so
    windows it opens would otherwise stay behind the browser.
    """
    app = _ns_app()
    if app is None:
        return
    try:
        app.activateIgnoringOtherApps_(True)
    except Exception:  # noqa: BLE001
        log.debug("Could not activate host app", exc_info=True)
