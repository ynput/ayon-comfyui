"""Tests for the AYON host BridgeClient against the relay (no ComfyUI).

Runs the relay of the ComfyUI plugin in a plain aiohttp app on localhost.
Needs Python 3.9+ with aiohttp, e.g. ComfyUI's embedded Python:

    python tests/bridge/test_client.py [<relay bridge.py> <bridge_client.py>]
"""

import asyncio
import importlib.util
import json
import socket
import sys
import threading
import time
from pathlib import Path

import aiohttp
from aiohttp import web


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


REPO = Path(__file__).resolve().parents[2]
RELAY_PATH = REPO / "client/ayon_comfyui/_comfyui_plugin/ayon_menu/bridge.py"
CLIENT_PATH = REPO / "client/ayon_comfyui/api/bridge_client.py"
if len(sys.argv) > 2:
    RELAY_PATH, CLIENT_PATH = Path(sys.argv[1]), Path(sys.argv[2])

relay = load("relay", RELAY_PATH)
client_mod = load("bridge_client", CLIENT_PATH)
client_mod.RECONNECT_DELAYS = (0.2, 0.3)

PORT = 18732
BASE = f"http://127.0.0.1:{PORT}/sub"  # sub-path proxy style
FAILS = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label, flush=True)
    if not cond:
        FAILS.append(label)


class Server:
    """Relay app served under /sub in its own thread, restartable."""

    def __init__(self):
        self.bridge = relay.Bridge()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.runner = None

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(15)

    async def _start(self):
        routes = web.RouteTableDef()
        self.bridge.add_routes(routes)
        sub = web.Application()
        sub.add_routes(routes)
        app = web.Application()
        app.add_subapp("/sub", sub)
        self.runner = web.AppRunner(app, shutdown_timeout=0.5)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", PORT).start()

    def start(self):
        self.run(self._start())

    def stop(self, wipe=False):
        self.run(self.runner.cleanup())
        if wipe:  # simulate a ComfyUI restart (all state lost)
            self.bridge = relay.Bridge()


