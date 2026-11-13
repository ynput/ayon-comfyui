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

import asyncio
import json
import logging
import os
import re

log = logging.getLogger(__name__)

ROOTS_ENV = "AYON_COMFYUI_ROOTS"
#: Header with the AYON host's bridge session secret.
SESSION_HEADER = "X-AYON-Session"
ROOTS_FILE = os.path.join("__ayon", "roots.json")
_ROOTLESS = re.compile(r"^\{root\[([A-Za-z0-9_-]+)\]\}(.*)$", re.DOTALL)
MAX_CHECK_PATHS = 20_000

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
    roots = {}
    for name, path in data.items():
        if not isinstance(path, str) or not path:
            continue
        path = os.path.abspath(path)  # noqa: PLW2901
        if os.path.dirname(path) == path:
            # A whole drive or filesystem would open up every file on it.
            log.warning("Ignoring AYON root '%s': %s is a filesystem root",
                        name, path)
            continue
        roots[str(name)] = path
    return roots


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
    if ":" in relative or "\0" in relative:
        # Drive letters and NTFS alternate data streams.
        return None
    full = os.path.realpath(os.path.join(root, relative))
    return full if is_inside(full, os.path.realpath(root)) else None


def is_inside(path: str, directory: str) -> bool:
    """Return whether `path` is `directory` or below it."""
    try:
        common = os.path.commonpath([path, directory])
    except ValueError:  # different drives
        return False
    return os.path.normcase(common) == os.path.normcase(directory)


def _is_ayon_session(request) -> bool:  # noqa: ANN001
    """Whether the request comes from a registered AYON session.

    The AYON host sends its session secret, the one it registers with on
    the bridge websocket.
    """
    from .bridge import BRIDGE, session_id_from_secret  # noqa: PLC0415

    secret = request.headers.get(SESSION_HEADER, "")
    if not 32 <= len(secret) <= 256:  # noqa: PLR2004
        return False
    return session_id_from_secret(secret) in BRIDGE.sessions


async def handle_check(request):  # noqa: ANN001, ANN201
    """Tell AYON which rootless paths this server can read.

    Body: `{"paths": ["{root[work]}/...", ...]}`. Answers
    `{"roots": [names], "exists": [bool, ...]}`. Only paths below a
    configured root are ever checked, and only for AYON sessions, so this
    doesn't tell anyone else which files exist.
    """
    from aiohttp import web  # noqa: PLC0415

    if not _is_ayon_session(request):
        return web.json_response({"error": "unauthorized"}, status=403)
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    paths = body.get("paths") if isinstance(body, dict) else None
    if not isinstance(paths, list) or len(paths) > MAX_CHECK_PATHS:
        return web.json_response({"error": "invalid paths"}, status=400)
    # Checking many files on a network share takes a while: keep ComfyUI's
    # server (and everyone's websocket) responsive meanwhile.
    exists = await asyncio.get_running_loop().run_in_executor(
        None, _paths_exist, paths
    )
    return web.json_response(
        {"roots": sorted(configured_roots()), "exists": exists},
        headers={"Cache-Control": "no-store"},
    )


def _paths_exist(paths: list) -> list[bool]:
    exists = []
    for path in paths:
        resolved = resolve_rootless(path)
        exists.append(bool(resolved) and os.path.isfile(resolved))
    return exists


def add_routes(routes) -> None:  # noqa: ANN001
    """Register the path routes on ComfyUI's server."""
    routes.post("/ayon/paths/check")(handle_check)
