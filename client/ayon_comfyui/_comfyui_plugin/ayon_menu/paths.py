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
files below the roots the server's owner chose. Anyone who can queue
prompts on this ComfyUI can read media files there through an AYON load
node, so on a shared server map the roots narrowly, and/or limit them to
projects with:

- `AYON_COMFYUI_PROJECTS`: project folder names (a JSON list, or comma
  separated), the first folder below a root. AYON sets it to the current
  project when it launches a local ComfyUI.

A root that is a whole drive, share or filesystem (`P:\\`, `\\\\nas\\share`,
`/`) would open up every file on it, so it is only used while
`AYON_COMFYUI_PROJECTS` narrows it to project folders, and ignored
otherwise (see `ignored_roots`).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re

log = logging.getLogger(__name__)

ROOTS_ENV = "AYON_COMFYUI_ROOTS"
PROJECTS_ENV = "AYON_COMFYUI_PROJECTS"
#: Header with the AYON host's proof of its bridge session (see
#: `session_proof`).
SESSION_HEADER = "X-AYON-Session"
ROOTS_FILE = os.path.join("__ayon", "roots.json")
_ROOTLESS = re.compile(r"^\{root\[([A-Za-z0-9_-]+)\]\}(.*)$", re.DOTALL)
MAX_CHECK_PATHS = 20_000

#: `ignored_roots` reason of a whole drive or filesystem root while
#: `AYON_COMFYUI_PROJECTS` isn't set.
WHOLE_DRIVE = "whole_drive"

_cache: dict = {"key": None, "roots": {}, "ignored": {}}


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
        str(name): os.path.abspath(path)
        for name, path in data.items()
        if isinstance(path, str) and path
    }


def is_filesystem_root(path: str) -> bool:
    """Return whether `path` is a whole drive, share or filesystem."""
    path = os.path.abspath(path)
    return os.path.dirname(path) == path


def _roots() -> tuple[dict[str, str], dict[str, dict]]:
    env = os.environ.get(ROOTS_ENV, "")
    path = _roots_file()
    try:
        mtime = os.path.getmtime(path) if path else None
    except OSError:
        mtime = None
    # Whether whole drives may be used depends on the projects.
    key = (env, os.environ.get(PROJECTS_ENV, ""), path, mtime)
    if _cache["key"] == key:
        return _cache["roots"], _cache["ignored"]

    configured: dict[str, str] = {}
    try:
        if mtime is not None:
            configured.update(_read_roots(path))
        if env:
            configured.update(_read_roots(env))
    except (OSError, ValueError, TypeError) as exc:
        log.warning("Invalid AYON roots configuration: %s", exc)

    narrowed = allowed_projects() is not None
    roots: dict[str, str] = {}
    ignored: dict[str, dict] = {}
    for name, root in configured.items():
        if is_filesystem_root(root) and not narrowed:
            # Anyone who can queue prompts on this ComfyUI can read the
            # files below its roots, so a whole drive (or share) is only
            # acceptable while access is narrowed to project folders.
            log.warning(
                "Ignoring AYON root '%s': %s is a whole drive or share, "
                "which is only used while %s limits it to project folders.",
                name, root, PROJECTS_ENV,
            )
            ignored[name] = {"path": root, "reason": WHOLE_DRIVE}
            continue
        roots[name] = root
    _cache.update(key=key, roots=roots, ignored=ignored)
    return roots, ignored


def configured_roots() -> dict[str, str]:
    """Return the AYON roots path references may read below.

    Leaves out the `ignored_roots`.
    """
    return _roots()[0]


def ignored_roots() -> dict[str, dict]:
    """Return the configured roots that aren't used, and why.

    Returns:
        Root name to `{"path": ..., "reason": ...}`, where the reason is
        `WHOLE_DRIVE`: the root is a whole drive, share or filesystem, and
        `AYON_COMFYUI_PROJECTS` doesn't narrow it to project folders.
    """
    return _roots()[1]


def allowed_projects() -> set[str] | None:
    """Return the project folders path references may read, None for all."""
    raw = os.environ.get(PROJECTS_ENV, "").strip()
    if not raw:
        return None
    try:
        names = json.loads(raw) if raw.startswith("[") else raw.split(",")
    except ValueError:
        log.warning("Invalid %s: %s", PROJECTS_ENV, raw)
        return set()
    return {
        os.path.normcase(str(name).strip())
        for name in names
        if str(name).strip()
    }


def resolve_rootless(path: str, *, strict: bool = True) -> str | None:
    """Return the local path of an AYON rootless path, or None.

    Only paths below a configured root (and inside an allowed project
    folder, see `AYON_COMFYUI_PROJECTS`) resolve; `..` and symlinks can't
    escape it.

    Args:
        path: AYON rootless path, e.g. `{root[work]}/project/...`.
        strict: Resolve symlinks (touches the filesystem). Without it the
            path is only checked lexically, e.g. for a quick validation.
    """
    if not isinstance(path, str):
        return None
    match = _ROOTLESS.match(path)
    if match is None:
        return None
    root = configured_roots().get(match.group(1))
    if not root:
        return None
    projects = allowed_projects()
    if projects is None and is_filesystem_root(root):
        # Never read a whole drive unless narrowed to project folders;
        # `configured_roots` already leaves such roots out.
        return None
    relative = match.group(2).replace("\\", "/").lstrip("/")
    if ":" in relative or "\0" in relative:
        # Drive letters and NTFS alternate data streams.
        return None
    resolve = os.path.realpath if strict else os.path.abspath
    full = resolve(os.path.join(root, relative))
    if not is_inside(full, resolve(root)):
        return None
    if projects is not None:
        # Checked on the resolved path, so a symlink can't leave the
        # project folder either; files next to the project folders (e.g.
        # at the top of a drive) aren't inside one.
        below_root = os.path.relpath(full, resolve(root))
        project, _sep, inside = below_root.replace("\\", "/").partition("/")
        if not inside or os.path.normcase(project) not in projects:
            return None
    return full


def is_inside(path: str, directory: str) -> bool:
    """Return whether `path` is `directory` or below it."""
    try:
        common = os.path.commonpath([path, directory])
    except ValueError:  # different drives
        return False
    return os.path.normcase(common) == os.path.normcase(directory)


def session_proof(secret: str) -> str:
    """Return what proves knowledge of a bridge session secret.

    The AYON host sends this (not the secret itself) in `SESSION_HEADER`.
    """
    return hmac.new(
        secret.encode(), b"ayon-paths-check", hashlib.sha256
    ).hexdigest()


def _is_ayon_session(request) -> bool:  # noqa: ANN001
    """Whether the request comes from a registered AYON session."""
    from .bridge import BRIDGE  # noqa: PLC0415

    proof = request.headers.get(SESSION_HEADER, "")
    if len(proof) != 64:  # noqa: PLR2004
        return False
    return any(
        hmac.compare_digest(proof, session_proof(session.secret))
        for session in list(BRIDGE.sessions.values())
    )


async def handle_check(request):  # noqa: ANN001, ANN201
    """Tell AYON which rootless paths this server can read.

    Body: `{"paths": ["{root[work]}/...", ...]}`. Answers
    `{"roots": [names], "ignored_roots": {name: {"path", "reason"}},
    "exists": [bool, ...]}`, so AYON can tell the artist why it uploads
    files instead. Only paths below a configured root are ever checked, and
    only for AYON sessions, so this doesn't tell anyone else which files
    exist.
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
        {
            "roots": sorted(configured_roots()),
            "ignored_roots": ignored_roots(),
            "exists": exists,
        },
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
