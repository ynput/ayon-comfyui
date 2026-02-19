import asyncio

from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType
from aiohttp.client import _WSRequestContextManager


async def retrieve_websocket_connection() -> _WSRequestContextManager:
    session = ClientSession()
    ws = await session.ws_connect("ws://localhost:55055/ws/")
    return ws, session


async def ping_websocket(ws: _WSRequestContextManager):
    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            if msg.data == "close cmd":
                await ws.close()
                break
            else:
                print("We're still alive!", msg.data)
                await ws.send_str(msg.data + "/answer")
        elif msg.type == WSMsgType.ERROR:
            break


async def spam_websocket(ws: ClientWebSocketResponse):
    while True:
        await ws.send_str("ping")
        await asyncio.sleep(0.5)
