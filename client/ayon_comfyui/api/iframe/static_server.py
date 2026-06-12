import asyncio
import logging
import sys
from pathlib import Path
from threading import Thread

from aiohttp import web

from ayon_comfyui.api.consts import LOG_LEVEL
from ayon_comfyui.api.iframe.page_templater import template_html

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


class StaticServerThread(Thread):
    """Serves the basic webpage on http://localhost:port with the <iframe>
    in it."""

    def __init__(
        self,
        *args,  # noqa : ANN002
        port: int = 5454,
        comfy_webui_port: int = 55056,
        comfy_url: str = "http://127.0.0.1:8188",
        **kwargs,  # noqa : ANN003
    ):
        fpath = Path(__file__).parent
        self.port = port
        self.comfy_url = comfy_url
        self.comfy_webui_ws_port = comfy_webui_port

        async def index(request: web.Request) -> web.Response:  # noqa :ARG001, RUF029
            """Return templated HTML page."""
            return web.Response(
                text=template_html(
                    comfy_url=self.comfy_url,
                    webui_port=self.comfy_webui_ws_port,
                ),
                content_type="text/html",
            )

        self._app = web.Application()
        self._app.router.add_get("/", index)
        self._app.router.add_static("/static/", fpath / "static/")

        self.loop = None

        self._shutdown_event = None

        super().__init__(*args, **kwargs)

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._shutdown_event = asyncio.Event()
        self.loop.run_until_complete(self.async_run())

    async def async_run(self):
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", self.port)
        await site.start()
        print(f"Static Server running on http://127.0.0.1:{self.port}")

        # Shutdown conditional
        await self._shutdown_event.wait()
        await site.stop()
        await runner.cleanup()

    def stop(self):
        self.loop.call_soon_threadsafe(self._shutdown_event.set)
