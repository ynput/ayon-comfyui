"""Install host.

To be launched from launch_script.py.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from textwrap import dedent
from threading import Thread
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from ayon_core.lib import env_value_to_bool
from ayon_core.pipeline import (
    get_current_project_name,
    install_host,
    registered_host,
)
from ayon_core.tools.utils import get_ayon_qt_app
from ayon_core.tools.utils.dialogs import show_message_dialog, ScrollMessageBox
from qtpy import QtCore, QtWidgets

if TYPE_CHECKING:
    from qtpy.QtWidgets import QApplication

from ayon_comfyui.api.bridge import ComfyUIBridge
from ayon_comfyui.api.bridge_client import (
    BridgeError,
    check_plugin,
    check_url,
    is_unencrypted_remote,
)
from ayon_comfyui.api.consts import LOG_LEVEL
from ayon_comfyui.api.deduce_python import (
    deduce_default_python_executable,
    python_setup_venv_with_depends,
    venv_check_existence,
    venv_get_python,
)
from ayon_comfyui.api.profile_selector import (
    ProfileDialog,
    ProfileTypeEnum,
)
from ayon_comfyui.settings_util import (
    ComfyLocalSettings,
    ComfyRemoteSettings,
)

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")

# Seconds to wait for ComfyUI to become reachable. A locally launched
# ComfyUI may install requirements or load many custom nodes first.
LOCAL_STARTUP_TIMEOUT = 600.0
REMOTE_STARTUP_TIMEOUT = 30.0


def safe_excepthook(*args):  # noqa: ANN201, ANN002, D103
    traceback.print_exception(*args)


def _subproc_launch_ComfyUI() -> subprocess.Popen:
    """Launch local profile.

    Returns:
        Popen ComfyUI subprocess.
    """
    settings, profile = ComfyLocalSettings.pull_committed_settings()

    # CHECK IF WINDOWS PORTABLE TO TARGET THE RIGHT PYTHON PATH

    pythonpath = deduce_default_python_executable()

    # Get from settings
    if profile.using_custom_python:
        pythonpath = profile.custom_python_path
    elif profile.is_windows_portable and profile.current_os == "Windows":
        # THEY MISSPELLED EMBEDDED...
        # Traverse folder and look for python.exe in the future.
        pythonpath = (
            Path(profile.base_folder).parent / "python_embeded" / "python.exe"
        )

    # let the user manage a python environment themselves
    # TODO(@sas): Look into astral uv as an alternative.

    if profile.using_managed_venv and not (
        profile.is_windows_portable and profile.current_os == "Windows"
    ):
        env_folder_name = f"{'_'.join(profile.name.split())}_env"

        import ayon_comfyui as comfy_plugin

        # Go to AYON / addons_resources
        envs_root = (
            Path(comfy_plugin.__file__).parent.parent.parent.parent
            / "addons_resources"
            / "comfyui_envs"
        )

        env_path = envs_root / env_folder_name
        env_path.mkdir(parents=True, exist_ok=True)

        requirements = Path(profile.base_folder) / "requirements.txt"

        if not venv_check_existence(env_path):
            try:
                pythonpath = python_setup_venv_with_depends(
                    pythonpath, env_path, requirements
                )
            except ChildProcessError as e:

                messages = [
                    "<h1>Couldn't instantiate virtual environment</h1>",
                    "Using:"
                    f"python: <code>{pythonpath!s}</code>",
                    f"target environment folder: <code>{env_path!s}</code>",
                    f"requirements: <code>{requirements!s}</code>",
                    "<h3>Error:</h3>",
                    str(e),
                    "Process will now shut down.",
                ]
                dialog = ScrollMessageBox(
                    icon=QtWidgets.QMessageBox.Icon.Critical,
                    title="Virtual environment error",
                    messages=messages,
                )
                dialog.exec()
                return None
        else:
            pythonpath = venv_get_python(env_path)

    # This needs to be tested on different platforms.
    shell_args = []
    creation_flags = {}

    if sys.platform == "win32":
        shell_args = [
            "powershell",
            "-NoExit",  # NoExit prevents window closing after error
            "-ExecutionPolicy",
            "Bypass",
            "&",
        ]
        creation_flags = {"creationflags": subprocess.CREATE_NEW_CONSOLE}
    elif sys.platform == "linux":
        shell_args = [
            "x-terminal-emulator",
            "-e",
        ]

    elif sys.platform == "darwin":
        shell_args = [
            "open",
            "-a",
            "Terminal",
        ]

    comfy_main_location = profile.base_folder
    if not comfy_main_location.endswith("main.py"):
        main_path = Path(comfy_main_location) / "main.py"
        comfy_main_location = str(main_path)

    log.info("Comfy Folder:")
    log.info(comfy_main_location)

    # win only for now ?
    args = [
        *shell_args,
        pythonpath,
        "-s",
        comfy_main_location,
        "--disable-auto-launch",  # Prevents browser from starting
        "--port",
        f"{profile.comfy_port}",  # port needs to be string in arg list
        *profile.launch_args,
    ]

    yaml_folder = Path(profile.base_folder).as_posix()
    yaml = dedent(f"""
            ayon_config:
                base_path: "{yaml_folder}"
            """)

    # Construct yaml within profile.
    yaml += profile.get_customfolders_yaml

    proc = None
    # Generate temporary file,
    # dont delete tempfile otherwise comfy gets confused
    tmp_path = ""
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt", delete=False
    ) as tmp:
        tmp.write(yaml)
        args.extend(("--extra-model-paths-config", tmp.name))
        tmp_path = tmp.name

    log.info(
        f"Launching ComfyUI locally with YAML comfig:"  # noqa: G004
        f"\n{yaml}\n\nand arguments:\n{args}"
    )

    # Cleanup env
    delim = ":"
    if sys.platform == "win32":
        delim = ";"

    envdict: dict[str, str] = os.environ
    envdict["PATH"] = delim.join(
        [
            pth
            for pth in envdict["PATH"].split(delim)
            if "AYON" not in pth or "Ayon" not in pth or "ayon" not in pth
        ]
    )
    envdict["PYTHONPATH"] = profile.base_folder

    # ideally temporary file should be deleted after some scheduled interval
    proc = subprocess.Popen(
        args, cwd=profile.base_folder, **creation_flags, env=envdict
    )

    # time buffer closing of tempfile, allowing it to be read by comfyUI
    buffer_time = 20.0

    def _defer_delete_tmp(*, path: str = "", hold_time: float = 10.0) -> None:
        time.sleep(hold_time)
        os.remove(path)

    Thread(
        target=_defer_delete_tmp,
        kwargs={"path": tmp_path, "hold_time": buffer_time},
        daemon=True,
    ).start()

    return proc


def main(*args):
    """Main designed to accomodate both local and remote launch profiles."""
    sys.excepthook = safe_excepthook

    from ayon_comfyui.api import ComfyUIHost

    host = ComfyUIHost()
    install_host(host)

    log.info("Installed host")

    app = get_ayon_qt_app()
    app.setQuitOnLastWindowClosed(False)

    log.info("got QT app")

    try:
        project_name = get_current_project_name() or None

        profile_selector = ProfileDialog()
        # initialize local/remote settings
        profile_selector.populate_list(project_name)

        profile_selector.exec()
    except BaseException:  # noqa: BLE001
        log.debug("Error during profile dialog", exc_info=True)

    if (res := profile_selector.dialog_result) == ProfileTypeEnum.UNDECIDED:
        show_message_dialog(
            title="No profile selected!",
            message="You have not selected a profile.\nClosing...",
            level="warning",
        )
        sys.exit(0)
    elif res == ProfileTypeEnum.LOCAL:
        settings, profile = (
            profile_selector.settings_local.pull_committed_settings()
        )
        launch_local(app, settings, profile)
    elif res == ProfileTypeEnum.REMOTE:
        settings, profile = (
            profile_selector.settings_remote.pull_committed_settings()
        )
        launch_remote(app, settings, profile)

    # Launch Qt Thread
    log.info("Launching qt thread")

    ret = 1
    try:
        ret = app.exec_()
    except BaseException:  # noqa: BLE001
        log.debug("Problems keeping thread alive", exc_info=True)

    # Qt may crash tearing down windows that are still alive (e.g. AYON
    # tools that were left open) during `os._exit`; destroy them first.
    _destroy_windows(app)

    # The bridge already disconnected and stopped ComfyUI (if we launched
    # it) before the Qt loop ended; don't let leftover threads block exit.

    # sys.exit(ret)
    os._exit(ret)


def _destroy_windows(app: QApplication) -> None:
    for widget in QtWidgets.QApplication.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(
        None, QtCore.QEvent.Type.DeferredDelete
    )
    app.processEvents()


def _open_last_workfile() -> None:
    """Open the workfile AYON asked to open on launch, if any."""
    workfile_path = os.getenv("AYON_LAST_WORKFILE")
    if not workfile_path or not env_value_to_bool("AVALON_OPEN_LAST_WORKFILE"):
        return
    if not os.path.isfile(workfile_path):
        log.info("Last workfile doesn't exist (yet): %s", workfile_path)
        return
    log.info("Opening last workfile: %s", workfile_path)
    try:
        registered_host().open_workfile(workfile_path)
    except Exception as exc:
        log.exception("Failed to open last workfile: %s", workfile_path)
        show_message_dialog(
            title="AYON - ComfyUI",
            message=f"Failed to open workfile:\n{workfile_path}\n\n{exc}",
            level="critical",
        )


def _probe_comfyui(url: str) -> tuple[str, str]:
    """Check what, if anything, already serves the ComfyUI URL.

    Returns:
        ("free", "") when nothing listens on its port, ("ayon", "") for a
        ComfyUI with a compatible AYON plugin, otherwise ("busy", reason).
    """
    parts = urlsplit(url)
    try:
        socket.create_connection(
            (parts.hostname or "127.0.0.1", parts.port or 80), timeout=1
        ).close()
    except OSError:
        return "free", ""
    try:
        check_plugin(url, timeout=3)
    except BridgeError as exc:
        return "busy", str(exc)
    return "ayon", ""


def _fail(message: str) -> None:
    log.error(message)
    show_message_dialog(
        title="AYON - ComfyUI", message=message, level="critical"
    )
    sys.exit(1)


def launch_local(
    app: QApplication,
    settings: ComfyLocalSettings,  # noqa: ARG001
    profile: ComfyLocalSettings.ComfyLocalProfile,
) -> None:
    """Launch ComfyUI as a subprocess and connect to it."""
    url = profile.comfy_local_url
    try:
        check_url(url)
    except BridgeError as exc:
        _fail(str(exc))
    process = None
    state, reason = _probe_comfyui(url)
    if state == "ayon":
        answer = QtWidgets.QMessageBox.question(
            None,
            "AYON - ComfyUI",
            f"ComfyUI is already running at {url}.\n\n"
            "Use the running ComfyUI for this AYON session? AYON won't "
            "stop it when the session ends.",
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            sys.exit(0)
        log.info("Using the ComfyUI already running at %s", url)
    elif state == "busy":
        _fail(
            f"Port {urlsplit(url).port} is already in use, so ComfyUI "
            f"can't start at {url}.\n\n{reason}\n\n"
            "Close the program using that port, or change the ComfyUI port "
            f"of the '{profile.name}' launch profile."
        )
    else:
        try:
            process = _subproc_launch_ComfyUI()
        except Exception as exc:  # noqa: BLE001
            log.exception("Problems launching ComfyUI")
            _fail(f"Unable to launch ComfyUI:\n\n{exc}")
        if process is None:
            sys.exit(1)

    bridge = ComfyUIBridge(
        url,
        process=process,
        open_browser=True,
        startup_timeout=LOCAL_STARTUP_TIMEOUT,
        on_first_tab=_open_last_workfile,
        parent=app,
    )
    bridge.start()


def launch_remote(
    app: QApplication,
    settings: ComfyRemoteSettings,  # noqa: ARG001
    profile: ComfyRemoteSettings.ComfyRemoteProfile,
) -> None:
    """Connect to a ComfyUI server that is already running."""
    url = profile.comfy_url
    try:
        check_plugin(url)
    except BridgeError as exc:
        _fail(str(exc))
    if is_unencrypted_remote(url):
        log.warning(
            "ComfyUI at %s is reached over plain http: the AYON session "
            "secret and the workflows travel unencrypted. Prefer https for "
            "a ComfyUI on another machine.",
            url,
        )

    bridge = ComfyUIBridge(
        url,
        open_browser=profile.open_browser,
        startup_timeout=REMOTE_STARTUP_TIMEOUT,
        on_first_tab=_open_last_workfile,
        parent=app,
    )
    bridge.start()
