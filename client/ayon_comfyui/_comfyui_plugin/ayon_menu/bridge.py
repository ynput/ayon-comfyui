"""AYON bridge: relay between an AYON session and its paired ComfyUI tab.

The routes are registered on ComfyUI's own server (custom routes API), so
both the AYON host process (a Python websocket client) and the browser tab
(same origin as the ComfyUI page) connect to ComfyUI. AYON itself does not
listen on any port and the browser never talks to the artist's machine.

The relay authenticates both sides, binds one tab to one AYON session and
forwards `request`/`response` frames between them. It never interprets the
RPC methods themselves.

Protocol (JSON text frames):

- The first frame of a connection must be a `hello`:
    - host:     {type: hello, role: host, protocol, secret, info}
    - tab:      {type: hello, role: tab, protocol, pair_code | credential}
  The server answers with a `welcome`, or closes the connection.
- Host only: {type: pair_code} -> {type: pair_code, code, expires_in}
  The host opens `/ayon/pair#code=<code>` in the browser; the tab trades the
  one-time code for a credential it keeps in its `sessionStorage`.
- Relayed both ways:
    {type: request, id, method, params}
    {type: response, id, result} or {type: response, id, error}
- From the server: {type: peer, connected, info}

Security model: ComfyUI itself has no authentication, so anyone who can
reach it can already queue prompts and read its user data. The bridge makes
sure nobody without the session secret, a pairing code or a tab credential
can drive an AYON session or answer its requests, and that AYON sessions
sharing one ComfyUI server never cross-talk. Nothing is broadcast.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time

from aiohttp import WSMsgType, web

log = logging.getLogger(__name__)

PROTOCOLS = (1,)
PROTOCOL = PROTOCOLS[-1]
# What this plugin offers beyond the bridge protocol itself (e.g. nodes or
# tab methods a publish needs), so AYON can tell an outdated plugin apart
# before relying on them. Reported by `/ayon/info` and in the host welcome.
#
# - "publish-v1": save nodes write `AYON/<instance>/<prompt>/` and report
#   their files in an `ayon` UI output; the tab answers `getApiPrompt` and
#   `getQueuedPrompts` (host-driven publishing).
# - "paths-v1": `/ayon/paths/check` and load nodes reading AYON rootless
#   path references.
FEATURES: tuple[str, ...] = ("publish-v1", "paths-v1")

HELLO_TIMEOUT = 10.0
HEARTBEAT = 30.0
MAX_MSG_SIZE = 64 * 1024 * 1024
PAIR_CODE_TTL = 600.0
# A used pairing code stays valid a little longer, so a tab that reloads
# before it received its `welcome` isn't stranded.
PAIR_CODE_REUSE = 60.0
HOSTLESS_SESSION_TTL = 300.0
MAX_SESSIONS = 256
MAX_PAIR_CODES_PER_SESSION = 8
MAX_PENDING = 1024
MAX_ID_LENGTH = 128
MAX_INFO_SIZE = 16 * 1024

CLOSE_REJECTED = 4001
CLOSE_SUPERSEDED = 4003
CLOSE_UNKNOWN_SESSION = 4004

PAIR_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>AYON - ComfyUI</title>
</head>
<body>
<p>Connecting ComfyUI to AYON&hellip;</p>
<script>
(function () {
  try {
    var code = new URLSearchParams(location.hash.slice(1)).get("code");
    if (code) {
      // The tab trades it for a credential once ComfyUI loaded; a
      // credential it already has stays until the code is accepted.
      sessionStorage.setItem("ayon.bridge.pair_code", code);
    }
  } catch (err) {
    console.error("AYON: unable to store pairing code", err);
  }
  location.replace(new URL("../", location.href).href);
})();
</script>
</body>
</html>
"""


def session_id_from_secret(secret: str) -> str:
    """Return the public session id for a host secret."""
    digest = hashlib.sha256(f"ayon-comfyui-session:{secret}".encode())
    return digest.hexdigest()[:32]


def tab_signature(secret: str) -> str:
    """Return the signature a tab presents to rejoin a session."""
    return hmac.new(secret.encode(), b"tab", hashlib.sha256).hexdigest()


