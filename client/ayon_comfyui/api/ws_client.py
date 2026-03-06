from __future__ import annotations

import asyncio
import logging
import sys
from functools import partial
from threading import Thread
from typing import Any, Callable

import aiohttp

from ayon_comfyui.api.consts import LOG_LEVEL

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


class WSClientThread(Thread):
    """Establishes an initial connection, then tries a few times to reconnect.

    After that, fail and optionally run function on failure.
    """

    def __init__(
        self,
        hostname: str = "localhost",
        port: int | str = 55055,
        use_https: bool = False,  # noqa: FBT001, FBT002
        retries: int = 3,
        retry_interval: float = 5.0,
    ):
        self._host = hostname
        self._port = port
        self._endpoint = "ws"
        self._https = use_https

        self._url = f"ws{'s' if self._https else ''}://{self._host}:{self._port}/{self._endpoint}"

        self._retries: int = 0
        self._total_retries: int = retries
        self._retry_interval: float = retry_interval

        self._initial_connect = True
        self._on_broken: Callable | None = None
        self._broken = False

        self.loop = None

        super().__init__()

    def run(self) -> None:
        """Method representing the thread's activity."""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            asyncio.ensure_future(self.async_run(), loop=self.loop)  # noqa: RUF006
            self.loop.run_forever()
        except BaseException as e:  # noqa: BLE001
            log.debug(f"Error during client run: {e}")  # noqa: G004

    async def async_run(self) -> None:
        """Connection, pinging logic."""
        while True:
            await self.ws_client(wait_forever=self._initial_connect)
            self._initial_connect = False
            if self._retries < self._total_retries:
                self._retries += 1
                print(f"Retry {self._retries} / {self._total_retries}")
                await asyncio.sleep(self._retry_interval)
            else:
                break
        # when loop has been broken, run on_broken
        if self._on_broken:
            self._on_broken()

        self._broken = True

    def register_on_connection_broken(
        self, func: Callable, *args: list[Any], **kwargs: dict[str, Any]
    ) -> None:
        """Register a function to be called when the connection breaks."""
        self._on_broken = partial(func, *args, **kwargs)

    async def ws_client(self, wait_forever: bool = False) -> None:  # noqa: FBT001, FBT002
        """Connect to a server to maintain heartbeat.

        Returns when the connection has ended.
        """

        async def _establish_con() -> None:
            """Block until connected.

            Raises:
                aiohttp.ClientConnectorError
            """
            async with (
                aiohttp.ClientSession() as ses,
                ses.ws_connect(self._url, heartbeat=5) as ws,
            ):
                # Block until heartbeat fails
                print("Established connection!")
                async for _ in ws:
                    pass

        if wait_forever:
            while True:
                try:
                    await _establish_con()
                    break
                except aiohttp.ClientConnectorError:
                    print("Couldn't connect, trying again in 1 second.")
                    await asyncio.sleep(1)
        else:
            try:
                await _establish_con()
            except aiohttp.ClientConnectorError:
                print("Couldn't connect.")
