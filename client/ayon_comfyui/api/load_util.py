"""Make loaded files available to ComfyUI: upload, or reference by path.

Uploading into ComfyUI's input directory is the default: it works wherever
ComfyUI runs. Referencing files in place is opt-in per load. It avoids
copying large plates and follows files that change in place (hero
versions), but only when the ComfyUI server can read the files under its
own mapping of the AYON roots (see `_comfyui_plugin/ayon_menu/paths.py`).
When it can't, files are uploaded after all, and the artist is told why.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from typing import TYPE_CHECKING, Any

from ayon_comfyui.api.bridge_client import BridgeError
from ayon_comfyui.api.comfy_http import ComfyHttp
from ayon_comfyui.api.upload_util import upload_input_images

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

#: Environment variable the ComfyUI plugin reads its AYON roots from.
ROOTS_ENV = "AYON_COMFYUI_ROOTS"
#: ...and the project folders below them it may read.
PROJECTS_ENV = "AYON_COMFYUI_PROJECTS"
#: ComfyUI plugin feature for reading files by path.
PATHS_FEATURE = "paths-v1"
#: Why the ComfyUI plugin ignores a root that is a whole drive or share
#: (`WHOLE_DRIVE` in `_comfyui_plugin/ayon_menu/paths.py`).
WHOLE_DRIVE = "whole_drive"


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
        # Only this project's folder below each root (by name and code, as
        # anatomy templates may use either).
        os.environ.setdefault(
            PROJECTS_ENV, json.dumps(sorted(project_folders(project_name)))
        )


def project_folders(project_name: str) -> set[str]:
    """Return the folder names a project may have below a root."""
    folders = {project_name}
    try:
        import ayon_api  # noqa: PLC0415

        project = ayon_api.get_project(project_name, fields={"code"}) or {}
        if project.get("code"):
            folders.add(project["code"])
    except Exception:  # noqa: BLE001
        log.debug("Unable to get the project code", exc_info=True)
    return folders


def session_proof(secret: str) -> str:
    """Return what proves knowledge of the bridge session secret.

    Must match `session_proof` in `_comfyui_plugin/ayon_menu/paths.py`,
    which checks it; the secret itself is never sent over HTTP.
    """
    return hmac.new(
        secret.encode(), b"ayon-paths-check", hashlib.sha256
    ).hexdigest()


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


#: Header the ComfyUI plugin authenticates `/ayon/paths/check` with.
SESSION_HEADER = "X-AYON-Session"
_ROOT_NAME = re.compile(r"^\{root\[([A-Za-z0-9_-]+)\]\}")


def server_read_problem(
    comfy_url: str, rootless: list[str], session_secret: str
) -> str | None:
    """Return why the ComfyUI server can't read all `rootless` paths.

    The check is only answered for AYON sessions registered on the bridge,
    so it is authenticated with this session's secret.

    Returns:
        None when it can read them all.
    """
    try:
        answer = ComfyHttp(comfy_url).http_json(
            "POST",
            "/ayon/paths/check",
            json={"paths": rootless},
            headers={SESSION_HEADER: session_proof(session_secret)},
        )
    except BridgeError as exc:
        return f"ComfyUI couldn't check whether it can read them ({exc})."
    return check_answer_problem(rootless, answer)


def check_answer_problem(rootless: list[str], answer: Any) -> str | None:  # noqa: ANN401
    """Return why a `/ayon/paths/check` answer refuses `rootless`, or None."""
    exists = answer.get("exists") if isinstance(answer, dict) else None
    if not isinstance(exists, list) or len(exists) != len(rootless):
        return "ComfyUI gave an invalid answer when checking the files."
    missing = [path for path, found in zip(rootless, exists) if not found]
    if not missing:
        return None

    roots = answer.get("roots")
    roots = roots if isinstance(roots, list) else []
    ignored = answer.get("ignored_roots")
    ignored = ignored if isinstance(ignored, dict) else {}
    for path in missing:
        match = _ROOT_NAME.match(path)
        name = match.group(1) if match else None
        if name is None or name in roots:
            continue
        refused = ignored.get(name)
        if not isinstance(refused, dict):
            return (
                f"ComfyUI has no AYON root '{name}' (see {ROOTS_ENV} on "
                "that server)."
            )
        if refused.get("reason") == WHOLE_DRIVE:
            return (
                f"ComfyUI ignores its AYON root '{name}' "
                f"({refused.get('path')}): a whole drive or share is only "
                f"used while {PROJECTS_ENV} limits it to project folders. "
                "AYON sets that when it launches ComfyUI; for another "
                "ComfyUI, ask its administrator."
            )
        return f"ComfyUI ignores its AYON root '{name}'."
    return (
        f"ComfyUI can't find {len(missing)} of the {len(rootless)} file(s) "
        "below its AYON roots: they point elsewhere on that server, or "
        f"{PROJECTS_ENV} doesn't include this project."
    )


def _reference_problem(  # noqa: PLR0913
    comfy_url: str,
    project_name: str,
    filepaths: list[str],
    session_secret: str,
    plugin_features: frozenset[str] | None,
) -> tuple[list[str] | None, str | None]:
    """Return the rootless paths to reference, or None and why not."""
    if plugin_features is not None and PATHS_FEATURE not in plugin_features:
        return None, (
            "The AYON plugin on ComfyUI can't read files by path (it is "
            "older than this addon)."
        )
    rootless = rootless_paths(project_name, filepaths)
    if rootless is None:
        return None, (
            f"The files aren't below an AYON root of project "
            f"'{project_name}'."
        )
    problem = server_read_problem(comfy_url, rootless, session_secret)
    if problem:
        return None, problem
    return rootless, None


def _log_fallback(reason: str) -> None:
    log.warning(
        "Uploading the files to ComfyUI instead of referencing them. %s",
        reason,
    )


def container_files(  # noqa: PLR0913
    comfy_url: str,
    project_name: str,
    filepaths: list[str],
    *,
    subfolder: str,
    reference: bool = False,
    session_secret: str = "",
    plugin_features: frozenset[str] | None = None,
    on_fallback: Callable[[str], None] | None = None,
) -> dict:
    """Return the container's file entries for `filepaths`.

    Args:
        comfy_url: The ComfyUI server.
        project_name: The files' project.
        filepaths: The files to load.
        subfolder: The input subfolder to upload to.
        reference: Reference the files in place, when the server can.
        session_secret: This session's bridge secret.
        plugin_features: What the AYON plugin on ComfyUI supports.
        on_fallback: Called with why, when `reference` was asked but the
            files are uploaded instead. Without it that's logged.

    Returns:
        `{"path_reference": {"files": [...]}, "image_upload_info": []}`
        when referencing by path, else `{"path_reference": None,
        "image_upload_info": [...]}` after uploading the files.
    """
    if reference:
        rootless, reason = _reference_problem(
            comfy_url, project_name, filepaths, session_secret,
            plugin_features,
        )
        if rootless is not None:
            log.info("Referencing %s file(s) on ComfyUI.", len(rootless))
            return {
                "path_reference": {"files": rootless},
                "image_upload_info": [],
            }
        (on_fallback or _log_fallback)(reason)
    return {
        "path_reference": None,
        "image_upload_info": upload_input_images(
            filepaths, comfy_url, subfolder=subfolder
        ),
    }
