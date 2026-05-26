from traceback import print_exception

from aiohttp import web

from .consts import AYON_BACKEND_PORT

_CLIENTS = set()


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle ping pong until error."""
    # Be explicit about handling ping pong
    ws = web.WebSocketResponse(autoping=True)
    await ws.prepare(request)

    _CLIENTS.add(ws)

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.ERROR:
                print("Something Has Gone Awry...")
                print_exception(ws.exception())
    finally:
        _CLIENTS.remove(ws)

    return ws


def run_server():
    app = web.Application()
    app.router.add_get("/ws", ws_handler)

    web.run_app(app, host="127.0.0.1", port=AYON_BACKEND_PORT)
