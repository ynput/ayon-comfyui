"""Tests for the AYON bridge relay of the ComfyUI plugin.

Runs the relay in a plain aiohttp app on localhost (no ComfyUI needed).
Needs Python 3.9+ with aiohttp, e.g. ComfyUI's embedded Python:

    python tests/bridge/test_relay.py [<relay bridge.py>]
"""

import asyncio
import importlib.util
import json
import secrets
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

REPO = Path(__file__).resolve().parents[2]
RELAY_PATH = REPO / "client/ayon_comfyui/_comfyui_plugin/ayon_menu/bridge.py"
if len(sys.argv) > 1:
    RELAY_PATH = Path(sys.argv[1])

spec = importlib.util.spec_from_file_location("bridge", RELAY_PATH)
bridge_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_mod)

PORT = 18731
URL = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}/ayon/ws"
FAILS = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


async def recv(ws, timeout=3):
    msg = await ws.receive(timeout=timeout)
    if msg.type == aiohttp.WSMsgType.TEXT:
        return json.loads(msg.data)
    return {"_closed": msg.type.name, "code": ws.close_code,
            "extra": msg.extra}


async def recv_until(ws, pred, timeout=3):
    while True:
        frame = await recv(ws, timeout)
        if "_closed" in frame or pred(frame):
            return frame


async def host_connect(session, secret, info=None):
    ws = await session.ws_connect(WS)
    await ws.send_json({"type": "hello", "role": "host", "protocol": 1,
                        "secret": secret, "info": info or {"user": "a"}})
    return ws, await recv(ws)


async def tab_connect(session, **hello):
    ws = await session.ws_connect(WS, max_msg_size=0)
    await ws.send_json({"type": "hello", "role": "tab", "protocol": 1,
                        **hello})
    return ws, await recv(ws)


async def get_code(host):
    await host.send_json({"type": "pair_code"})
    return (await recv(host))["code"]


