"""This python file describes the actual launching procedure.

It's called upon from the pre_launch_args.py hook,
by using `ayon_console run launch_script.py args, ...`
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Type

from ayon_comfyui.api.consts import LOG_LEVEL

# Use whole ass path for completeness sake to make sure it resolves
from ayon_comfyui.api.launch_logic import main_local, main_remote

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


argv_t = Type[list[str]]


def valdidate_args(*args: argv_t) -> None:
    """Check and validate args (sys.argv).

    Returns Nothing.
    """
    log.info(f"launching with {args}")  # noqa: G004

    is_remote = os.environ.get("COMFY_IS_REMOTE", "No")

    if is_remote in {"yes", "No", "NO", 0}:
        main_local(*args)
    elif is_remote in {"yes", "Yes", "YES", 1}:
        main_remote(*args)


if __name__ == "__main__":
    valdidate_args(sys.argv)