class Tab:
    """Fake browser tab: answers requests with canned results."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.ws = None
        self.session = None
        self.welcome = None
        self.requests = []
        self.events = []
        self.responses = {}

    def run(self, coro, timeout=15):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(
            timeout)

    async def _connect(self, **hello):
        self.session = self.session or aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(
            f"ws://127.0.0.1:{PORT}/sub/ayon/ws", max_msg_size=0)
        await self.ws.send_json({"type": "hello", "role": "tab",
                                 "protocol": 1, **hello})
        msg = await self.ws.receive()
        if msg.type != aiohttp.WSMsgType.TEXT:
            return {"closed": self.ws.close_code}
        self.welcome = json.loads(msg.data)
        self.loop.create_task(self._reader(self.ws))
        return self.welcome

    async def _reader(self, ws):
        async for msg in ws:
            frame = json.loads(msg.data)
            if frame["type"] == "request":
                self.requests.append(frame)
                if frame["method"] == "fail":
                    reply = {"type": "response", "id": frame["id"],
                             "error": {"code": "boom", "message": "kaput"}}
                elif frame["method"] == "slow":
                    continue
                else:
                    reply = {"type": "response", "id": frame["id"],
                             "result": {"echo": frame["params"]}}
                await ws.send_json(reply)
            elif frame["type"] == "response":
                self.responses[frame["id"]] = frame
            else:
                self.events.append(frame)

    def connect(self, **hello):
        return self.run(self._connect(**hello))

    async def _request(self, rid, method, params):
        await self.ws.send_json({"type": "request", "id": rid,
                                 "method": method, "params": params})

    def request(self, rid, method, params):
        self.run(self._request(rid, method, params))
        deadline = time.time() + 5
        while rid not in self.responses and time.time() < deadline:
            time.sleep(0.05)
        return self.responses.get(rid)

    def close(self):
        self.run(self.ws.close())


def wait_for(pred, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


def main():
    BridgeClient = client_mod.BridgeClient
    BridgeError = client_mod.BridgeError

    # check_plugin: unreachable, then ok, then 404 (no plugin)
    try:
        client_mod.check_plugin(BASE, timeout=1)
        check(False, "check_plugin unreachable")
    except BridgeError as e:
        check(e.code == "unreachable", "check_plugin unreachable")

    server = Server()
    server.start()
    info = client_mod.check_plugin(BASE)
    check(info["protocols"] == [1], "check_plugin ok (sub-path)")
    try:
        client_mod.check_plugin(f"http://127.0.0.1:{PORT}/other")
        check(False, "check_plugin no_plugin")
    except BridgeError as e:
        check(e.code == "no_plugin", "check_plugin no_plugin")

    events = []
    client = BridgeClient(BASE, info={"user": "alice"},
                          on_event=lambda e, d: events.append((e, d)))
    handled = []

    def tool_handler(params):
        handled.append((threading.current_thread().name, params))
        return "scheduled"

    def bad_handler(params):
        raise ValueError("nope")

    client.register_handler("requestToolByName", tool_handler)
    client.register_handler("bad", bad_handler)
    check(client.ws_url == f"ws://127.0.0.1:{PORT}/sub/ayon/ws", "ws url")
    client.start()
    check(wait_for(lambda: client.registered), "client registered")
    check(client.plugin_features == frozenset(), "plugin features")
    check(("connected", {"tab_connected": False}) in events,
          "connected event")

    try:
        client.call("getWorkfile")
        check(False, "no tab error")
    except BridgeError as e:
        check(e.code == "no_tab", "no tab -> BridgeError(no_tab)")

    code = client.request_pair_code()
    url = client.pairing_url(code)
    check(url == f"{BASE}/ayon/pair#code={code}", "pairing url")
    tab = Tab()
    w = tab.connect(pair_code=code)
    check(w["type"] == "welcome"
          and w["peer"]["info"] == {"user": "alice"}, "tab paired")
    check(wait_for(lambda: client.tab_connected), "client sees tab")
    cred = w["credential"]

    res = client.call("getWorkfile", {"x": 1})
    check(res == {"echo": {"x": 1}}, "call result")
    try:
        client.call("fail")
        check(False, "tab error")
    except BridgeError as e:
        check(e.code == "boom" and str(e) == "kaput", "tab error surfaces")
    try:
        client.call("slow", timeout=0.5)
        check(False, "timeout")
    except BridgeError as e:
        check(e.code == "timeout", "call timeout")

    r = tab.request("t1", "requestToolByName", {"tool_name": "loader"})
    check(r and r.get("result") == "scheduled", "tab -> host handler")
    check(handled and handled[0][1] == {"tool_name": "loader"}
          and handled[0][0] != "AYON-ComfyUI-bridge",
          "handler runs off the bridge thread")
    r = tab.request("t2", "bad", {})
    check(r and r["error"]["message"] == "nope", "handler error relayed")
    r = tab.request("t3", "unknown", {})
    check(r and r["error"]["code"] == "unknown_method", "unknown method")
    r = tab.request("t4", ["not", "a", "name"], {})
    check(r and r["error"]["code"] == "unknown_method", "non-string method")

    # In-flight call fails fast when the tab closes
    result = {}

    def slow_call():
        try:
            client.call("slow", timeout=None)
        except BridgeError as e:
            result["code"] = e.code
    t = threading.Thread(target=slow_call)
    t.start()
    time.sleep(0.3)
    tab.close()
    t.join(5)
    check(result.get("code") == "tab_disconnected",
          "in-flight call fails on tab close")
    check(wait_for(lambda: not client.tab_connected), "tab gone")

    # ComfyUI restart: relay state wiped; client re-registers, tab rejoins
    tab2 = Tab()
    tab2.connect(credential=cred)
    check(wait_for(lambda: client.tab_connected), "tab rejoined")
    events.clear()
    server.stop(wipe=True)
    check(wait_for(lambda: ("disconnected", {}) in events),
          "disconnected event")
    server.start()
    check(wait_for(lambda: client.registered, 10), "client re-registered")
    # tab reconnects with its credential after the host re-registered
    w = tab2.connect(credential=cred)
    check(w.get("type") == "welcome", "tab rebinds after restart")
    check(wait_for(lambda: client.tab_connected), "client sees rebind")
    res = client.call("getWorkfile", {"y": 2})
    check(res == {"echo": {"y": 2}}, "call works after restart")

    client.stop()
    check(not client.registered, "stopped")

    # Protocol rejection -> 'rejected' event, no reconnect loop
    client_mod.PROTOCOL = 99
    events2 = []
    c2 = BridgeClient(BASE, on_event=lambda e, d: events2.append((e, d)))
    c2.start()
    check(wait_for(lambda: any(e == "rejected" for e, _ in events2)),
          "protocol mismatch -> rejected")
    rej = [d for e, d in events2 if e == "rejected"][0]
    check("protocol" in rej["reason"], "rejected reason: " + rej["reason"])
    c2._thread.join(3)
    check(not c2._thread.is_alive(), "client stops after rejection")

    # A server that accepts connections but never answers the handshake
    attempts = []

    def silent_server():
        server = socket.socket()
        server.bind(("127.0.0.1", PORT + 1))
        server.listen()
        connections = []
        while True:
            connection, _ = server.accept()
            attempts.append(time.time())
            connections.append(connection)

    threading.Thread(target=silent_server, daemon=True).start()
    client_mod.HANDSHAKE_TIMEOUT = 0.5
    c3 = BridgeClient(f"http://127.0.0.1:{PORT + 1}")
    c3.start()
    check(wait_for(lambda: len(attempts) >= 2, 8),
          "handshake timeout: client retries")
    check(not c3.registered and c3._thread.is_alive(),
          "handshake timeout: still reconnecting")
    c3.stop(timeout=2)

    print("FAILURES:", FAILS or "none")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
