"""Using a QObject to manage the lifetime of RPC server."""

from __future__ import annotations

import logging
import sys
from collections import deque
from typing import TYPE_CHECKING, ClassVar, Type

if TYPE_CHECKING:
    from collections.abc import Callable
from functools import partial

from qtpy.QtCore import QObject, QTimer

from ayon_comfyui.api.consts import LOG_LEVEL
from ayon_comfyui.api.iframe import StaticServerThread
from ayon_comfyui.api.qtthread_interface import QThread_interface
from ayon_comfyui.api.result import safe_partial
from ayon_comfyui.api.rpc_server_iframe import RPCServerThread
from ayon_comfyui.api.rpc_server_stub_iframe import RPCStub
from ayon_comfyui.api.ws_client import WSClientThread

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


class QRPCManager(QObject, QThread_interface):
    """Manage RPC async processes within QThread context."""

    _main_tasks: ClassVar[Type[deque]] = deque()
    _stored_man: ClassVar[QRPCManager] = None

    def __init__(  # noqa :PLR0913
        self,
        *,
        parent: QObject = None,
        client_hostname: str = "localhost",
        client_port: int | str = 55055,
        server_port: int | str = 55056,
        static_port: int | str = 5454,
        comfy_url: str = "http://127.0.0.1:8818",
        use_https: bool = False,
    ) -> None:
        """Construct QRPCManager.

        For a local session, the client hostname will always be hostname.

        The client port is the port we use to connect to the backend,
        That's where this plugin acts as a "client"
        The server port is the port we open to the webui.
        """
        # Sneak constructed object into class definition.
        # Semi-Singleton behavior.
        self.__class__._stored_man = self  # noqa: SLF001
        log.info("within QRPCManager init")
        super().__init__(parent=parent)

        self._server_thread = RPCServerThread(
            server_port, self, https=use_https
        )
        self._static_thread = StaticServerThread(
            port=static_port, comfy_url=comfy_url
        )
        self._ws_client_thread = WSClientThread(
            hostname=client_hostname, port=client_port, use_https=use_https
        )

        # Stub just exists by itself.
        self._stub = RPCStub()

        # Define QTimers to process the tasks
        loop_timer = QTimer()
        loop_timer.setInterval(100)
        loop_timer.timeout.connect(self.process_scheduled_tasks)

        self._loop_timer = loop_timer

    def schedule(self, function: Callable, *args, **kwargs):
        log.info("scheduled function to qt thread")
        f = partial(function, *args, **kwargs)
        self._main_tasks.append(f)

    def process_scheduled_tasks(self) -> None:
        """QTimer scheduled process to run tasks stored in task queue."""
        # capture current length of queue
        current_tasks = len(self._main_tasks)

        if current_tasks > 0:
            log.info("processing tasks...")
        # move tasks out of list
        # (generator expression later made concrete during filter)
        task_list = (self._main_tasks.popleft() for _ in range(current_tasks))
        task_list = [safe_partial(t) for t in task_list if t]  # filter Falsey

        results = [task() for task in task_list]

        [
            log.debug(f"Error encountered in scheduled task: {res.error}")  # noqa: G004
            for res in results
            if res.is_err
        ]

    def start_server(self) -> None:
        """Wraps server start logic in thread."""
        log.info("within QRPCManager start_server")
        try:
            self._static_thread.start()
        except BaseException as e:  # noqa: BLE001
            log.debug(f"failure in static server thread start: {e}")  # noqa: G004
        log.info("static <iframe> server thread supposedly started")
        try:
            self._server_thread.setup_server()
            self._server_thread.start()
        except BaseException as e:  # noqa: BLE001
            log.debug(f"failure in websocketserver thread start: {e}")  # noqa: G004

        log.info("websocketserver thread supposedly started")
        # try:
        #     self._rpc_client_thread.start()
        # except BaseException as e:
        #     log.debug(f"failure in client thread start {e}")
        try:
            self._ws_client_thread.start()
        except BaseException as e:  # noqa: BLE001
            log.debug(f"failure in ws client thread start {e}")  # noqa: G004

        log.info("ws client thread supposedly started")
        self._loop_timer.start()
        log.info("Started QT loop")

    @classmethod
    def get_instance(cls) -> QRPCManager:
        """Service Locator-like pull Singleton from class registry.

        Returns:
            class contained QRPCManager instance.
        """
        return cls._stored_man

    @property
    def stub(self) -> RPCStub:
        """Return stored stub."""
        return self._stub
