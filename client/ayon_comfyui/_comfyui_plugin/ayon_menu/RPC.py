import asyncio
import sys

import aiohttp.web

if __name__ == "__main__":
    sys.path.append(
        "C:\\Users\\sas.vangulik\\AppData\\Local\\Ynput\\AYON\\dependency_packages\\ayon_2503211538_windows.zip\\runtime"
    )

# TODO: Deprecate WSRPC. We don't need functionality here necessarily.
from wsrpc_aiohttp import Route, WebSocketAsync, decorators

from .client_tracker import TRACKER
from .consts import AYON_BACKEND_PORT


class ComfyUIAyonRoute(Route):
    def init(self, **kwargs):
        """Override of init method. Can return anything."""
        return kwargs

    @decorators.proxy
    async def registerClient(self, client_id):
        """Endpoint for registering the client on first connect"""
        name, ip = (
            client_id["hostname"],
            client_id["ip"],
        )
        print("Registering session for", name, ip)
        client_hash = TRACKER.register(hostname=name, ip=ip)
        return client_hash

    @decorators.proxy
    async def pingAyonMenu(self, message, client_id):
        print(client_id)
        name, ip = client_id["hostname"], client_id["ip"]
        # We need to use this to save client ID somewhere as a hash maybe
        print("RECEIVED RPC:", message, name, ip)

        return "Hi from ayon_menu python plugin!"

    @decorators.proxy
    async def requestWorkfiles(self, message, client_id):
        # DEPRECATE: THIS SHOULD BE DONE AYON SIDE ON A SERVER.
        name, ip = client_id["web_uuid"]

        return "Hi from ayon_menu python plugin!"


def run_server():
    app = aiohttp.web.Application()
    app.router.add_route("*", "/ws/", WebSocketAsync)  # Websocket route
    print("Running task.")
    WebSocketAsync.add_route("testayon", ComfyUIAyonRoute)

    aiohttp.web.run_app(app, port=AYON_BACKEND_PORT, loop=asyncio.new_event_loop())


# TODO: Deprecate.
if __name__ == "__main__":
    run_server()