async def main():
    b = bridge_mod.Bridge()
    routes = web.RouteTableDef()
    b.add_routes(routes)
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PORT).start()

    async with aiohttp.ClientSession() as s:
        r = await s.get(URL + "/ayon/info")
        info = await r.json()
        check(info == {"name": "ayon-comfyui", "protocols": [1],
                       "features": []}, "info")
        r = await s.get(URL + "/ayon/pair")
        page = await r.text()
        check("ayon.bridge.pair_code" in page
              and r.headers.get("Cache-Control") == "no-store", "pair page")

        secret = secrets.token_urlsafe(32)
        host, welcome = await host_connect(s, secret, {"user": "alice"})
        check(welcome["type"] == "welcome"
              and welcome["peer"]["connected"] is False
              and welcome["features"] == [], "host welcome")
        sid = welcome["session"]

        # request without a tab
        await host.send_json({"type": "request", "id": "h1",
                              "method": "getWorkfile", "params": {}})
        resp = await recv(host)
        check(resp.get("error", {}).get("code") == "no_tab", "no_tab error")

        code = await get_code(host)
        tab, tw = await tab_connect(s, pair_code=code)
        check(tw["type"] == "welcome" and tw["peer"]["connected"]
              and tw["peer"]["info"] == {"user": "alice"}, "tab welcome")
        cred = tw["credential"]
        check(cred["session"] == sid, "credential session")
        ev = await recv(host)
        check(ev == {"type": "peer", "connected": True}, "host sees tab")

        # host -> tab request/response
        await host.send_json({"type": "request", "id": "h2",
                              "method": "getWorkfile", "params": {"a": 1}})
        req = await recv(tab)
        check(req["id"] == "h2" and req["params"] == {"a": 1}, "relay req")
        # forged response for an id that was never requested is dropped
        await tab.send_json({"type": "response", "id": "nope",
                             "result": "x"})
        await tab.send_json({"type": "response", "id": "h2",
                             "result": "graph"})
        resp = await recv(host)
        check(resp == {"type": "response", "id": "h2", "result": "graph"},
              "relay resp (forged one dropped)")
        # a second response with the same id is dropped too
        await tab.send_json({"type": "response", "id": "h2",
                             "result": "again"})
        # tab -> host request
        await tab.send_json({"type": "request", "id": "t1",
                             "method": "requestToolByName",
                             "params": {"tool_name": "loader"}})
        req = await recv(host)
        check(req["id"] == "t1" and req["method"] == "requestToolByName",
              "tab->host req (duplicate resp dropped)")
        await host.send_json({"type": "response", "id": "t1",
                              "result": "ok"})
        resp = await recv(tab)
        check(resp.get("result") == "ok", "tab->host resp")

        # reusing the pairing code shortly after works (lost welcome)
        tab_b, tbw = await tab_connect(s, pair_code=code)
        check(tbw["type"] == "welcome", "pair code reuse within window")
        closed = await recv(tab)
        check(closed.get("code") == 4003, "old tab superseded (4003)")
        await recv(host)  # peer connected for tab_b

        # pending request to the superseded tab errors out
        await host.send_json({"type": "request", "id": "h3",
                              "method": "slow", "params": {}})
        await recv(tab_b)
        tab_c, tcw = await tab_connect(s, credential=cred)
        check(tcw["type"] == "welcome", "credential rejoin")
        resp = await recv(host)
        check(resp.get("id") == "h3"
              and resp["error"]["code"] == "tab_disconnected",
              "pending request fails on supersede")
        ev = await recv(host)
        check(ev == {"type": "peer", "connected": True},
              "peer connected after supersede")
        closed = await recv(tab_b)
        check(closed.get("code") == 4003, "tab_b superseded")

        # wrong credential / unknown session / bad protocol / bad code
        t, r = await tab_connect(s, credential={"session": sid, "sig": "x"})
        check(r.get("code") == 4001, "forged credential rejected")
        t, r = await tab_connect(
            s, credential={"session": "0" * 32, "sig": "x"})
        check(r.get("code") == 4004, "unknown session 4004")
        t, r = await tab_connect(s, pair_code="bogus")
        check(r.get("code") == 4001, "bogus pair code rejected")
        ws = await s.ws_connect(WS)
        await ws.send_json({"type": "hello", "role": "host",
                            "protocol": 99, "secret": secret})
        r = await recv(ws)
        check(r.get("code") == 4001 and b"protocol" in r["extra"].encode(),
              "protocol mismatch rejected with reason")
        ws = await s.ws_connect(WS)
        await ws.send_json({"type": "hello", "role": "host", "protocol": 1,
                            "secret": "short"})
        r = await recv(ws)
        check(r.get("code") == 4001, "short secret rejected")

        # second session can't reach the first one's tab
        secret2 = secrets.token_urlsafe(32)
        host2, w2 = await host_connect(s, secret2, {"user": "bob"})
        check(w2["session"] != sid and not w2["peer"]["connected"],
              "second session isolated")
        await host2.send_json({"type": "request", "id": "x1",
                               "method": "getWorkfile", "params": {}})
        r = await recv(host2)
        check(r.get("error", {}).get("code") == "no_tab",
              "host2 can't reach tab1")
        # tab credential of session 1 doesn't work for session 2
        t, r = await tab_connect(s, credential={
            "session": w2["session"], "sig": cred["sig"]})
        check(r.get("code") == 4001, "cross-session credential rejected")

        # host disconnect -> tab notified, tab request gets no_host
        await host.close()
        ev = await recv(tab_c)
        check(ev == {"type": "peer", "connected": False},
              "tab sees host leave")
        await tab_c.send_json({"type": "request", "id": "t2",
                               "method": "requestToolByName", "params": {}})
        r = await recv(tab_c)
        check(r.get("error", {}).get("code") == "no_host", "no_host error")
        # host reconnects with same secret -> same session, tab notified
        host, w = await host_connect(s, secret, {"user": "alice"})
        check(w["session"] == sid and w["peer"]["connected"],
              "host rejoins same session")
        ev = await recv(tab_c)
        check(ev.get("type") == "peer" and ev["connected"],
              "tab sees host rejoin")

        # tab closes with a request in flight -> host gets error
        await host.send_json({"type": "request", "id": "h4",
                              "method": "slow", "params": {}})
        await recv(tab_c)
        await tab_c.close()
        r = await recv(host)
        check(r.get("id") == "h4"
              and r["error"]["code"] == "tab_disconnected",
              "in-flight request fails on tab close")
        ev = await recv(host)
        check(ev == {"type": "peer", "connected": False},
              "host sees tab leave")

        # large frame (> aiohttp's 4 MB default) is relayed
        tab_d, _ = await tab_connect(s, credential=cred)
        await recv(host)
        big = "x" * (6 * 1024 * 1024)
        await host.send_json({"type": "request", "id": "h5",
                              "method": "loadWorkfile",
                              "params": {"workfile_json": big}})
        req = await recv(tab_d, timeout=10)
        check(len(req["params"]["workfile_json"]) == len(big),
              "6 MB frame relayed")

        # a late host answer to a superseded tab's request must not reach
        # the new tab (which may reuse the same request id)
        await tab_d.send_json({"type": "request", "id": "same-1",
                               "method": "requestToolByName", "params": {}})
        await recv_until(host, lambda f: f.get("id") == "same-1")
        tab_e, _ = await tab_connect(s, credential=cred)
        await recv_until(host, lambda f: f.get("type") == "peer")
        await host.send_json({"type": "response", "id": "same-1",
                              "result": "late"})
        await tab_e.send_json({"type": "request", "id": "same-1",
                               "method": "requestToolByName", "params": {}})
        await recv_until(host, lambda f: f.get("type") == "request")
        await host.send_json({"type": "response", "id": "same-1",
                              "result": "fresh"})
        got = await recv_until(tab_e, lambda f: f.get("type") == "response")
        check(got.get("result") == "fresh",
              "late answer for superseded tab dropped")
        # a response with an unhashable id doesn't kill the connection
        await tab_e.send_json({"type": "response", "id": ["x"],
                               "result": 1})
        await tab_e.send_json({"type": "request", "id": "after",
                               "method": "ping", "params": {}})
        req = await recv_until(host, lambda f: f.get("type") == "request")
        check(req.get("id") == "after", "unhashable id ignored")

        # hello timeout
        bridge_mod.HELLO_TIMEOUT = 0.5
        ws = await s.ws_connect(WS)
        r = await recv(ws)
        check(r.get("code") == 4001, "hello timeout closes")

        # expired pair code (reuse window)
        bridge_mod.PAIR_CODE_REUSE = 0.2
        code2 = await get_code(host)
        t1, r1 = await tab_connect(s, pair_code=code2)
        await asyncio.sleep(0.4)
        t2, r2 = await tab_connect(s, pair_code=code2)
        check(r1["type"] == "welcome" and r2.get("code") == 4001,
              "pair code expires after reuse window")

    await runner.cleanup()
    print("FAILURES:", FAILS or "none")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
