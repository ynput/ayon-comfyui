from __future__ import annotations

from collections.abc import Callable
from typing import Any


class QThread_interface:  # noqa: N801
    """Mimic forward declaration of QRPCManager."""

    def schedule(
        self, function: Callable, *args: list[Any], **kwargs: dict[str:Any]
    ) -> None:
        """Schedule a function in the thread."""
