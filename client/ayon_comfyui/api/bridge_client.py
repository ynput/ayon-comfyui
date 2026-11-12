"""Websocket client that connects an AYON session to ComfyUI.

AYON is a client of the AYON bridge routes that the ComfyUI plugin adds to
ComfyUI's own server (see `_comfyui_plugin/ayon_menu/bridge.py`), so AYON
does not need to listen on any port. The ComfyUI tab that AYON opens is
paired with this session and the relay forwards requests between them.

This module has no Qt or AYON dependencies, so it can be used and tested on
its own. All network activity runs on a private asyncio loop in a daemon
thread; `call()` and the other public methods are thread-safe.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import itertools
import json
import logging
import secrets
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

log = logging.getLogger(__name__)

PROTOCOL = 1
MAX_MSG_SIZE = 64 * 1024 * 1024
HEARTBEAT = 30.0
RECONNECT_DELAYS = (0.5, 1.0, 2.0, 3.0, 5.0)

CLOSE_REJECTED = 4001
CLOSE_SUPERSEDED = 4003

Handler = Callable[[dict], Any]
EventCallback = Callable[[str, dict], None]


class BridgeError(RuntimeError):
    """Raised when a bridge call can't be completed."""

    def __init__(self, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


def join_url(base_url: str, path: str, *, websocket: bool = False) -> str:
    """Join `path` onto a ComfyUI base URL, keeping any sub-path."""
    parts = urlsplit(base_url)
    scheme = parts.scheme
    if websocket:
        scheme = {"http": "ws", "https": "wss"}.get(scheme, scheme)
    return urlunsplit(
        (scheme, parts.netloc, parts.path.rstrip("/") + path, "", "")
    )


def check_plugin(base_url: str, timeout: float = 5.0) -> dict:
    """Check the AYON plugin is installed on ComfyUI and compatible.

    Returns:
        The plugin info reported by `/ayon/info`.

    Raises:
        BridgeError: With code `unreachable`, `no_plugin` or `incompatible`.
    """
    url = join_url(base_url, "/ayon/info")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            info = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # noqa: PLR2004
            msg = (
                f"ComfyUI at {base_url} does not have the AYON plugin, or "
                "it is outdated. Install or update the AYON ComfyUI plugin "
                "on that ComfyUI server."
            )
            raise BridgeError(msg, "no_plugin") from exc
        msg = f"ComfyUI at {base_url} answered with HTTP {exc.code}."
        raise BridgeError(msg, "unreachable") from exc
    except (OSError, ValueError) as exc:
        msg = f"Unable to reach ComfyUI at {base_url}: {exc}"
        raise BridgeError(msg, "unreachable") from exc

    protocols = info.get("protocols") if isinstance(info, dict) else None
    if not isinstance(protocols, list) or PROTOCOL not in protocols:
        msg = (
            f"The AYON plugin on ComfyUI at {base_url} supports protocol(s) "
            f"{protocols}, but this AYON addon needs protocol {PROTOCOL}. "
            "Update the AYON ComfyUI plugin on that ComfyUI server to the "
            "version shipped with this addon."
        )
        raise BridgeError(msg, "incompatible")
    return info


class BridgeClient:
    """AYON host connection to the ComfyUI bridge.

    Args:
        base_url: ComfyUI URL, e.g. `http://127.0.0.1:8188` or
            `https://comfy.studio.com/sub/path`.
        info: Session info shown in the paired tab (user, project, ...).
        on_event: Called from the bridge thread with an event name and data:
            `connected`, `disconnected`, `tab_connected`, `tab_disconnected`
            and `rejected` (fatal, the client stops reconnecting).
        ssl: Passed to aiohttp when set. By default aiohttp verifies the
            certificate against the system's trusted CAs.
    """

    def __init__(
        self,
        base_url: str,
        *,
        info: dict | None = None,
        on_event: EventCallback | None = None,
        ssl: Any = None,  # noqa: ANN401
    ) -> None:
        self.base_url = base_url
        self.ws_url = join_url(base_url, "/ayon/ws", websocket=True)
        self.secret = secrets.token_urlsafe(32)
        self.info = info or {}
        self._on_event = on_event
        self._ssl = ssl

        self._handlers: dict[str, Handler] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)
        self._id_prefix = secrets.token_hex(3)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._stopping = False
        self._ready = threading.Event()
        self._registered = False
        self._tab_connected = False
        self.session_id: str | None = None

    # --- state ------------------------------------------------------------

    @property
    def registered(self) -> bool:
        """Whether the session is registered with ComfyUI right now."""
        return self._registered

    @property
    def tab_connected(self) -> bool:
        """Whether a ComfyUI tab is paired and connected right now."""
        return self._registered and self._tab_connected

    def pairing_url(self, code: str) -> str:
        """Return the URL that pairs a browser tab using `code`."""
        return join_url(self.base_url, "/ayon/pair") + f"#code={code}"

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Start connecting (and reconnecting) in a background thread."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._thread_main, name="AYON-ComfyUI-bridge", daemon=True
        )
        self._thread.start()
        self._ready.wait()

    def stop(self, timeout: float = 5.0) -> None:
        """Disconnect and stop the background thread."""
        self._stopping = True
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        async def _close() -> None:
            if self._ws is not None and not self._ws.closed:
                await self._ws.close()

        try:
            asyncio.run_coroutine_threadsafe(_close(), loop).result(timeout)
        except Exception:  # noqa: BLE001
            log.debug("Error while closing the bridge", exc_info=True)
        if self._thread is not None:
            self._thread.join(timeout)

    def register_handler(self, method: str, handler: Handler) -> None:
        """Handle requests for `method` coming from the ComfyUI tab.

        The handler gets the request params and returns a JSON-serializable
        result. It runs in a worker thread, never on the Qt main thread.
        """
        self._handlers[method] = handler

    # --- calls ------------------------------------------------------------

    def call(
        self,
        method: str,
        params: dict | None = None,
        timeout: float | None = 10.0,
    ) -> Any:  # noqa: ANN401
        """Call `method` in the paired ComfyUI tab and return its result.

        Raises:
            BridgeError: When no tab is connected, the tab reports an error,
                the connection drops or the call times out.
        """
        loop = self._loop
        if loop is None or not self._registered or self._ws is None:
            msg = "Not connected to ComfyUI."
            raise BridgeError(msg, "not_connected")
        if threading.current_thread() is self._thread:
            msg = "call() can't be used from the bridge thread."
            raise BridgeError(msg, "deadlock")
        future = asyncio.run_coroutine_threadsafe(
            self._call(method, params or {}), loop
        )
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            msg = f"ComfyUI didn't answer '{method}' within {timeout} s."
            raise BridgeError(msg, "timeout") from exc

    def request_pair_code(self, timeout: float = 10.0) -> str:
        """Ask the relay for a one-time code to pair a ComfyUI tab."""
        loop = self._loop
        if loop is None or not self._registered:
            msg = "Not connected to ComfyUI."
            raise BridgeError(msg, "not_connected")
        future = asyncio.run_coroutine_threadsafe(
            self._call(None, {}), loop
        )
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            msg = "ComfyUI didn't hand out a pairing code."
            raise BridgeError(msg, "timeout") from exc

    async def _call(self, method: str | None, params: dict) -> Any:  # noqa: ANN401
        ws = self._ws
        if ws is None or ws.closed:
            msg = "Not connected to ComfyUI."
            raise BridgeError(msg, "not_connected")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        if method is None:
            # The relay answers `pair_code` frames itself.
            request_id = "pair_code"
            frame = {"type": "pair_code"}
        else:
            request_id = f"{self._id_prefix}-{next(self._ids)}"
            frame = {
                "type": "request",
                "id": request_id,
                "method": method,
                "params": params,
            }
        self._pending[request_id] = future
        try:
            await ws.send_str(json.dumps(frame))
            return await future
        finally:
            self._pending.pop(request_id, None)

    # --- connection -------------------------------------------------------

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_until_complete(self._run())
        finally:
            self._loop.close()

    async def _run(self) -> None:
        attempt = 0
        # Only pass `ssl` when set: aiohttp < 3.9 treats `ssl=True` as
        # "don't verify the certificate".
        ssl_kwargs = {} if self._ssl is None else {"ssl": self._ssl}
        async with aiohttp.ClientSession() as session:
            while not self._stopping:
                try:
                    async with session.ws_connect(
                        self.ws_url,
                        heartbeat=HEARTBEAT,
                        max_msg_size=MAX_MSG_SIZE,
                        **ssl_kwargs,
                    ) as ws:
                        self._ws = ws
                        attempt = 0
                        fatal = await self._session(ws)
                        if fatal:
                            return
                except (
                    aiohttp.ClientError, OSError, asyncio.TimeoutError
                ) as exc:
                    log.debug("Unable to connect to %s: %s", self.ws_url, exc)
                except Exception:
                    # Never let an unexpected error end the reconnect loop.
                    log.exception("Unexpected error in the ComfyUI connection")
                finally:
                    self._ws = None
                    self._disconnected()

                if self._stopping:
                    return
                delay = RECONNECT_DELAYS[
                    min(attempt, len(RECONNECT_DELAYS) - 1)
                ]
                attempt += 1
                await asyncio.sleep(delay)

    async def _session(self, ws: aiohttp.ClientWebSocketResponse) -> bool:
        """Run one connection. Returns True when reconnecting is pointless."""
        await ws.send_str(json.dumps({
            "type": "hello",
            "role": "host",
            "protocol": PROTOCOL,
            "secret": self.secret,
            "info": self.info,
        }))
        closing = {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        }
        while True:
            msg = await ws.receive()
            if msg.type in closing:
                break
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                frame = json.loads(msg.data)
            except ValueError:
                continue
            if not isinstance(frame, dict):
                continue
            try:
                await self._on_frame(ws, frame)
            except Exception:
                log.exception("Unable to handle a message from ComfyUI")

        code = ws.close_code
        if code in {CLOSE_REJECTED, CLOSE_SUPERSEDED}:
            reason = msg.extra if isinstance(msg.extra, str) else ""
            log.error(
                "ComfyUI rejected the AYON session (%s): %s", code, reason
            )
            self._emit("rejected", {"code": code, "reason": reason})
            return True
        return False

    async def _on_frame(
        self, ws: aiohttp.ClientWebSocketResponse, frame: dict
    ) -> None:
        kind = frame.get("type")
        if kind == "welcome":
            self.session_id = frame.get("session")
            self._registered = True
            self._tab_connected = bool(frame.get("peer", {}).get("connected"))
            log.info("Connected to ComfyUI at %s", self.base_url)
            self._emit("connected", {"tab_connected": self._tab_connected})
        elif kind == "peer":
            connected = bool(frame.get("connected"))
            if connected != self._tab_connected:
                self._tab_connected = connected
                self._emit(
                    "tab_connected" if connected else "tab_disconnected", {}
                )
        elif kind == "pair_code":
            self._resolve("pair_code", result=frame.get("code"))
        elif kind == "response":
            self._resolve(
                frame.get("id"),
                result=frame.get("result"),
                error=frame.get("error"),
            )
        elif kind == "request":
            asyncio.get_running_loop().create_task(
                self._handle_request(ws, frame)
            )

    def _resolve(
        self, request_id: Any, result: Any = None, error: Any = None  # noqa: ANN401
    ) -> None:
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        if error:
            if isinstance(error, dict):
                exc = BridgeError(
                    str(error.get("message") or error),
                    str(error.get("code") or "error"),
                )
            else:
                exc = BridgeError(str(error))
            future.set_exception(exc)
        else:
            future.set_result(result)

    async def _handle_request(
        self, ws: aiohttp.ClientWebSocketResponse, frame: dict
    ) -> None:
        request_id = frame.get("id")
        method = frame.get("method")
        handler = self._handlers.get(method)
        response: dict = {"type": "response", "id": request_id}
        if handler is None:
            response["error"] = {
                "code": "unknown_method",
                "message": f"AYON doesn't handle '{method}'.",
            }
        else:
            params = frame.get("params")
            if not isinstance(params, dict):
                params = {}
            try:
                if inspect.iscoroutinefunction(handler):
                    result = await handler(params)
                else:
                    result = await asyncio.get_running_loop().run_in_executor(
                        None, handler, params
                    )
                response["result"] = result
            except Exception as exc:  # noqa: BLE001
                log.warning("AYON failed to handle '%s'", method,
                            exc_info=True)
                response["error"] = {"code": "error", "message": str(exc)}
        if not ws.closed:
            try:
                await ws.send_str(json.dumps(response))
            except (ConnectionError, RuntimeError):
                log.debug("Unable to answer '%s'", method, exc_info=True)

    def _disconnected(self) -> None:
        was_registered = self._registered
        self._registered = False
        self._tab_connected = False
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(BridgeError(
                    "Lost the connection to ComfyUI.", "disconnected"
                ))
        if was_registered and not self._stopping:
            log.warning("Lost the connection to ComfyUI at %s", self.base_url)
            self._emit("disconnected", {})

    def _emit(self, event: str, data: dict) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(event, data)
        except Exception:  # noqa: BLE001
            log.exception("Error in bridge event callback '%s'", event)
