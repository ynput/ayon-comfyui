"""Utility for knowing when it's okay to open the browser."""

import asyncio
import logging
import sys
import webbrowser
from threading import Thread

import aiohttp
from multidict import CIMultiDictProxy

from ayon_comfyui.api.consts import LOG_LEVEL

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


async def wait_for_site_availability(url: str) -> None:
    """Asynchronously wait for a website to open."""
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url) as r:
                    # 200 - HTTP OK!
                    if r.status == 200:  # noqa: PLR2004
                        log.info(f"Website @ {url} is up!")  # noqa : G004
                        break
            except aiohttp.ClientConnectorError:
                log.info(f"Website @ {url} not reachable")  # noqa : G004

            await asyncio.sleep(1)


async def get_site_headers(url: str) -> CIMultiDictProxy:
    """Return headers associated with a site."""
    async with aiohttp.ClientSession() as session, session.head(url) as r:
        return r.headers


def defer_site_launch_when_available(
    url_to_wait_for: str, url_to_launch: str
) -> None:
    """Waits for an URL to become available, then launches the browser."""

    class BrowserLaunchThread(Thread):
        """Thread used to defer browser execution."""

        def run(self) -> None:
            """Schedule async stuff in sync."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.async_run())

        async def async_run(self) -> None:  # noqa: PLR6301
            """Wait for availability of embedded site.

            Then, launch target site.
            """
            await wait_for_site_availability(url_to_wait_for)
            webbrowser.open(url_to_launch)

    BrowserLaunchThread().start()
