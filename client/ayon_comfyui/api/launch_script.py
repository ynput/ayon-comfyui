"""This python file describes the actual launching procedure.

It's called upon from the pre_launch_args.py hook,
by using `ayon_console run launch_script.py args, ...`
"""

from __future__ import annotations

import os
import sys
from typing import Type

# Use whole ass path for completeness sake to make sure it resolves
from ayon_comfyui.api.launch_logic import main

argv_t = Type[list[str]]


def valdidate_args(*args: argv_t) -> None:
    """Check and validate args (sys.argv).

    Returns Nothing.
    """
    fname = os.path.expanduser("~\\Desktop\\comfy_launchscript_log.txt")
    with open(fname, "w") as file:
        print(*args, sep="\n", file=file)

    main(*args)


if __name__ == "__main__":
    valdidate_args(sys.argv)
