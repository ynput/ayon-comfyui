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


async def wait_for_site_availability_timeout(
    url: str, timeout: float = 5
) -> None:
    """Asynchronously wait for a website to open. with timeout."""

    async def timeout_(timeout: float) -> None:
        await asyncio.sleep(timeout)

    task_timeout = asyncio.create_task(timeout_(timeout))

    async with aiohttp.ClientSession() as session:
        while not task_timeout.done():
            try:
                async with session.get(url) as r:
                    if r.status == 200:  # noqa: PLR2004
                        # cancel timeout task if still running
                        task_timeout.cancel()
                        return True

            except aiohttp.ClientConnectorError:
                pass

            await asyncio.sleep(0.2)
    return False


def poll_site_availability_timeout(url: str, timeout: float = 5) -> bool:
    """Get whether a site is available.

    Sync version of `wait_for_site_availability_timeout`

    Returns:
        True/False whether was able to connect.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(
        wait_for_site_availability_timeout(url, timeout)
    )


async def get_site_headers(url: str) -> CIMultiDictProxy:
    """Return headers associated with a site."""
    async with aiohttp.ClientSession() as session, session.head(url) as r:
        return r.headers


def poll_site_headers(url: str) -> CIMultiDictProxy:
    """Return headers associated with a site.

    Sync version of `get_site_headers`
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(get_site_headers(url))


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
