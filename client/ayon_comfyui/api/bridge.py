"""Connection between this AYON session and ComfyUI, managed in Qt.

`ComfyUIBridge` owns the `BridgeClient` (see `bridge_client.py`), the
ComfyUI process when AYON launched it, and the lifetime of the session:

- It connects to ComfyUI, asks for a pairing code and opens the paired
  ComfyUI tab in the browser.
- Requests from that tab (open a tool, save) run on the Qt main thread.
- When no tab is connected for a while, or ComfyUI can't be reached, a
  small "AYON - ComfyUI" window explains why, lets the artist reopen the
  ComfyUI tab, or quit the session. Nothing quits on its own, so a
  discarded tab, sleep or a network blip never kill a running ComfyUI.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import socket
import subprocess
import sys
import time
import webbrowser
from functools import partial
from typing import TYPE_CHECKING, Any

from qtpy import QtCore, QtGui, QtWidgets

from ayon_comfyui.api.bridge_client import (
    BridgeClient,
    BridgeError,
    check_plugin,
)
from ayon_comfyui.api.menu_actions import (
    TOOL_NAMES,
    save_current_workfile,
    show_tool_by_name,
)
from ayon_comfyui.api.rpc_stub import RPCStub

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

# Show the session window when no tab has been connected for this long.
TAB_GRACE_SECONDS = 10.0
# ...or when ComfyUI isn't reachable yet this long after launch; starting
# ComfyUI regularly takes a while.
STARTUP_GRACE_SECONDS = 30.0
# ...or this long after reconnecting to ComfyUI (e.g. after a restart),
# since the tab needs to reconnect too.
TAB_GRACE_AFTER_RECONNECT_SECONDS = 60.0
# Pairing codes expire on the ComfyUI side after 10 minutes; show a fresh
# one well before that.
PAIRING_CODE_MAX_AGE_SECONDS = 300.0
PAIRING_CODE_RETRY_SECONDS = 30.0

_BRIDGE: ComfyUIBridge | None = None


def get_bridge() -> ComfyUIBridge:
    """Return the running bridge of this AYON session."""
    if _BRIDGE is None:
        msg = "The AYON ComfyUI session is not connected to ComfyUI."
        raise BridgeError(msg, "not_started")
    return _BRIDGE


def get_stub() -> RPCStub:
    """Return the stub to talk to the paired ComfyUI tab."""
    return get_bridge().stub


def get_session_info() -> dict:
    """Return what the paired ComfyUI tab shows about this session."""
    from ayon_core.lib import get_ayon_username  # noqa: PLC0415
    from ayon_core.pipeline import get_current_context  # noqa: PLC0415

    from ayon_comfyui.version import __version__  # noqa: PLC0415

    context = get_current_context()
    try:
        user = get_ayon_username()
    except Exception:  # noqa: BLE001
        user = ""
    return {
        "user": user,
        "project": context.get("project_name") or "",
        "folder": context.get("folder_path") or "",
        "task": context.get("task_name") or "",
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "addon_version": __version__,
    }


class ComfyUIBridge(QtCore.QObject):
    """Connects this AYON session to ComfyUI and its paired tab.

    Args:
        comfy_url: URL of ComfyUI.
        process: ComfyUI process when AYON launched it; it is stopped when
            the session ends. A ComfyUI that AYON didn't start is never
            stopped.
        open_browser: Open the paired ComfyUI tab automatically; otherwise
            the session window shows the link to open.
        startup_timeout: Seconds to wait for ComfyUI to become reachable.
        on_first_tab: Called once, when the first tab connected.
    """

    _sig_call = QtCore.Signal(object)
    _sig_event = QtCore.Signal(str, object)

    def __init__(  # noqa: PLR0913
        self,
        comfy_url: str,
        *,
        process: subprocess.Popen | None = None,
        open_browser: bool = True,
        startup_timeout: float = 30.0,
        on_first_tab: Callable[[], None] | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        global _BRIDGE  # noqa: PLW0603
        _BRIDGE = self

        self.comfy_url = comfy_url
        self._process = process
        self._open_browser = open_browser
        self._startup_timeout = startup_timeout
        self._on_first_tab = on_first_tab

        self.client = BridgeClient(
            comfy_url, info=get_session_info(), on_event=self._on_client_event
        )
        self.stub = RPCStub(self.client)
        self.client.register_handler(
            "requestToolByName", self._handle_request_tool
        )
        self.client.register_handler(
            "requestSaveWorkfile", self._handle_request_save
        )
        self.client.register_handler("pingAyonMenu", self._handle_ping)

        self._started_at = time.monotonic()
        self._ever_connected = False
        self._had_tab = False
        self._disconnected_at: float | None = None
        self._no_tab_since: float | None = time.monotonic()
        self._tab_grace = TAB_GRACE_SECONDS
        self._pairing_url = ""
        self._pairing_code = ""
        self._pairing_code_at = 0.0
        self._pairing_code_pending = False
        self._open_tab_on_code = False
        self._shutting_down = False
        # Startup failed and the artist is being told; ignore late events.
        self._failed = False

        self._sig_call.connect(self._run_callable)
        self._sig_event.connect(self._handle_event)

        self._window = SessionWindow(self)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_state)

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Start connecting to ComfyUI."""
        log.info("Connecting to ComfyUI at %s", self.comfy_url)
        self.client.start()
        self._timer.start()
        try:
            from ayon_core.lib import register_event_callback  # noqa: PLC0415

            register_event_callback("taskChanged", self._on_task_changed)
        except Exception:  # noqa: BLE001
            log.debug("Unable to track context changes", exc_info=True)

    def shutdown(self) -> None:
        """End the session: disconnect, stop ComfyUI if we launched it."""
        if self._shutting_down:
            return
        self._shutting_down = True
        log.info("Ending the AYON ComfyUI session")
        self._timer.stop()
        self._window.hide()
        self.client.stop()
        self._stop_process()
        QtCore.QCoreApplication.exit(0)

    def _stop_process(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        log.info("Stopping ComfyUI (pid %s)", process.pid)
        if sys.platform == "win32":
            # Kill the whole tree: the console wrapper and ComfyUI itself.
            subprocess.run(  # noqa: S603
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],  # noqa: S607
                check=False,
                capture_output=True,
            )
        else:
            process.kill()
            process.wait()

    def _process_exited(self) -> bool:
        """Whether the ComfyUI that AYON launched is known to be gone.

        On Windows ComfyUI runs in a console (`powershell -NoExit`) that
        stays open until the artist closes it, so its exit means ComfyUI is
        gone. Elsewhere the terminal wrapper (`open -a Terminal`,
        `x-terminal-emulator`) may return right away while ComfyUI keeps
        running, so its exit says nothing.
        """
        if self._process is None or sys.platform != "win32":
            return False
        return self._process.poll() is not None

    # --- pairing ----------------------------------------------------------

    def open_tab(self) -> None:
        """Pair and open a new ComfyUI tab in the browser."""
        self._open_tab_on_code = True
        self.new_pairing_code()

    def new_pairing_code(self) -> None:
        """Ask for a fresh one-time pairing code and link.

        The relay answers in the background, so the Qt thread never waits
        on it; the session window updates (and the browser opens, after
        `open_tab`) once the code arrives.
        """
        if not self.client.registered or self._pairing_code_pending:
            return
        # Also counts as an attempt, so a failing relay isn't asked every
        # second.
        self._pairing_code_at = time.monotonic()
        try:
            future = self.client.call_nowait(None, timeout=10)
        except BridgeError as exc:
            log.warning("Unable to get a pairing code: %s", exc)
            self._open_tab_on_code = False
            return
        self._pairing_code_pending = True
        future.add_done_callback(
            lambda done: self.run_in_main_thread(
                partial(self._on_pairing_code, done)
            )
        )

    def _on_pairing_code(self, future: concurrent.futures.Future) -> None:
        self._pairing_code_pending = False
        open_tab = self._open_tab_on_code
        self._open_tab_on_code = False
        code = None
        if not future.cancelled() and future.exception() is None:
            code = future.result()
        if not code:
            error = None if future.cancelled() else future.exception()
            log.warning("Unable to get a pairing code: %s", error)
            self._pairing_code = ""
            self._pairing_url = ""
            self._window.update_view()
            return
        self._pairing_code = code
        self._pairing_url = self.client.pairing_url(code)
        self._window.update_view()
        if open_tab:
            log.info("Opening ComfyUI tab: %s", self.comfy_url)
            webbrowser.open(self._pairing_url)

    def ensure_pairing_code(self) -> None:
        """Make sure the session window shows a pairing code still valid."""
        age = time.monotonic() - self._pairing_code_at
        if age > PAIRING_CODE_MAX_AGE_SECONDS or (
            not self._pairing_code and age > PAIRING_CODE_RETRY_SECONDS
        ):
            self.new_pairing_code()

    def _forget_pairing_code(self) -> None:
        # A tab used it, or ComfyUI forgot it; get a new one when needed.
        self._pairing_code = ""
        self._pairing_url = ""
        self._pairing_code_at = 0.0

    # --- state --------------------------------------------------------------

    def status_text(self) -> str:
        """Describe the state of the session for the session window."""
        if not self.client.registered:
            if not self._ever_connected:
                return (
                    f"Waiting for ComfyUI at {self.comfy_url} to start..."
                )
            return (
                f"Lost the connection to ComfyUI at {self.comfy_url}. "
                "Reconnecting..."
            )
        if self.client.tab_connected:
            return "A ComfyUI tab is connected."
        if self._had_tab:
            return (
                "The ComfyUI tab disconnected. Reopen it to keep working, "
                "or quit the AYON session."
            )
        return (
            "Waiting for the ComfyUI tab to connect. If it didn't open, use "
            "'Open ComfyUI tab', or paste the pairing code into the AYON "
            "panel of an open ComfyUI tab."
        )

    @property
    def pairing_url(self) -> str:
        return self._pairing_url

    @property
    def pairing_code(self) -> str:
        return self._pairing_code

    def _update_state(self) -> None:
        """Every second: check startup timeout and session window."""
        if self._shutting_down:
            return
        now = time.monotonic()
        if not self.client.registered:
            if self._process_exited():
                log.info("ComfyUI exited, ending the AYON session.")
                self.shutdown()
                return
            if (
                not self._ever_connected
                and now - self._started_at > self._startup_timeout
            ):
                self._startup_failed()
                return

        show = False
        if not self.client.registered:
            if self._disconnected_at is None:
                show = now - self._started_at > STARTUP_GRACE_SECONDS
            else:
                show = now - self._disconnected_at > TAB_GRACE_SECONDS
        elif not self.client.tab_connected and self._no_tab_since:
            show = now - self._no_tab_since > self._tab_grace
        if show and self.client.registered:
            # Pairing codes expire; keep the one on display usable.
            self.ensure_pairing_code()
        self._window.set_wanted(show)

    def _startup_failed(self) -> None:
        self._failed = True
        self._timer.stop()
        try:
            check_plugin(self.comfy_url, timeout=3)
            message = (
                f"ComfyUI at {self.comfy_url} is reachable but the AYON "
                "bridge didn't accept the connection. Check the ComfyUI "
                "console for errors."
            )
        except BridgeError as exc:
            message = str(exc)
        log.error("Unable to connect to ComfyUI: %s", message)
        QtWidgets.QMessageBox.critical(
            None,
            "AYON - ComfyUI",
            f"Unable to connect to ComfyUI.\n\n{message}",
        )
        self.shutdown()

    # --- client events (bridge thread -> Qt) ------------------------------

    def _on_client_event(self, event: str, data: dict) -> None:
        self._sig_event.emit(event, data)

    def _handle_event(self, event: str, data: Any) -> None:  # noqa: ANN401
        if self._shutting_down or self._failed:
            return
        now = time.monotonic()
        if event == "connected":
            first = not self._ever_connected
            self._ever_connected = True
            self._disconnected_at = None
            if data.get("tab_connected"):
                self._tab_connected(first_connection=first)
            else:
                self._no_tab_since = now
                self._tab_grace = (
                    TAB_GRACE_SECONDS
                    if first
                    else TAB_GRACE_AFTER_RECONNECT_SECONDS
                )
            if first:
                if self._open_browser:
                    self.open_tab()
                else:
                    self.new_pairing_code()
                    self._window.set_wanted(True)
        elif event == "disconnected":
            self._disconnected_at = now
            # A restarted ComfyUI forgot the pairing codes it handed out.
            self._forget_pairing_code()
            if self._process_exited():
                log.info("ComfyUI exited, ending the AYON session.")
                self.shutdown()
                return
        elif event == "tab_connected":
            self._tab_connected(first_connection=False)
        elif event == "tab_disconnected":
            self._no_tab_since = now
            self._tab_grace = TAB_GRACE_SECONDS
        elif event == "rejected":
            self._failed = True
            self._timer.stop()
            QtWidgets.QMessageBox.critical(
                None,
                "AYON - ComfyUI",
                "ComfyUI refused the AYON session.\n\n"
                f"{data.get('reason') or 'No reason given.'}",
            )
            self.shutdown()
            return
        self._update_state()
        self._window.update_view()

    def _tab_connected(self, *, first_connection: bool) -> None:  # noqa: ARG002
        self._no_tab_since = None
        self._forget_pairing_code()
        self._window.set_wanted(False)
        self._send_session_info()
        if not self._had_tab:
            self._had_tab = True
            if self._on_first_tab is not None:
                self._run_callable(self._on_first_tab)

    def _on_task_changed(self, *_args: Any) -> None:  # noqa: ANN401
        self.client.info = get_session_info()
        self._send_session_info()

    def _send_session_info(self) -> None:
        """Show the current AYON context in the tab's AYON panel.

        Doesn't wait for the tab, so a slow tab never blocks the Qt thread.
        """
        try:
            info = get_session_info()
            self.client.info = info
            future = self.client.call_nowait("setSessionInfo", info)
        except Exception:  # noqa: BLE001
            log.debug("Unable to send session info", exc_info=True)
            return

        def _log_failure(done: concurrent.futures.Future) -> None:
            if not done.cancelled() and done.exception() is not None:
                log.debug("Unable to send session info: %s", done.exception())

        future.add_done_callback(_log_failure)

    # --- requests from the tab (bridge worker thread) ---------------------

    def run_in_main_thread(self, func: Callable[[], Any]) -> None:
        """Run `func` on the Qt main thread, from any thread.

        Doesn't wait for it to run. Tab request handlers run on a worker
        thread; use this for anything that touches Qt or host state, and
        answer the tab right away.
        """
        self._sig_call.emit(func)

    def _run_callable(self, func: Callable[[], Any]) -> None:
        try:
            func()
        except Exception:
            log.exception("Error while running %s", func)

    def _handle_request_tool(self, params: dict) -> str:
        tool_name = params.get("tool_name")
        if tool_name not in TOOL_NAMES:
            msg = f"Unknown AYON tool: {tool_name!r}"
            raise ValueError(msg)
        # Acknowledge right away; the tool opens on the Qt main thread.
        self.run_in_main_thread(partial(show_tool_by_name, tool_name))
        return f"{tool_name} scheduled"

    def _handle_request_save(self, params: dict) -> str:  # noqa: ARG002
        self.run_in_main_thread(save_current_workfile)
        return "save workfile scheduled"

    def _handle_ping(self, params: dict) -> str:
        return str(params.get("message", "pong"))


