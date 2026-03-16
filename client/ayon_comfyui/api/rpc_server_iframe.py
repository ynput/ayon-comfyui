from __future__ import annotations

import asyncio
import logging
import sys
from functools import wraps
from threading import Thread
from typing import Any, Callable, ClassVar

import aiohttp.web
from ayon_core.tools.utils import host_tools
from wsrpc_aiohttp import Route, WebSocketAsync, decorators
from wsrpc_aiohttp.websocket.common import WSRPCBase

from ayon_comfyui.api.consts import LOG_LEVEL
from ayon_comfyui.api.qtthread_interface import QThread_interface
from ayon_comfyui.api.util import extract_default_kwargs
from ayon_comfyui.parse_settings import ComfyLocalSettings, ComfyRemoteSettings

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


def show_tool_by_name(tool_name: str) -> None:
    """Show host tool by name, with default settings."""
    kwargs = {}
    if tool_name == "loader":
        kwargs["use_context"] = True
        kwargs["on_top"] = True

    if tool_name == "create":
        tool_name = "publisher"
        kwargs["tab"] = "create"

    if tool_name == "publisher":
        kwargs["tab"] = "publish"

    host_tools.show_tool_by_name(tool_name, **kwargs)


# TODO(@sas): This will all be on localhost.
#             The origin will be set to the page hosted through api/iframe/Static
# def _pull_origin_from_settings() -> str:
#     _, profile = ComfyRemoteSettings.pull_committed_settings()
#     if isinstance(profile, ComfyRemoteSettings.ComfyRemoteProfile):
#         return profile.comfy_origin
#     return "http://localhost:8188"


def pull_origin_from_settings() -> str:
    settings, profile = ComfyRemoteSettings.pull_committed_settings()
    if isinstance(profile, ComfyRemoteSettings.ComfyRemoteProfile):
        return profile.address_frontend
    if isinstance(settings, ComfyLocalSettings):
        return settings.address_frontend
    return "http://localhost:5454"


def get_client_from_origin(origin: str) -> WSRPCBase | None:
    """Attempt to get client from socket connections.

    This mimicks the photoshop ayon plugin, where the socket
    is read out and the first connection is picked.
    We want to be more thorough though, and make sure the
    connection header checks out!

    Returns:
        None if not found else WSRPCBase
    """
    clients_dict: dict[str, WSRPCBase] = WebSocketAsync.get_clients()
    for client in clients_dict.values():
        if (
            "Origin" in client.request.headers
            and client.request.headers.get("Origin") == origin
        ):
            return client
    return None


class AyonLocalHost(Route):
    """Handle Menu calls from JS part of ComfyUI plugin."""

    qt_thread: QThread_interface = None

    def init(self, **kwargs):
        """Override of init method. Can return anything."""
        return kwargs

    @classmethod
    def register_qrpc_manager(cls, qrpc: QThread_interface):
        cls.qt_thread = qrpc

    @decorators.proxy
    async def pingAyonMenu(self, message: str) -> str:  # noqa: PLR6301, N802
        """Returns message sent from server."""
        return message

    @decorators.proxy
    async def requestToolByName(self, tool_name: str) -> None:  # noqa: N802
        """Schedule tool in thread."""
        log.debug(f"origin {self.socket.request.headers}")
        if self.qt_thread:
            self.qt_thread.schedule(show_tool_by_name, tool_name)
            return f"{tool_name} scheduled in qt_thread"
        return tool_name


class RPCServerThread(Thread):
    """Manages event loop for the server that recieves messages.

    In particular, deal with the JavaScript part of the plugin.
    """

    _instance: ClassVar[RPCServerThread] = None

    def __init__(
        self,
        port: int = 55056,
        qthread: QThread_interface = None,
        *,
        https: bool = False,
    ):
        self._app = None
        self._port = port
        self._setup = False
        self._is_running = False
        self._is_https = https
        self._loop: asyncio.AbstractEventLoop = None
        self._shutdown_event = None

        self._origin = pull_origin_from_settings()
        log.info(self._origin)
        AyonLocalHost.register_qrpc_manager(qthread)
        self.__class__._instance = self  # noqa: SLF001

        super().__init__()

    @classmethod
    def get_thread(cls) -> RPCServerThread:
        """Return stored thread."""
        return cls._instance

    def setup_server(self) -> None:
        """Set up server, do not start it yet."""
        self._app = aiohttp.web.Application()
        # on https replace with Origin Checking Websocket Async.
        # ws_cls = WebSocketAsync

        # self.__class__._ws_cls = ws_cls
        self._app.router.add_route("*", "/ws/", WebSocketAsync)

        WebSocketAsync.add_route("ayonComfyUI", AyonLocalHost)
        self._setup = True

    def run(self) -> None:
        """Do server run."""
        if not self.is_set_up:
            return
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._shutdown_event = asyncio.Event()
        self._loop.run_until_complete(self.async_run())

    async def async_run(self) -> None:
        """Run server async."""
        runner = aiohttp.web.AppRunner(self._app)
        await runner.setup()
        site = aiohttp.web.TCPSite(runner, "localhost", self._port)
        await site.start()
        log.info(
            f"Websocket Server running on ws://localhost:{self._port}/ws/"  # noqa: G004
        )

        # Shutdown conditional
        await self._shutdown_event.wait()
        await site.stop()
        await runner.cleanup()

    @property
    def is_set_up(self) -> bool:
        """Return whether the server is set up.

        This doesn't mean that the server is running,
        but it means that the server is ready to run.
        """
        return self._setup

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Return contained loop."""
        return self._loop

    def stop(self) -> None:
        """Stop server from running."""
        self._loop.call_soon_threadsafe(self._shutdown_event.set)


def call_on_origin(origin: str = None) -> Callable:
    """Decorator to send a function to a specific client on the websocket thread.

    Function signature should be like this:
    ```
    @call_on_origin("http://expected-origin.com")
    def name_of_method(*, arg1='default1', arg2='default2') -> T:
        pass
    ```
    """  # noqa : DOC201

    def _outer_wrapper(func: Callable) -> Callable:
        @wraps(func)
        def _inner_wrapper(*args: list[Any], **kwargs: dict[str, Any]) -> Any:  # noqa: ARG001, ANN401
            _origin_ = (
                RPCServerThread.get_thread()._origin  # noqa: SLF001
                if origin is None
                else origin
            )

            client = get_client_from_origin(origin=_origin_)
            log.info("FOR ORIGIN:" + _origin_)
            log.info("GOT CLIENT:" + str(client))
            if client is None:
                return None

            ws_loop = RPCServerThread.get_thread().loop
            default_kw = extract_default_kwargs(func)

            kwargs = default_kw | kwargs
            func_name = func.__qualname__

            # remove class namespace
            if "." in func_name:
                func_name = func.__qualname__.split(".")[-1]

            fut = asyncio.run_coroutine_threadsafe(
                client.call(func_name, **kwargs), ws_loop
            )
            # From testing, it's beneficial to explicitly wait for return.
            result = fut.result()
            return result  # noqa: RET504

        return _inner_wrapper

    return _outer_wrapper
