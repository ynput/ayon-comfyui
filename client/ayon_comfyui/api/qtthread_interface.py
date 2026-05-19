from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qtpy.QtCore import SignalInstance


class ThreadLike:
    """Expose stop function."""

    def stop(self) -> None:
        """Set event flag of this thread to stop execution."""


class QThread_interface:  # noqa: N801
    """Mimic forward declaration of QRPCManager."""

    sig_onheartbeat_fail: SignalInstance
    sig_onfrontendcon_fail: SignalInstance

    def schedule(
        self, function: Callable, *args: list[Any], **kwargs: dict[str, Any]
    ) -> None:
        """Schedule a function in the thread."""

    @property
    def server_thread(self) -> ThreadLike:
        """Get Server Thread for RPC."""

    @property
    def static_server_thread(self) -> ThreadLike:
        """Get Static Server Thread for RPC."""

    @property
    def ws_pulse_client(self):  # noqa :ANN201
        """Get WS client to pulse backend."""
