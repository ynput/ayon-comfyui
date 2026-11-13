"""HTTP access to ComfyUI's own API (`/prompt`, `/history`, `/view`, ...).

Every URL is built here, on the AYON side, from the ComfyUI URL of the
session (sub-paths kept), so nothing is ever fetched from a URL that a
browser tab handed us. It uses plain `urllib` with the default SSL context,
so it is thread-safe, works while the bridge websocket reconnects, and works
without a paired tab (headless).

This module has no Qt or AYON dependencies.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

from ayon_comfyui.api.bridge_client import BridgeError, join_url

DEFAULT_TIMEOUT = 30.0
DOWNLOAD_TIMEOUT = 600.0
# Error bodies are only read to explain a failure.
MAX_ERROR_BODY = 64 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: AYON only fetches URLs it built itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201, PLR0913, PLR0917
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class ComfyHttp:
    """Small client for ComfyUI's HTTP API.

    Args:
        base_url: ComfyUI URL, e.g. `http://127.0.0.1:8188` or
            `https://comfy.studio.com/sub/path`.
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def url(self, path: str, params: dict | None = None) -> str:
        """Return the URL of `path` on this ComfyUI."""
        url = join_url(self.base_url, path)
        if params:
            url = f"{url}?{urlencode(params)}"
        return url

    def http_json(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,  # noqa: A002, ANN401
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Any:  # noqa: ANN401
        """Send a request and return its decoded JSON response.

        Raises:
            BridgeError: Code `http_<status>` when ComfyUI answers with an
                error status (the message includes its error text, and
                `body` holds the decoded error response), or `unreachable`.
        """
        data = None
        all_headers = {"Accept": "application/json", **(headers or {})}
        if json is not None:
            data = _json_dumps(json).encode("utf-8")
            all_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(  # noqa: S310
            self.url(path, params),
            data=data,
            method=method,
            headers=all_headers,
        )
        try:
            with _OPENER.open(request, timeout=timeout) as response:  # noqa: S310
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise _http_error(exc, method, path) from exc
        except (OSError, ValueError) as exc:
            msg = f"Unable to reach ComfyUI at {self.base_url}: {exc}"
            raise BridgeError(msg, "unreachable") from exc
        if not body:
            return None
        try:
            return _json_loads(body)
        except ValueError as exc:
            msg = f"ComfyUI answered {method} {path} with invalid JSON."
            raise BridgeError(msg, "invalid_response") from exc

    def download(
        self,
        path: str,
        dest: str | os.PathLike,
        *,
        params: dict | None = None,
        timeout: float | None = DOWNLOAD_TIMEOUT,
    ) -> int:
        """Stream a response body into the file `dest`.

        The file is written next to `dest` first and only moved into place
        once complete, so a failed download never leaves a partial file.

        Returns:
            The number of bytes written.
        """
        dest = os.fspath(dest)
        request = urllib.request.Request(self.url(path, params), method="GET")  # noqa: S310
        directory = os.path.dirname(dest) or "."
        os.makedirs(directory, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(
            prefix=".download-", dir=directory
        )
        try:
            with os.fdopen(handle, "wb") as stream:
                try:
                    with _OPENER.open(request, timeout=timeout) as response:
                        shutil.copyfileobj(response, stream, 1024 * 1024)
                except urllib.error.HTTPError as exc:
                    raise _http_error(exc, "GET", path) from exc
                except (OSError, ValueError) as exc:
                    msg = (
                        f"Unable to download {path} from ComfyUI at "
                        f"{self.base_url}: {exc}"
                    )
                    raise BridgeError(msg, "unreachable") from exc
                size = stream.tell()
            os.replace(temp_path, dest)
        except BaseException:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
        return size


def _http_error(
    exc: urllib.error.HTTPError, method: str, path: str
) -> BridgeError:
    try:
        raw = exc.read(MAX_ERROR_BODY)
    except OSError:
        raw = b""
    body: Any = None
    detail = ""
    if raw:
        try:
            body = _json_loads(raw)
        except ValueError:
            detail = raw.decode("utf-8", "replace").strip()[:500]
        else:
            detail = _error_text(body)
    message = f"ComfyUI answered {method} {path} with HTTP {exc.code}"
    if detail:
        message = f"{message}: {detail}"
    error = BridgeError(message, f"http_{exc.code}")
    error.status = exc.code
    error.body = body
    return error


def _error_text(body: Any) -> str:  # noqa: ANN401
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("type") or error)
        if error:
            return str(error)
    return ""


def _json_dumps(data: Any) -> str:  # noqa: ANN401
    return json.dumps(data)


def _json_loads(raw: bytes) -> Any:  # noqa: ANN401
    return json.loads(raw.decode("utf-8"))
