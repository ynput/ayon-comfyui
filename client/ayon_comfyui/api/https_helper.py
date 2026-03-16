"""Tools for https on localhost.

The only requirement, now that we're RPC-ing:
AYON -> WS -> iframe.postMessage -> ComfyUI

is that the embedded ComfyUI site isn't contaminated with the wrong headers.

"""

from __future__ import annotations

import logging
import secrets
import ssl
import subprocess
import sys

from ayon_comfyui.api.consts import LOG_LEVEL
from ayon_comfyui.api.util import cache_result

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


def curl_get_site_headers(website: str) -> dict[str, str]:
    """Return headers associated with a site.

    TODO(@sas): Rewrite this to aiohtpp to make it actually viable.

    Uses 'curl -I ' to get them.
    """
    proc = subprocess.Popen(
        ["curl", "-I", website],  # noqa: S607
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    out, _ = proc.communicate()
    out = out.strip()
    iter_out = iter(out.splitlines())
    next(iter_out)  # Skip HTTP response

    collect_dict: dict[str, str] = {}

    for line in iter_out:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        collect_dict[key] = value

    return collect_dict


def get_ssl_context_client() -> ssl.SSLContext:
    """Returns client suitable default SSL context."""
    return ssl.create_default_context()


@cache_result
def get_session_secret() -> str:
    """Returns a 16 char long hex-compatible secret.

    This function is cached and will reproduce the same output.
    """
    return secrets.token_hex(16)
