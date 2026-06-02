"""Tools for deducing things about python.

In this module, we mainly use 'python' and 'python3'.
Use of 'py' alias can be a bit fickle.

TODO(@sas): Check python version before enabling note adding
as this is a python 3.11 feature.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def deduce_default_python_executable() -> str | None:
    """Deduce default python executable location.

    This is done by attempt at subprocessing
    python/python3 depending on platform.

    Returns:
        Path to python executable or None if not found.
    """
    script = "import sys;print(sys.executable)"

    python_name = "python"
    if sys.platform != "win32":
        python_name += "3"  # python3

    try:
        proc = subprocess.Popen(
            [python_name, "-c", script],
            stdout=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        return None

    out, _ = proc.communicate()

    return out.strip()


def deduce_default_python_version() -> str | None:
    """Deduce default python executable version.

    This is done by attempt at subprocessing
    python/python3 depending on platform.

    Returns:
        Python version as '3.X.X' or None if not found.
    """
    script = (
        "import sys;"
        "print(sys.version_info.major,sys.version_info.minor,sys.version_info.micro,sep='.')"
    )

    python_name = "python"
    if sys.platform != "win32":
        python_name += "3"  # python3

    try:
        proc = subprocess.Popen(
            [python_name, "-c", script],
            stdout=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        return None

    out, _ = proc.communicate()

    return out.strip()


def venv_get_python(environment_path: Path) -> Path:
    """Returns path to python executable in environment.

    Warning: Does not check if the environment exists / is valid.
    For that, use `venv_check_existence`.
    """
    bin_directory = "bin"

    python_name = "python"
    if sys.platform == "win32":
        python_name += ".exe"
        bin_directory = "Scripts"

    return environment_path / bin_directory / python_name


def venv_check_existence(environment_path: Path) -> bool:
    """Returns whether a valid python environment exists at location.

    Utility function to check if an environment has previously been made.
    It is kind of naive, it only checks if the environment has been set up,
    not if it actually works.
    """
    py_path = venv_get_python(environment_path)
    bin_path = py_path.parent

    asserts = [
        environment_path.exists(),
        bin_path.exists(),
        py_path.exists(),
    ]

    return all(asserts)


def format_error_message(
    stderr: str,
    message: str = "Something went wrong.",
    args: list[str | Path] | None = None
) -> ChildProcessError:
    code_block_style = (
        "background: #1e1e1e;"
        "color: #dcdcdc;"
        "white-space: pre-wrap;"  # allow word wrapping in code blocks
    )

    text = f"<p>{message}</p>"
    if args:
        text += "<p>Args:</p>"
        text += f"<pre style='{code_block_style}'>{args}</pre>"
    if stderr:
        text += "<p>Output:</p>"
        text += f"<pre style='{code_block_style}'>{stderr}</pre>"

    return ChildProcessError(text)


def pip_install_requirements(
    python_exec_path: Path, requirements_path: Path
) -> None:
    """Uses pip to install/update modules from a requirements file.

    This process should go pretty quick if requirements are already met.

    Raises ChildProcessError if somehow, packages failed to install.
    """
    args = [python_exec_path, "-m", "pip", "install", "-r", requirements_path]

    delim = ":"
    if sys.platform == "win32":
        delim = ";"

    envdict: dict[str, str] = os.environ._data  # noqa: SLF001
    envdict["PATH"] = delim.join(
        [
            pth
            for pth in envdict["PATH"].split(delim)
            if "AYON" not in pth or "Ayon" not in pth or "ayon" not in pth
        ]
    )
    envdict.pop("PYTHONPATH", None)

    proc = subprocess.Popen(
        args,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    out, err = proc.communicate()
    out, err = out.strip(), err.strip()

    if "Error" in out or "ERROR" in out or "Error" in err or "ERROR" in err:
        error = format_error_message(
            stderr=err,
            message="Failed to install packages from requirements.",
            args=args,
        )
        raise error


def python_setup_venv_with_depends(
    python_exec_path: Path, environment_path: Path, requirements_path: Path
) -> Path:
    """Spawn a virtual environment using venv.

    Because a venv points to a path that could be local, we should carefully
    consider where to place the environment path.
    Then, set it up with requirements.txt

    Returns:
        path to executable within python environment,
        environment_path/Scripts/python(.exe)

    Raises:
        ChildProcessError when failed to set up a virtual environment.
        ChildProcessError from setting up environment and failing.
    """
    # Only do this if there's no venv already.
    if not venv_check_existence(environment_path):
        venv_args = [python_exec_path, "-m", "venv", environment_path]

        proc = subprocess.Popen(
            venv_args,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

        out, err = proc.communicate()
        out, err = out.strip(), err.strip()
        if out or err:
            error = format_error_message(
                stderr=err,
                message="Failed to set up a virtual environment.",
                args=venv_args,
            )
            raise error

    venv_python = venv_get_python(environment_path)

    # Can fail too.
    pip_install_requirements(venv_python, requirements_path)

    return venv_python
