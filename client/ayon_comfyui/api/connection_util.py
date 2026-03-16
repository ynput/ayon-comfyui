"""Utility for knowing when it's okay to open the browser."""

import asyncio
import logging
import sys
import webbrowser
from threading import Thread

import aiohttp

from ayon_comfyui.api.consts import LOG_LEVEL

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


async def wait_for_site_availability(url: str):
    """Asynchronously wait for a website to open."""
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with (
                    session.get(url) as r,
                ):
                    # 200 - HTTP OK!
                    if r.status == 200:  # noqa: PLR2004
                        log.info(f"Website @ {url} is up!")  # noqa : G004
                        break
            except aiohttp.ClientConnectorError:
                log.info(f"Website @ {url} not reachable")  # noqa : G004

            await asyncio.sleep(1)


def defer_site_launch_when_available(
    url_to_wait_for: str, url_to_launch: str
) -> None:
    """Waits for an URL to become available, then launches the browser."""

    class BrowserLaunchThread(Thread):
        """Thread used to defer browser execution."""

        def run(self):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.async_run())

        async def async_run(self):
            await wait_for_site_availability(url_to_wait_for)
            webbrowser.open(url_to_launch)

    BrowserLaunchThread().start()
