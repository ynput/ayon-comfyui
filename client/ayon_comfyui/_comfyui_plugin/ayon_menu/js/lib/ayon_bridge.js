// Connection from a ComfyUI tab to the AYON session that opened it.
//
// The tab connects to the AYON bridge websocket on its own ComfyUI server
// (`/ayon/ws`, see `ayon_menu/bridge.py`), which relays requests between the
// tab and its AYON host process. The tab never talks to the artist's machine.
//
// Pairing: AYON opens `/ayon/pair#code=...`, which stores a one-time code in
// this tab's sessionStorage and redirects to ComfyUI. The code is traded for
// a credential (also kept in sessionStorage) to reconnect after reloads.
//
// ComfyUI loads every .js file of an extension, so this module must not have
// side effects on import.

export const PROTOCOL = 1
const PAIR_CODE_KEY = "ayon.bridge.pair_code"
const CREDENTIAL_KEY = "ayon.bridge.credential"

const CLOSE_REJECTED = 4001
const CLOSE_SUPERSEDED = 4003
const CLOSE_UNKNOWN_SESSION = 4004

const RECONNECT_DELAYS_MS = [500, 1000, 2000, 3000, 5000]
// How long to keep retrying an unknown session, e.g. while ComfyUI restarted
// and the AYON host hasn't registered its session again yet.
const UNKNOWN_SESSION_RETRY_MS = 3 * 60 * 1000

