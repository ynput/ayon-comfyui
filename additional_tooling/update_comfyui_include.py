"""Copy plugins to: client/ayon_comfyui/_comfyui_plugin/comfyui_ayon.

Whole file tree is taken along, but not all files are taken with.
"""

import os
from pathlib import Path
from shutil import copy2


def include_ayon_comfyui_plugin(base_path: str):
    COMFY_BASE = Path(base_path)
    DESTINATION = (
        Path(__file__).parent.parent
        / "client"
        / "ayon_comfyui"
        / "_comfyui_plugin"
    )
    FILES_ALLOWED = {".py", ".js", ".md", "LICENSE"}

    for dirpath, _, filenames in os.walk(COMFY_BASE):
        relative_path = Path(dirpath).relative_to(COMFY_BASE)
        if any(
            str(pth).startswith((".", "__")) and len(str(pth)) > 1
            for pth in (relative_path.parts)
        ):
            # no .vscode, .git, etc.
            continue

        filter_files = [
            f for f in filenames if any(allow in f for allow in FILES_ALLOWED)
        ]
        destination_dir = DESTINATION.joinpath(relative_path)
        destination_dir.mkdir(parents=True, exist_ok=True)
        from_files = [Path(dirpath) / file for file in filter_files]
        to_files = [destination_dir / file for file in filter_files]

        for from_file, to_file in zip(from_files, to_files):
            copy2(from_file, to_file)
