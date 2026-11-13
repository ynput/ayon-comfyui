"""Resolve AYON rootless paths (`{root[work]}/...`) on the ComfyUI server.

Load nodes normally read files AYON uploaded into ComfyUI's input
directory, which works wherever ComfyUI runs. When the files are reachable
from the ComfyUI server too, AYON can reference them in place instead
(opt-in), which avoids copying large plates and picks up files that change
in place, like hero versions.

The server decides where each AYON root is, so a path from a Windows
workstation can resolve on a Linux server. Configure it with either:

- `AYON_COMFYUI_ROOTS`: a JSON object `{"work": "/mnt/projects", ...}`, or
  the path of a JSON file with that object. AYON sets it to the current
  site's roots when it launches a local ComfyUI.
- `<ComfyUI user directory>/__ayon/roots.json` with the same object.

Without a configured root nothing resolves, so path references only read
files below the roots the server's owner chose.
"""

from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

ROOTS_ENV = "AYON_COMFYUI_ROOTS"
ROOTS_FILE = os.path.join("__ayon", "roots.json")
_ROOTLESS = re.compile(r"^\{root\[([A-Za-z0-9_-]+)\]\}(.*)$", re.DOTALL)
MAX_CHECK_PATHS = 100_000

_cache: dict = {"key": None, "roots": {}}


def _roots_file() -> str | None:
    try:
        import folder_paths  # noqa: PLC0415
    except ImportError:
        return None
    return os.path.join(folder_paths.get_user_directory(), ROOTS_FILE)


def _read_roots(source: str) -> dict:
    text = source.strip()
    if not text.startswith("{"):
        with open(text, encoding="utf-8") as stream:
            text = stream.read()
    data = json.loads(text)
    if not isinstance(data, dict):
        msg = "AYON roots must be a JSON object of root name to path"
        raise TypeError(msg)
    return {
        str(name): os.path.abspath(str(path))
        for name, path in data.items()
        if isinstance(path, str) and path
    }


def configured_roots() -> dict[str, str]:
    """Return the AYON roots configured on this ComfyUI server."""
    env = os.environ.get(ROOTS_ENV, "")
    path = _roots_file()
    try:
        mtime = os.path.getmtime(path) if path else None
    except OSError:
        mtime = None
    key = (env, path, mtime)
    if _cache["key"] == key:
        return _cache["roots"]

    roots: dict[str, str] = {}
    try:
        if mtime is not None:
            roots.update(_read_roots(path))
        if env:
            roots.update(_read_roots(env))
    except (OSError, ValueError, TypeError) as exc:
        log.warning("Invalid AYON roots configuration: %s", exc)
    _cache.update(key=key, roots=roots)
    return roots


def resolve_rootless(path: str) -> str | None:
    """Return the local path of an AYON rootless path, or None.

    Only paths below a configured root resolve; `..` can't escape it.
    """
    if not isinstance(path, str):
        return None
    match = _ROOTLESS.match(path)
    if match is None:
        return None
    root = configured_roots().get(match.group(1))
    if not root:
        return None
    relative = match.group(2).replace("\\", "/").lstrip("/")
    full = os.path.abspath(os.path.join(root, relative))
    try:
        common = os.path.commonpath([full, root])
    except ValueError:  # different drives
        return None
    inside = os.path.normcase(common) == os.path.normcase(root)
    return full if inside else None


async def handle_check(request):  # noqa: ANN001, ANN201
    """Tell AYON which rootless paths this server can read.

    Body: `{"paths": ["{root[work]}/...", ...]}`. Answers
    `{"roots": [names], "exists": [bool, ...]}`. Only paths below a
    configured root are ever checked.
    """
    from aiohttp import web  # noqa: PLC0415

    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    paths = body.get("paths") if isinstance(body, dict) else None
    if not isinstance(paths, list) or len(paths) > MAX_CHECK_PATHS:
        return web.json_response({"error": "invalid paths"}, status=400)
    exists = []
    for path in paths:
        resolved = resolve_rootless(path)
        exists.append(bool(resolved) and os.path.isfile(resolved))
    return web.json_response(
        {"roots": sorted(configured_roots()), "exists": exists},
        headers={"Cache-Control": "no-store"},
    )


def add_routes(routes) -> None:  # noqa: ANN001
    """Register the path routes on ComfyUI's server."""
    routes.post("/ayon/paths/check")(handle_check)