class SessionWindow(QtWidgets.QWidget):
    """Explains why the session has no ComfyUI tab, and how to fix it."""

    def __init__(self, bridge: ComfyUIBridge) -> None:
        super().__init__(None)
        self._bridge = bridge
        self._wanted = False
        # Closed by the artist: stay hidden until the situation changes.
        self._dismissed = False
        self.setWindowTitle("AYON - ComfyUI")
        self.setMinimumWidth(460)
        try:
            from ayon_core import resources, style  # noqa: PLC0415

            self.setStyleSheet(style.load_stylesheet())
            self.setWindowIcon(
                QtGui.QIcon(resources.get_ayon_icon_filepath())
            )
        except Exception:  # noqa: BLE001
            log.debug("Unable to apply AYON style", exc_info=True)

        self._status = QtWidgets.QLabel(self)
        self._status.setWordWrap(True)
        self._details = QtWidgets.QLabel(self)
        self._details.setWordWrap(True)
        self._details.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )

        self._code_label = QtWidgets.QLabel("Pairing code:", self)
        self._code = QtWidgets.QLineEdit(self)
        self._code.setReadOnly(True)
        self._link_label = QtWidgets.QLabel("Link:", self)
        self._link = QtWidgets.QLineEdit(self)
        self._link.setReadOnly(True)

        pairing = QtWidgets.QGridLayout()
        pairing.addWidget(self._code_label, 0, 0)
        pairing.addWidget(self._code, 0, 1)
        pairing.addWidget(self._link_label, 1, 0)
        pairing.addWidget(self._link, 1, 1)

        self._open_btn = QtWidgets.QPushButton("Open ComfyUI tab", self)
        self._open_btn.clicked.connect(bridge.open_tab)
        quit_btn = QtWidgets.QPushButton("Quit AYON session", self)
        quit_btn.clicked.connect(bridge.shutdown)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._open_btn)
        buttons.addWidget(quit_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._status)
        layout.addWidget(self._details)
        layout.addLayout(pairing)
        layout.addLayout(buttons)

    def set_wanted(self, wanted: bool) -> None:  # noqa: FBT001
        """Show or hide the window, keeping it up to date."""
        if not wanted:
            self._dismissed = False
        if wanted == self._wanted:
            if wanted and self.isVisible():
                self.update_view()
            return
        self._wanted = wanted
        if wanted and not self._dismissed:
            if self._bridge.client.registered:
                self._bridge.ensure_pairing_code()
            self.update_view()
            self.show()
            self.raise_()
            self.activateWindow()
        elif not wanted:
            self.hide()

    def update_view(self) -> None:
        bridge = self._bridge
        self._status.setText(bridge.status_text())
        info = bridge.client.info
        context = " / ".join(
            value
            for value in (
                info.get("project"), info.get("folder"), info.get("task")
            )
            if value
        )
        self._details.setText(
            f"ComfyUI: {bridge.comfy_url}\nAYON context: {context or '-'}"
        )
        registered = bridge.client.registered
        has_code = registered and bool(bridge.pairing_code)
        for widget in (
            self._code_label, self._code, self._link_label, self._link
        ):
            widget.setVisible(has_code)
        self._code.setText(bridge.pairing_code)
        self._link.setText(bridge.pairing_url)
        self._open_btn.setEnabled(registered)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        # Closing the window only hides it; the session keeps running.
        if self._wanted:
            self._dismissed = True
        super().closeEvent(event)
