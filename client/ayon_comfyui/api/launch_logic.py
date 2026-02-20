"""Install host.

To be launched from launch_script.py.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from textwrap import dedent
from threading import Thread
from traceback import format_tb, print_tb

from ayon_core.lib import env_value_to_bool
from ayon_core.pipeline import get_current_project_name, install_host
from ayon_core.tools.utils import get_ayon_qt_app
from ayon_core.tools.utils.dialogs import show_message_dialog

from ayon_comfyui.api.deduce_python import (
    deduce_default_python_executable,
    python_setup_venv_with_depends,
    venv_check_existence,
    venv_get_python,
)
from ayon_comfyui.api.profile_selector.local_profile_dialog import (
    LocalProfileDialog,
)
from ayon_comfyui.api.qt_rpc import QRPCManager
from ayon_comfyui.parse_settings import ComfyLocalSettings

logging.basicConfig(force=True, stream=sys.stdout, level=logging.DEBUG)
log = logging.getLogger("ayon_comfyui")


def log_to_file(msg, err: BaseException = None):
    fname = os.path.expanduser("~\\Desktop\\comfy_launchlogic_log.txt")
    with open(fname, "a") as file:
        errs = [err, type(err)] if err is not None else []
        print(msg, *errs, file=file, flush=True)
        if err:
            print_tb(err.__traceback__, file=file)


def safe_excepthook(*args):
    traceback.print_exception(*args)


def adjust_consts_comfyui_plugin(plugin_path: Path) -> None:
    """Adjust settings for comfyui plugin."""
    settings, _ = ComfyLocalSettings.pull_committed_settings()

    javascript = f'export const AYON_WEBUI_PORT = "{settings.port_webui}";'
    python = f"AYON_BACKEND_PORT = {settings.port_backend}"

    py_file = plugin_path / "ayon_menu" / "consts.py"
    js_file = plugin_path / "ayon_menu" / "js" / "lib" / "consts.js"

    # TODO: We really shouldn't be updating files inside the packaged plugin,
    #  but for now this is the easiest way to get the settings in there
    #  without having to do some sort of IPC or environment variable passing
    #  to comfyUI, which would be more robust but also more work to implement.
    with open(py_file, "w", encoding="utf-8") as py_f:
        py_f.write(python)

    with open(js_file, "w", encoding="utf-8") as js_f:
        js_f.write(javascript)


def _subproc_launch_ComfyUI() -> subprocess.Popen:
    """Launch local profile."""
    # We really need to fetch most of this from settings...
    fname = os.path.expanduser("~\\Desktop\\comfy_launchlogic_log.txt")

    settings, profile = ComfyLocalSettings.pull_committed_settings()

    # CHECK IF WINDOWS PORTABLE TO TARGET THE RIGHT PYTHON PATH
    # TODO(@sas): maybe allow for launch using ayon_console.
    # This would suck, though.
    # The better solution would be to understand which python is present
    # by subprocessing launching "python" / "python3" and then doing
    # sys.executable() to get the path
    # if nothing works, quit while we are ahead

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

    # TEST IMPLEMENTATION OF:
    # TODO(@sas): add an option for
    # letting the user manage a python environment themselves

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
                show_message_dialog(
                    "Virtual environment error",
                    (
                        "Couldn't instantiate virtual environment using:\n"
                        f"python: {pythonpath!s}\n"
                        f"goal environment folder: {env_path!s}\n"
                        f"requirements: {requirements!s}\n\n"
                        f"Error: {e}\n\n"
                        "Process will now shut down."
                    ),
                    "critical",
                )
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

    log_to_file(comfy_main_location)

    # win only for now ?
    args = [
        *shell_args,
        pythonpath,
        "-s",
        comfy_main_location,
        # "--disable-auto-launch",  # Prevents browser from starting
        *profile.launch_args,
    ]

    # 8 space | 2 tabs indent to sit below custom nodes
    path_indent = " " * 8

    # simulate paths comin in from settings
    # paths = [R"C:\Users\sas.vangulik\Documents\comfy_nodes_ayon"]
    paths = profile.extra_node_dirs or []

    # TODO(@Sas): Adress following
    # There needs to be a setting for this so we can point to
    # a development folder
    include_content = not profile.omit_packaged_plugin

    if include_content:
        import ayon_comfyui as comfy_plugin

        comfy_plugin_path = (
            Path(comfy_plugin.__file__).parent / "_comfyui_plugin"
        )
        # inject settings
        adjust_consts_comfyui_plugin(comfy_plugin_path)

        paths.append(str(comfy_plugin_path))

    paths = ["\n" + path_indent + p.replace("\\", "/") for p in paths]

    yaml_folder = profile.base_folder.replace("\\", "/")
    yaml = dedent(f"""
            ayon_config:
                base_path: "{yaml_folder}"
                custom_nodes: |""")

    yaml += "".join(paths)

    log_to_file(yaml)

    proc = None
    # Generate temporary file,
    # dont delete tempfile otherwise comfy gets confused
    tmp_path = ""
    with tempfile.TemporaryFile(
        "w", encoding="utf-8", suffix=".txt", delete=False
    ) as tmp:
        tmp.write(yaml)
        args.extend(("--extra-model-paths-config", tmp.name))
        tmp_path = tmp.name

    with open(fname, "a") as file:
        print(*args, sep="\n", file=file)
        print(yaml, file=file)

    log_to_file(args)
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
    buffer_time = 5

    def _defer_delete_tmp(path: str, hold_time: float) -> None:
        time.sleep(hold_time)
        os.remove(path)

    Thread(
        target=_defer_delete_tmp, args={tmp_path, buffer_time}, daemon=True
    ).start()

    return proc


def main(*subproc_args):
    """Local launch."""
    fname = os.path.expanduser("~\\Desktop\\comfy_launchlogic_log.txt")
    with open(fname, "w") as file:
        print(*subproc_args, sep="\n", file=file)

    # sys.excepthook = safe_excepthook

    from ayon_comfyui.api import ComfyUIHost

    host = ComfyUIHost()
    install_host(host)

    with open(fname, "a") as file:
        print("Installed host", file=file)

    app = get_ayon_qt_app()
    app.setQuitOnLastWindowClosed(False)

    with open(fname, "a") as file:
        print("got QT app", file=file)

    env_workfiles_on_launch = os.getenv(
        "AYON_COMFYUI_WORKFILES_ON_LAUNCH", "1"
    )
    workfiles_on_launch = env_value_to_bool(
        "AYON_COMFYUI_WORKFILES_ON_LAUNCH",
        value=env_workfiles_on_launch,
        default=True,
    )

    try:
        project_name = get_current_project_name() or None

        settings = ComfyLocalSettings(project_name=project_name)

        profile_selector = LocalProfileDialog()
        # ensure project specific settings
        profile_selector.populate_list(settings)

        # block and get profile first.
        # Profile will also commit results to
        profile_selector.exec()

        profile = profile_selector.profile
    except BaseException as e:
        with open(fname, "a") as file:
            print(
                "error during profile dialog",
                e,
                "\n",
                "\n".join(format_tb(e.__traceback__)),
                file=file,
            )

    # sys.excepthook = safe_excepthook

    if not profile:
        show_message_dialog(
            title="No profile selected!",
            message="You have not selected a profile.\nClosing...",
            level="warning",
        )
        sys.exit(0)

    with open(fname, "a") as file:
        print("workfiles on launch:", workfiles_on_launch, file=file)

    try:
        # Launch comfyUI
        _subproc_launch_ComfyUI()
    except BaseException as e:
        from traceback import print_tb

        with open(fname, "a") as file:
            print("problems launching comfyUI", type(e), e, file=file)
            print_tb(e.__traceback__, file=file)
    # Somehow wrap a connection here.

    if workfiles_on_launch:
        pass
        # Crashes.
        # rpc.show_tool_by_name("workfiles", save=False)
        # with open(fname, "a") as file:
        #    print("Showed hostfiles", file=file)
    # Launch ComfyUI if the connection isn't external.

    # ComfyUI launch procedure

    with open(fname, "a") as file:
        print("Creating QRPCmanager", file=file)

    try:
        rpcman = QRPCManager(
            parent=app,
            client_hostname="localhost",
            client_port=settings.port_backend,
            server_port=settings.port_webui,
            use_https=False,
        )
        with open(fname, "a") as file:
            print("created rpc manager", file=file)
        rpcman.start_server()
        with open(fname, "a") as file:
            print("called start_server", file=file)
    except BaseException as e:
        from traceback import print_tb

        with open(fname, "a") as file:
            print("problem starting server", type(e), e, file=file)
            print_tb(e.__traceback__, file=file)
    # Launch Qt Thread
    log_to_file("launching qt thread")

    try:
        ret = app.exec_()
    except BaseException as e:
        from traceback import print_tb

        with open(fname, "a") as file:
            print("problem keeping qt thread alive", type(e), e, file=file)
            print_tb(e.__traceback__, file=file)
    # terminate connection after Qt Thread.

    sys.exit(ret)
