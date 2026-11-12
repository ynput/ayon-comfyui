"""Actions the AYON menu in ComfyUI asks the AYON host to run.

These run in the Qt main thread.
"""

from __future__ import annotations

import logging

from ayon_core.pipeline import registered_host
from ayon_core.tools.utils import host_tools

log = logging.getLogger(__name__)

# Tool names the ComfyUI tab may ask for; anything else is refused.
TOOL_NAMES = frozenset({
    "publisher",
    "create",
    "workfiles",
    "loader",
    "sceneinventory",
    "scripteditor",
})

# Keep a reference so the window doesn't get garbage collected instantly
console_window = None


def show_script_editor() -> None:
    """Show the AYON Python Script Editor (console interpreter)."""
    from ayon_core.tools.console_interpreter import (  # noqa: PLC0415
        InterpreterController,
    )
    from ayon_core.tools.console_interpreter.ui import (  # noqa: PLC0415
        ConsoleInterpreterWindow,
    )
    from qtpy import QtCore  # noqa: PLC0415

    global console_window  # noqa: PLW0603
    if console_window is None:
        controller = InterpreterController(name="comfyui")
        console_window = ConsoleInterpreterWindow(controller)
        console_window.setWindowTitle("Python Script Editor - ComfyUI")
        console_window.setWindowFlags(
            console_window.windowFlags()
            | QtCore.Qt.Dialog
            | QtCore.Qt.WindowMinimizeButtonHint
        )
    console_window.show()
    console_window.raise_()
    console_window.activateWindow()


def show_tool_by_name(tool_name: str) -> None:
    """Show host tool by name, with default settings."""
    if tool_name == "scripteditor":
        show_script_editor()
        return

    kwargs = {}
    if tool_name == "loader":
        kwargs["use_context"] = True

    if tool_name == "create":
        tool_name = "publisher"
        kwargs["tab"] = "create"
    elif tool_name == "publisher":
        kwargs["tab"] = "publish"

    host_tools.show_tool_by_name(tool_name, **kwargs)


def save_current_workfile() -> None:
    """Save current workfile, or show Workfiles tool if it's unsaved."""
    host = registered_host()
    current_path = host.get_current_workfile()
    if not current_path:
        log.info("Workflow is not an AYON workfile yet, showing Workfiles.")
        show_tool_by_name("workfiles")
        return

    try:
        host.save_workfile(current_path)
    except Exception as exc:
        log.exception("Failed to save workfile: %s", current_path)
        from qtpy import QtWidgets  # noqa: PLC0415

        QtWidgets.QMessageBox.critical(
            None, "AYON - Save Workfile failed", f"{current_path}\n\n{exc}"
        )
        return
    log.info("Saved workfile: %s", current_path)