class Session:
    """One AYON session: a host connection and at most one bound tab."""

    def __init__(self, session_id: str, secret: str) -> None:
        self.id = session_id
        self.secret = secret
        self.host: web.WebSocketResponse | None = None
        self.tab: web.WebSocketResponse | None = None
        self.host_info: dict = {}
        self.host_left_at: float | None = time.monotonic()
        # Ids of relayed requests that still await a response, per
        # direction: requests sent *to* the tab / *to* the host.
        self.pending = {"tab": set(), "host": set()}

    def peer(self, role: str) -> web.WebSocketResponse | None:
        return self.tab if role == "host" else self.host


class Bridge:
    """Session registry and frame relay."""

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        # code -> [session id, expires at, first used at]
        self.pair_codes: dict[str, list] = {}
        self._janitor: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

    # --- routes -----------------------------------------------------------

    def add_routes(self, routes: web.RouteTableDef) -> None:
        """Register the bridge routes."""
        routes.get("/ayon/info")(self.handle_info)
        routes.get("/ayon/pair")(self.handle_pair_page)
        routes.get("/ayon/ws")(self.handle_ws)

    async def handle_info(self, request: web.Request) -> web.Response:
        """Let AYON check the plugin is installed and compatible."""
        return web.json_response(
            {
                "name": "ayon-comfyui",
                "protocols": list(PROTOCOLS),
                "features": list(FEATURES),
            },
            headers={"Cache-Control": "no-store"},
        )

    async def handle_pair_page(self, request: web.Request) -> web.Response:
        """Move the pairing code into the tab's sessionStorage."""
        return web.Response(
            text=PAIR_PAGE,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """Authenticate a host or tab connection, then relay its frames."""
        self._ensure_janitor()
        ws = web.WebSocketResponse(
            heartbeat=HEARTBEAT, max_msg_size=MAX_MSG_SIZE
        )
        await ws.prepare(request)

        try:
            msg = await ws.receive(timeout=HELLO_TIMEOUT)
        except asyncio.TimeoutError:
            await _close(ws, CLOSE_REJECTED, "No hello received")
            return ws

        hello = _parse(msg)
        if hello is None or hello.get("type") != "hello":
            await _close(ws, CLOSE_REJECTED, "Expected a hello")
            return ws

        if hello.get("protocol") not in PROTOCOLS:
            await _close(
                ws,
                CLOSE_REJECTED,
                f"Unsupported protocol {hello.get('protocol')!r}, this "
                f"ComfyUI plugin supports {list(PROTOCOLS)}",
            )
            return ws

        role = hello.get("role")
        if role == "host":
            session = await self._accept_host(ws, hello)
        elif role == "tab":
            session = await self._accept_tab(ws, hello)
        else:
            await _close(ws, CLOSE_REJECTED, "Unknown role")
            return ws

        if session is None:
            return ws

        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                await self._on_frame(session, role, ws, msg.data)
        finally:
            await self._detach(session, role, ws)
        return ws

    # --- connection setup -------------------------------------------------

    async def _accept_host(
        self, ws: web.WebSocketResponse, hello: dict
    ) -> Session | None:
        secret = hello.get("secret")
        if not isinstance(secret, str) or not 32 <= len(secret) <= 256:
            await _close(ws, CLOSE_REJECTED, "Invalid session secret")
            return None

        session_id = session_id_from_secret(secret)
        session = self.sessions.get(session_id)
        if session is None:
            self._end_sessions(self._purge())
            if len(self.sessions) >= MAX_SESSIONS:
                await _close(ws, CLOSE_REJECTED, "Too many AYON sessions")
                return None
            session = Session(session_id, secret)
            self.sessions[session_id] = session
            log.info("AYON session %s created", session_id[:8])

        info = hello.get("info")
        if (
            isinstance(info, dict)
            and len(json.dumps(info)) <= MAX_INFO_SIZE
        ):
            session.host_info = info
        session.host_left_at = None
        await self._attach(session, "host", ws)

        await _send(ws, {
            "type": "welcome",
            "protocol": PROTOCOL,
            "session": session.id,
            "features": list(FEATURES),
            "peer": {"connected": session.tab is not None},
        })
        await _send(session.tab, {
            "type": "peer", "connected": True, "info": session.host_info,
        })
        log.info("AYON session %s: host connected", session.id[:8])
        return session

    async def _accept_tab(
        self, ws: web.WebSocketResponse, hello: dict
    ) -> Session | None:
        session = None
        code = hello.get("pair_code")
        credential = hello.get("credential")
        if isinstance(code, str):
            session_id = self._consume_pair_code(code)
            if session_id is None:
                await _close(
                    ws, CLOSE_REJECTED, "Invalid or expired pairing code"
                )
                return None
            session = self.sessions.get(session_id)
        elif isinstance(credential, dict):
            session = self.sessions.get(str(credential.get("session")))
            signature = credential.get("sig")
            if session is not None and not (
                isinstance(signature, str)
                and hmac.compare_digest(
                    signature, tab_signature(session.secret)
                )
            ):
                await _close(ws, CLOSE_REJECTED, "Invalid credential")
                return None
        else:
            await _close(ws, CLOSE_REJECTED, "Missing pairing code")
            return None

        if session is None:
            # Retryable: e.g. ComfyUI restarted and the AYON host didn't
            # register its session again yet.
            await _close(ws, CLOSE_UNKNOWN_SESSION, "Unknown AYON session")
            return None

        await self._attach(session, "tab", ws)
        await _send(ws, {
            "type": "welcome",
            "protocol": PROTOCOL,
            "session": session.id,
            "credential": {
                "session": session.id,
                "sig": tab_signature(session.secret),
            },
            "peer": {
                "connected": session.host is not None,
                "info": session.host_info,
            },
        })
        await _send(session.host, {"type": "peer", "connected": True})
        log.info("AYON session %s: tab connected", session.id[:8])
        return session

    def _consume_pair_code(self, code: str) -> str | None:
        entry = self.pair_codes.get(code)
        if entry is None:
            return None
        session_id, expires_at, first_used = entry
        now = time.monotonic()
        if now > expires_at or (
            first_used is not None and now - first_used > PAIR_CODE_REUSE
        ):
            self.pair_codes.pop(code, None)
            return None
        if first_used is None:
            entry[2] = now
        return session_id

    async def _attach(
        self, session: Session, role: str, ws: web.WebSocketResponse
    ) -> None:
        """Make `ws` the session's connection for `role` (newest wins)."""
        old = session.host if role == "host" else session.tab
        if role == "host":
            session.host = ws
        else:
            session.tab = ws
        if old is not None and old is not ws:
            # Before awaiting anything, so nothing the new connection sends
            # meanwhile gets forgotten.
            self._forget_requests_from(session, role)
            await self._fail_pending(session, role)
            # Don't wait for an unresponsive old peer's close handshake.
            self._spawn(_close(
                old, CLOSE_SUPERSEDED, "Superseded by a newer connection"
            ))

    async def _detach(
        self, session: Session, role: str, ws: web.WebSocketResponse
    ) -> None:
        current = session.host if role == "host" else session.tab
        if current is not ws:
            # Already superseded by a newer connection.
            return
        if role == "host":
            session.host = None
            session.host_left_at = time.monotonic()
        else:
            session.tab = None
        self._forget_requests_from(session, role)
        await self._fail_pending(session, role)
        # A new connection may have taken this role in the meantime.
        if (session.host if role == "host" else session.tab) is None:
            await _send(
                session.peer(role), {"type": "peer", "connected": False}
            )
        log.info("AYON session %s: %s disconnected", session.id[:8], role)

    def _forget_requests_from(self, session: Session, role: str) -> None:
        """Forget requests made by the connection for `role` that left.

        Their answers must not reach whoever takes its place, which may
        use the same request ids (e.g. a reloaded tab).
        """
        other = "tab" if role == "host" else "host"
        session.pending[other].clear()

    async def _fail_pending(self, session: Session, role: str) -> None:
        """Error all requests that the connection for `role` won't answer."""
        pending = session.pending[role]
        if not pending:
            return
        ids = list(pending)
        pending.clear()
        requester = session.peer(role)
        error = {
            "code": f"{role}_disconnected",
            "message": (
                "The ComfyUI tab disconnected before it answered."
                if role == "tab"
                else "AYON disconnected before it answered."
            ),
        }
        for request_id in ids:
            await _send(requester, {
                "type": "response", "id": request_id, "error": error,
            })

    # --- relay ------------------------------------------------------------

    async def _on_frame(
        self,
        session: Session,
        role: str,
        ws: web.WebSocketResponse,
        text: str,
    ) -> None:
        frame = _parse_text(text)
        if frame is None:
            return
        kind = frame.get("type")
        if kind == "request":
            await self._relay_request(session, role, ws, frame, text)
        elif kind == "response":
            await self._relay_response(session, role, frame, text)
        elif kind == "pair_code" and role == "host":
            # Keep only the newest few codes of a session.
            codes = [
                code
                for code, entry in self.pair_codes.items()
                if entry[0] == session.id
            ]
            excess = len(codes) - MAX_PAIR_CODES_PER_SESSION + 1
            for code in codes[:max(0, excess)]:
                del self.pair_codes[code]
            code = secrets.token_urlsafe(18)
            self.pair_codes[code] = [
                session.id, time.monotonic() + PAIR_CODE_TTL, None
            ]
            await _send(ws, {
                "type": "pair_code",
                "code": code,
                "expires_in": PAIR_CODE_TTL,
            })

    async def _relay_request(
        self,
        session: Session,
        role: str,
        ws: web.WebSocketResponse,
        frame: dict,
        text: str,
    ) -> None:
        request_id = frame.get("id")
        if not isinstance(request_id, str) or not (
            0 < len(request_id) <= MAX_ID_LENGTH
        ):
            return
        target_role = "tab" if role == "host" else "host"
        target = session.peer(role)
        pending = session.pending[target_role]
        error = None
        if target is None:
            error = {
                "code": f"no_{target_role}",
                "message": (
                    "No ComfyUI tab is connected to this AYON session."
                    if target_role == "tab"
                    else "AYON is not connected."
                ),
            }
        elif len(pending) >= MAX_PENDING:
            error = {"code": "busy", "message": "Too many pending requests."}

        if error is not None:
            await _send(ws, {
                "type": "response", "id": request_id, "error": error,
            })
            return

        pending.add(request_id)
        if not await _send_text(target, text):
            pending.discard(request_id)
            await _send(ws, {
                "type": "response",
                "id": request_id,
                "error": {
                    "code": f"{target_role}_disconnected",
                    "message": f"Unable to reach the {target_role}.",
                },
            })

    async def _relay_response(
        self, session: Session, role: str, frame: dict, text: str
    ) -> None:
        # Only forward answers to requests this connection actually got,
        # so nobody can inject results for other requests.
        pending = session.pending[role]
        request_id = frame.get("id")
        if not isinstance(request_id, str) or request_id not in pending:
            return
        pending.discard(request_id)
        await _send_text(session.peer(role), text)

    # --- housekeeping -----------------------------------------------------

    def _ensure_janitor(self) -> None:
        if self._janitor is None or self._janitor.done():
            self._janitor = asyncio.get_running_loop().create_task(
                self._janitor_loop()
            )

    async def _janitor_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            self._end_sessions(self._purge())

    def _end_sessions(self, sessions: list[Session]) -> None:
        for session in sessions:
            self._spawn(_close(
                session.tab, CLOSE_UNKNOWN_SESSION, "AYON session ended"
            ))

    def _spawn(self, coro) -> None:  # noqa: ANN001
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _purge(self) -> list[Session]:
        """Drop expired pairing codes and sessions whose host left."""
        now = time.monotonic()
        for code, (_, expires_at, first_used) in list(
            self.pair_codes.items()
        ):
            if now > expires_at or (
                first_used is not None and now - first_used > PAIR_CODE_REUSE
            ):
                del self.pair_codes[code]

        expired = [
            session
            for session in self.sessions.values()
            if session.host is None
            and session.host_left_at is not None
            and now - session.host_left_at > HOSTLESS_SESSION_TTL
        ]
        for session in expired:
            del self.sessions[session.id]
            log.info("AYON session %s expired", session.id[:8])
        return expired


def _parse(msg) -> dict | None:  # noqa: ANN001
    if msg.type != WSMsgType.TEXT:
        return None
    return _parse_text(msg.data)


def _parse_text(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def _send(ws: web.WebSocketResponse | None, data: dict) -> bool:
    return await _send_text(ws, json.dumps(data))


async def _send_text(ws: web.WebSocketResponse | None, text: str) -> bool:
    if ws is None or ws.closed:
        return False
    try:
        await ws.send_str(text)
    except (ConnectionError, RuntimeError):
        return False
    return True


async def _close(
    ws: web.WebSocketResponse | None, code: int, reason: str
) -> None:
    if ws is None or ws.closed:
        return
    # Websocket close reasons are limited to 123 bytes.
    await ws.close(code=code, message=reason.encode()[:123])


BRIDGE = Bridge()
