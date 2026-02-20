"""Using a QObject to manage the lifetime of RPC server."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections import deque
from typing import TYPE_CHECKING, ClassVar, Type

if TYPE_CHECKING:
    from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import partial
from threading import Thread
from traceback import print_tb

from qtpy.QtCore import QObject, QTimer

from ayon_comfyui.api.qtthread_interface import QThread_interface
from ayon_comfyui.api.result import safe_partial
from ayon_comfyui.api.rpc_client import RPCClient
from ayon_comfyui.api.rpc_server import RPCServer
from ayon_comfyui.api.rpc_server_stub import RPCServerStub

logging.basicConfig(force=True, stream=sys.stdout, level=logging.DEBUG)
log = logging.getLogger("ayon_comfyui")

@dataclass
class ClientRPCkwargs:
    """Struct for RPC client kwargs."""

    hostname: str
    port: int | str
    use_https: bool

    @property
    def kwargs(self):
        """Arguments to be forwarded into RPC Client constructor."""
        return asdict(self)


@dataclass
class ServerRPCkwargs:
    """Struct for RPC server kwargs."""

    port: int | str

    @property
    def kwargs(self):
        """Arguments to be forwarded into RPC Client constructor."""
        return asdict(self)


class QRPCManager(QObject, QThread_interface):
    """Manage RPC async processes within QThread context."""

    _main_tasks: ClassVar[Type[deque]] = deque()
    _stored_man: ClassVar[QRPCManager] = None

    def __init__(
        self,
        *,
        parent: QObject = None,
        client_hostname: str = "localhost",
        client_port: int | str = 55055,
        server_port: int | str = 55056,
        use_https: bool = False,
    ):
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

        self._client_rpc_data = ClientRPCkwargs(
            hostname=client_hostname,
            port=client_port,
            use_https=use_https,
        )

        self._server_rpc_data = ServerRPCkwargs(port=server_port)

        self._server_thread = RPCServerThread(self._server_rpc_data, self)

        self._client_thread = RPCClientThread(self._client_rpc_data, self)

        self._stub_client = RPCServerStub()

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
            self._server_thread.start()
        except BaseException as e:
            log.debug(f"failure in server thread start: {e}")  # noqa: G004

        log.info("server thread supposedly started")
        try:
            self._client_thread.start()
        except BaseException as e:
            log.debug(f"failure in client thread start {e}")  # noqa: G004
        log.info("client thread supposedly started")
        self._loop_timer.start()
        log.info("Started QT loop")
        log.info("Setting up stub.")
        try:
            self._stub_client.setup_class(self)
            self._stub_client.run()
        except BaseException as e:  # noqa: BLE001
            log.info(f"failure in server stub start {e}")  # noqa: G004

    @classmethod
    def get_instance(cls) -> QRPCManager:
        """Service Locator-like pull Singleton from class registry.

        Returns:
            class contained QRPCManager instance.
        """
        return cls._stored_man

    @property
    def stub(self) -> RPCServerStub:
        """Return stored stub."""
        return self._stub_client


class RPCClientThread(Thread):
    """Manages async event loop for RPC Client in a Thread."""

    def __init__(self, rpc_data: ClientRPCkwargs, qt_thread: QRPCManager):
        super().__init__()
        self.loop = None
        self.rpc = None
        self.rpc_kwargs = rpc_data
        self.qt_thread = qt_thread

    def run(self) -> None:
        """On thread run, wrap event loop and RPC client."""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.rpc = RPCClient(**self.rpc_kwargs.kwargs)
            # await connection
            self.loop.run_until_complete(self.rpc.connect())

            # We don't care about the ref to this future,
            # since this is going to launch as a polling operation.
            # TODO(@sas): Deprecate WSRPC and simplify to regular websocket.
            #             This avoids an unneeded dependency addition @ Comfyui.
            asyncio.ensure_future(self.rpc.ping(), loop=self.loop)  # noqa: RUF006
            self.loop.run_forever()
        except BaseException as e:  # noqa: BLE001
            log.debug(f"Error during client run: {e}")  # noqa: G004

    @property
    def connected(self) -> bool:
        """Return whether wrapped rpc client is connected."""
        if self.rpc:
            return self.rpc.connected
        return False


class RPCServerThread(Thread):
    """Manages async event loop for RPC Server in a Thread."""

    def __init__(self, rpc_data: ServerRPCkwargs, qt_thread: QRPCManager):
        super().__init__()
        self.loop = None
        self.rpc_server = None
        self.rpc_kwargs: ServerRPCkwargs = rpc_data
        self.qt_thread = qt_thread

    def run(self) -> None:
        """On thread run, wrap event loop and RPC client."""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.rpc_server = RPCServer(self.rpc_kwargs.port, self.qt_thread)
            self.rpc_server.setup_server()
            # Run server
            self.rpc_server.run_server(self.rpc_kwargs.port, loop=self.loop)
        except BaseException as e:  # noqa: BLE001
            log.debug(f"Error during server run: {e}")  # noqa: G004
