"""Make loaded files available to ComfyUI: upload, or reference by path.

Uploading into ComfyUI's input directory is the default: it works wherever
ComfyUI runs. Referencing files in place is opt-in per load. It avoids
copying large plates and follows files that change in place (hero
versions), but only when the ComfyUI server can read the files under its
own mapping of the AYON roots (see `_comfyui_plugin/ayon_menu/paths.py`).
When it can't, files are uploaded after all.
"""

from __future__ import annotations

import json
import logging
import os

from ayon_comfyui.api.bridge_client import BridgeError
from ayon_comfyui.api.comfy_http import ComfyHttp
from ayon_comfyui.api.upload_util import upload_input_images

log = logging.getLogger(__name__)

#: Environment variable the ComfyUI plugin reads its AYON roots from.
ROOTS_ENV = "AYON_COMFYUI_ROOTS"


def site_roots(project_name: str) -> dict[str, str]:
    """Return the AYON roots of a project on this machine."""
    from ayon_core.pipeline import Anatomy  # noqa: PLC0415

    anatomy = Anatomy(project_name)
    return {name: str(root) for name, root in anatomy.roots.items()}


def export_site_roots(project_name: str | None) -> None:
    """Let a ComfyUI that AYON launches resolve this site's AYON roots.

    A local ComfyUI inherits AYON's environment, and runs on the same
    machine, so the same roots apply. An explicit `AYON_COMFYUI_ROOTS`
    wins.
    """
    if not project_name or os.environ.get(ROOTS_ENV):
        return
    try:
        roots = site_roots(project_name)
    except Exception:  # noqa: BLE001
        log.debug("Unable to get the project roots", exc_info=True)
        return
    if roots:
        os.environ[ROOTS_ENV] = json.dumps(roots)


def rootless_paths(
    project_name: str, filepaths: list[str]
) -> list[str] | None:
    """Return `filepaths` as AYON rootless paths, or None if one isn't."""
    from ayon_core.pipeline import Anatomy  # noqa: PLC0415

    anatomy = Anatomy(project_name)
    result = []
    for path in filepaths:
        found, rootless = anatomy.find_root_template_from_path(path)
        if not found:
            return None
        result.append(rootless.replace("\\", "/"))
    return result


def server_can_read(comfy_url: str, rootless: list[str]) -> bool:
    """Return whether the ComfyUI server can read all `rootless` paths."""
    try:
        answer = ComfyHttp(comfy_url).http_json(
            "POST", "/ayon/paths/check", json={"paths": rootless}
        )
    except BridgeError as exc:
        log.info("ComfyUI can't check paths (%s).", exc)
        return False
    exists = answer.get("exists") if isinstance(answer, dict) else None
    return (
        isinstance(exists, list)
        and len(exists) == len(rootless)
        and all(exists)
    )


def container_files(
    comfy_url: str,
    project_name: str,
    filepaths: list[str],
    *,
    subfolder: str,
    reference: bool = False,
) -> dict:
    """Return the container's file entries for `filepaths`.

    Returns:
        `{"path_reference": {"files": [...]}, "image_upload_info": []}`
        when referencing by path, else `{"path_reference": None,
        "image_upload_info": [...]}` after uploading the files.
    """
    if reference:
        rootless = rootless_paths(project_name, filepaths)
        if rootless is None:
            log.warning(
                "The files aren't below an AYON root of '%s'; uploading "
                "them to ComfyUI instead of referencing them.", project_name,
            )
        elif server_can_read(comfy_url, rootless):
            log.info("Referencing %s file(s) on ComfyUI.", len(rootless))
            return {
                "path_reference": {"files": rootless},
                "image_upload_info": [],
            }
        else:
            log.warning(
                "ComfyUI can't read the files at their AYON root (its AYON "
                "roots are not configured for them); uploading instead."
            )
    return {
        "path_reference": None,
        "image_upload_info": upload_input_images(
            filepaths, comfy_url, subfolder=subfolder
        ),
    }
