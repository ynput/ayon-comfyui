"""Implement RPC Client."""

from __future__ import annotations

import asyncio

# TODO(@sas): REMOVE
if __name__ == "__main__":
    import sys

    sys.path.append(
        "C:\\Users\\sas.vangulik\\AppData\\Local\\Ynput\\AYON\\dependency_packages\\ayon_2503211538_windows.zip\\runtime"
    )


import socket
import time
import webbrowser
from functools import partial
from threading import Thread
from typing import Any

from aiohttp.client_exceptions import ClientConnectorError
from aiohttp.web import GracefulExit
from ayon_core.tools.utils import host_tools
from wsrpc_aiohttp import WSRPCClient


class RPCClient:
    """Host-Side RPC Client to communicate with Comfy-side Server."""

    _shutdown = False
    _connected = True

    def __init__(
        self,
        *,
        hostname: str = "localhost",
        port: int | str = 55055,
        use_https: bool = False,
    ):
        """Initialize RPC Client with a goal host and port."""
        # TODO(@sas): Make this fetch settings
        self._host = hostname
        self._port = port
        self._endpoint = "ws/"
        self._https = use_https
        self._client = WSRPCClient(
            f"ws{'s' if self._https else ''}://{self._host}:{self._port}/{self._endpoint}"
        )

        # Hash recieved from server to identify our session
        self._client_id = None

        self._client.add_route("show_tool", self.handle_show_tool_by_name)

        self.comfy_port = 8188

        return

        # LEGACY: Control browser launch. We should ideally not do this, please
        def _launch_browser_deferred(delay_seconds: int) -> None:
            """Defer launch of browser.

            It should launch after comfy has actually started
            but the launched state can't be determined so a timeout will do.
            """
            time.sleep(delay_seconds)
            webbrowser.open(
                f"http{'s' if self._https else ''}://{self._host}:{self.comfy_port}#{self._client_uuid}"
            )

        self._browser_launch_delay = 10

        if False:
            Thread(
                target=_launch_browser_deferred,
                args=(self._browser_launch_delay,),
                daemon=True,
            ).start()

    async def connect(self) -> None:
        """Make connection to RPC server."""
        while not self._shutdown:
            print("Attempting connection")
            try:
                await self._client.connect()
                self._connected = True
                print("Connected!")
                self._client_id = await self._client.call(
                    "testayon.registerClient",
                    client_id=self.client_identity,
                )
                break
            except ClientConnectorError as e:
                print("Can't connect:", e)
                await asyncio.sleep(0.2)

    def shutdown(self, *args) -> None:
        """Shutdown protocol meant to be registered to an os signal."""
        self._shutdown = True
        self._connected = False
        if self._client:
            task = asyncio.ensure_future(self._client.close())
            task.add_done_callback(partial(print, "RPC shutdown succesful."))

    async def ping(self, interval: float = 0.2, message: str = "hi") -> None:
        """Spam RPC endpoint with "hi" message."""
        if not self.client:
            return

        while True:
            msg = await self.client.call(
                "testayon.pingAyonMenu",
                message=message,
                client_id=self.client_identity,
                timeout=0.2,
            )
            print(msg)
            await asyncio.sleep(interval)

    async def handle_show_tool_by_name(self, data: dict) -> None:
        """Dissects RPC message and calls function."""
        # MOVE TO SERVER

        tool = data.get("tool_name")
        if not tool:
            return
        tool_args = data.get("tool_args", {})
        self.show_tool_by_name(tool, **tool_args)

    def show_tool_by_name(
        self, tool_name: str, **kwargs: dict[str, Any]
    ) -> None:
        """Show tool by name."""
        host_tools.show_tool_by_name(tool_name, **kwargs)

    @property
    def client(self) -> WSRPCClient | None:
        """Return WSRPC client if connected, else None."""
        if self._connected:
            return self._client
        return None

    @property
    def connected(self) -> bool:
        """Return whether connected."""
        return self._connected

    @property
    def client_closed(self) -> bool | None:
        """Return if client is closed.

        None if no client.
        """
        if self._client:
            return self._client.closed
        return None

    @property
    def client_identity(self) -> dict[str, str]:
        """Return dict of hostname and ip."""
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        return {"hostname": hostname, "ip": ip}


# TODO(@sas): REMOVE, Reason: Legacy entrypoint test
if __name__ == "__main__":
    rpc = RPCClient()

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(rpc.connect())
        loop.run_until_complete(rpc.ping())
    except (GracefulExit, KeyboardInterrupt) as e:
        print("Interupted by:", type(e), e)