function storage_get(key) {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function storage_set(key, value) {
  try {
    window.sessionStorage.setItem(key, value)
  } catch (err) {
    console.warn("AYON: unable to use sessionStorage", err)
  }
}

function storage_remove(key) {
  try {
    window.sessionStorage.removeItem(key)
  } catch {
    // ignore
  }
}

// Random prefix for request ids, so answers meant for a previous page load
// of this tab can't be mistaken for answers to this one. (crypto.randomUUID
// is not available on plain-http LAN origins; getRandomValues is.)
function random_id_prefix() {
  const values = new Uint32Array(2)
  window.crypto.getRandomValues(values)
  return Array.from(values, (value) => value.toString(16)).join("")
}

function parse_json(text) {
  try {
    return text ? JSON.parse(text) : null
  } catch {
    return null
  }
}

// Websocket URL of the bridge for a ComfyUI `api` object; keeps the
// sub-path of ComfyUI behind a reverse proxy.
export function bridge_ws_url(api) {
  const url = new URL(api.apiURL("/ayon/ws"), window.location.href)
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  return url.href
}

// States: "not_paired", "connecting", "connected", "superseded",
// "rejected" and "ended". Listen to "change" events for updates.
export class AyonBridge extends EventTarget {
  constructor(ws_url) {
    super()
    this.ws_url = ws_url
    this.handlers = new Map()
    this.pending = new Map()
    this.next_id = 1
    this.id_prefix = random_id_prefix()
    this.ws = null
    this.state = "not_paired"
    this.reason = ""
    this.host_connected = false
    this.host_info = {}
    this.attempt = 0
    this.unknown_since = null
    this.reconnect_timer = null

    // The AYON host keeps the session info shown in the AYON panel current
    // (e.g. after switching task in the Workfiles tool).
    this.register("setSessionInfo", (info) => {
      this.host_info = info ?? {}
      this.emit()
      return true
    })
  }

  get connected() {
    return this.state === "connected" && this.host_connected
  }

  register(method, handler) {
    this.handlers.set(method, handler)
  }

  start() {
    this.connect()
  }

  // Pair this tab with a code shown by AYON (e.g. when an SSO login lost
  // the code from the launch link, or for a tab opened by hand).
  pair_with_code(code) {
    // Keep the current credential until the new code is accepted.
    storage_set(PAIR_CODE_KEY, code.trim())
    this.close_socket()
    this.reconnect_here()
  }

  close_socket() {
    const ws = this.ws
    this.ws = null
    if (ws) {
      ws.onclose = null
      ws.close()
    }
    this.reject_pending("Lost the connection to AYON.")
    this.host_connected = false
  }

  reject_pending(message) {
    for (const pending of this.pending.values()) {
      pending.reject(new Error(message))
    }
    this.pending.clear()
  }

  // Connect again after another tab took over this AYON session.
  reconnect_here() {
    this.attempt = 0
    this.unknown_since = null
    this.connect()
  }

  connect() {
    clearTimeout(this.reconnect_timer)
    const hello = {type: "hello", role: "tab", protocol: PROTOCOL}
    const code = storage_get(PAIR_CODE_KEY)
    const credential = parse_json(storage_get(CREDENTIAL_KEY))
    this.hello_with_code = !!code
    if (code) {
      hello.pair_code = code
    } else if (credential) {
      hello.credential = credential
    } else {
      this.set_state(
        "not_paired",
        "This ComfyUI tab was not opened by AYON. " +
        "Launch ComfyUI from AYON to use the AYON tools."
      )
      return
    }

    this.set_state("connecting", this.attempt ? "Reconnecting to AYON..." : "")
    let ws
    try {
      ws = new WebSocket(this.ws_url)
    } catch (err) {
      console.error("AYON: unable to open the bridge websocket", err)
      this.schedule_reconnect()
      return
    }
    this.ws = ws
    ws.onopen = () => ws.send(JSON.stringify(hello))
    ws.onmessage = (event) => this.on_message(ws, event)
    ws.onclose = (event) => this.on_close(ws, event)
  }

  on_message(ws, event) {
    if (ws !== this.ws) {
      return
    }
    const frame = parse_json(event.data)
    if (!frame) {
      return
    }
    switch (frame.type) {
      case "welcome":
        storage_set(CREDENTIAL_KEY, JSON.stringify(frame.credential))
        storage_remove(PAIR_CODE_KEY)
        this.attempt = 0
        this.unknown_since = null
        this.host_connected = !!frame.peer?.connected
        this.host_info = frame.peer?.info ?? {}
        this.set_state("connected")
        break
      case "peer":
        this.host_connected = !!frame.connected
        if (frame.connected && frame.info) {
          this.host_info = frame.info
        }
        this.emit()
        break
      case "request":
        this.handle_request(ws, frame)
        break
      case "response":
        this.resolve(frame)
        break
    }
  }

  on_close(ws, event) {
    if (ws !== this.ws) {
      return
    }
    this.ws = null
    this.host_connected = false
    this.reject_pending("Lost the connection to AYON.")

    if (event.code === CLOSE_SUPERSEDED) {
      this.set_state(
        "superseded", "AYON is connected to another ComfyUI tab."
      )
      return
    }
    if (event.code === CLOSE_REJECTED) {
      const reason = event.reason || "unknown reason"
      if (this.hello_with_code) {
        // An invalid or expired pairing code: drop it, but keep using the
        // credential this tab may already have.
        storage_remove(PAIR_CODE_KEY)
        this.dispatchEvent(new CustomEvent("notice", {
          detail: `AYON didn't accept the pairing code: ${reason}.`,
        }))
        if (parse_json(storage_get(CREDENTIAL_KEY))) {
          this.attempt = 0
          this.connect()
          return
        }
      } else {
        storage_remove(CREDENTIAL_KEY)
      }
      this.set_state(
        "rejected",
        `AYON rejected this tab: ${reason}. ` +
        "Launch ComfyUI from AYON again, or paste a new pairing code."
      )
      return
    }
    if (event.code === CLOSE_UNKNOWN_SESSION) {
      this.unknown_since ??= Date.now()
      if (Date.now() - this.unknown_since > UNKNOWN_SESSION_RETRY_MS) {
        storage_remove(CREDENTIAL_KEY)
        storage_remove(PAIR_CODE_KEY)
        this.set_state(
          "ended",
          "The AYON session has ended. Launch ComfyUI from AYON again."
        )
        return
      }
    }
    this.schedule_reconnect()
  }

  schedule_reconnect() {
    const delay = RECONNECT_DELAYS_MS[
      Math.min(this.attempt, RECONNECT_DELAYS_MS.length - 1)
    ]
    this.attempt += 1
    this.set_state("connecting", "Reconnecting to AYON...")
    this.reconnect_timer = setTimeout(() => this.connect(), delay)
  }

  async handle_request(ws, frame) {
    const reply = {type: "response", id: frame.id}
    const handler = this.handlers.get(frame.method)
    if (!handler) {
      reply.error = {
        code: "unknown_method",
        message: `This ComfyUI tab doesn't handle '${frame.method}'. ` +
          "Reload the tab if AYON was updated.",
      }
    } else {
      try {
        const result = await handler(frame.params ?? {})
        reply.result = result === undefined ? null : result
      } catch (err) {
        console.error(`AYON: '${frame.method}' failed`, err)
        reply.error = {code: "error", message: String(err?.message ?? err)}
      }
    }
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(reply))
    }
  }

  // Call `method` on the AYON host. Rejects with a readable error when AYON
  // isn't connected.
  call(method, params = {}, timeout_ms = 30000) {
    return new Promise((resolve, reject) => {
      const ws = this.ws
      if (!ws || ws.readyState !== WebSocket.OPEN || !this.connected) {
        reject(new Error(this.not_connected_message()))
        return
      }
      const id = `tab-${this.id_prefix}-${this.next_id++}`
      const timer = timeout_ms ? setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`AYON didn't answer '${method}' in time.`))
      }, timeout_ms) : null
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer)
          resolve(value)
        },
        reject: (err) => {
          clearTimeout(timer)
          reject(err)
        },
      })
      ws.send(JSON.stringify({type: "request", id, method, params}))
    })
  }

  not_connected_message() {
    if (this.state === "connected" && !this.host_connected) {
      return "AYON is not connected. Is the AYON session still running?"
    }
    return this.reason || "Not connected to AYON."
  }

  resolve(frame) {
    const pending = this.pending.get(frame.id)
    if (!pending) {
      return
    }
    this.pending.delete(frame.id)
    if (frame.error) {
      pending.reject(new Error(frame.error.message ?? String(frame.error)))
    } else {
      pending.resolve(frame.result)
    }
  }

  set_state(state, reason = "") {
    this.state = state
    this.reason = reason
    this.emit()
  }

  emit() {
    this.dispatchEvent(new Event("change"))
  }
}
