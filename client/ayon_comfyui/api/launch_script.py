"""This python file describes the actual launching procedure.

It's called upon from the pre_launch_args.py hook,
by using `ayon_console run launch_script.py args, ...`
"""

from __future__ import annotations

import logging
import sys
from typing import Type

from ayon_comfyui.api.consts import LOG_LEVEL

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")

# Use whole ass path for completeness sake to make sure it resolves
from ayon_comfyui.api.launch_logic import main

argv_t = Type[list[str]]


def valdidate_args(*args: argv_t) -> None:
    """Check and validate args (sys.argv).

    Returns Nothing.
    """
    log.info(f"launching with {args}")  # noqa: G004

    main(*args)


if __name__ == "__main__":
    valdidate_args(sys.argv)
