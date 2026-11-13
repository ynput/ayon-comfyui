// Which ComfyUI workflow (tab) the AYON host acts on.
//
// The host pins a workflow by its AYON key, e.g. for the duration of a
// publish or for the instances the Publisher shows, so its calls keep
// acting on that workflow while the artist switches tabs. Only the active
// workflow has a live graph; another open workflow is read and written
// through its stored state (`workflow.activeState`).
//
// Kept free of ComfyUI imports so it can be tested on its own.

const STORAGE_KEY = "ayon.workflow_keys"
const PAGE_KEY = "ayon.page_id"
const STORAGE_LIMIT = 200

function new_key() {
  const crypto = globalThis.crypto
  if (typeof crypto?.randomUUID === "function") {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

// An error whose `code` reaches the AYON host (see `ayon_bridge.js`).
export function workflow_error(code, message) {
  const error = new Error(message)
  error.code = code
  return error
}

// The name ComfyUI shows for `workflow`.
export function workflow_label(workflow) {
  if (!workflow) {
    return null
  }
  return workflow.filename ?? workflow.path ?? null
}

function weak_ref(value) {
  return typeof WeakRef === "function" ? new WeakRef(value) : {deref: () => value}
}

// Each open workflow's AYON key: unique per tab (a duplicated workflow or
// the same workfile open twice get their own), stable while it's open, also
// when it's renamed. Remembered per ComfyUI workflow path in the browser
// tab's session storage, so the workflows a reload of the page restores
// get their keys back.
export class WorkflowKeys {
  constructor(storage = globalThis.sessionStorage ?? null) {
    this.storage = storage
    this.keys = new WeakMap()
    // key -> the workflow holding it
    this.holders = new Map()
    // path -> key, as stored before this page loaded; each is used once
    this.restorable = null
    this.page = null
  }

  // This browser tab's id. Keys are only unique within it: each browser
  // tab has its own session storage.
  page_id() {
    if (!this.page) {
      let page = null
      try {
        page = this.storage?.getItem(PAGE_KEY) ?? null
      } catch (err) {
        page = null
      }
      if (!page) {
        page = new_key()
        try {
          this.storage?.setItem(PAGE_KEY, page)
        } catch (err) {
          // The id still holds for this page.
        }
      }
      this.page = page
    }
    return this.page
  }

  key(workflow) {
    if (!workflow) {
      return null
    }
    const path = typeof workflow.path === "string" ? workflow.path : null
    let key = this.keys.get(workflow)
    if (!key) {
      // Only a workflow restored by a reload of the page takes a stored key
      // back, and never one another open workflow holds: a workflow opened
      // later at a path another one left (renamed or closed) is another
      // workflow.
      this.restorable ??= this.stored()
      const stored = path ? this.restorable[path] : null
      if (stored && !this.held_by_other(stored, workflow)) {
        key = stored
        delete this.restorable[path]
      } else {
        key = new_key()
      }
      this.keys.set(workflow, key)
      this.holders.set(key, weak_ref(workflow))
    }
    if (path) {
      this.remember(path, key)
    }
    return key
  }

  held_by_other(key, workflow) {
    const holder = this.holders.get(key)?.deref()
    return Boolean(holder) && holder !== workflow
  }

  // The open workflow with AYON key `key`, or null.
  find(workflows, key) {
    if (!key) {
      return null
    }
    return (workflows ?? []).find((workflow) => this.key(workflow) === key) ?? null
  }

  stored() {
    try {
      const value = JSON.parse(this.storage?.getItem(STORAGE_KEY) ?? "{}")
      return value && typeof value === "object" && !Array.isArray(value) ? value : {}
    } catch (err) {
      return {}
    }
  }

  remember(path, key) {
    const stored = this.stored()
    if (stored[path] === key) {
      return
    }
    // A renamed workflow takes its key along.
    for (const [other_path, other_key] of Object.entries(stored)) {
      if (other_key === key) {
        delete stored[other_path]
      }
    }
    stored[path] = key
    const entries = Object.entries(stored)
    try {
      this.storage?.setItem(
        STORAGE_KEY,
        JSON.stringify(Object.fromEntries(entries.slice(-STORAGE_LIMIT)))
      )
    } catch (err) {
      // Storage full or unavailable: the key still holds for this page.
    }
  }
}

// The stored state (serialized graph) of a workflow that isn't active.
export function stored_state(workflow) {
  const state = workflow?.activeState ?? workflow?.changeTracker?.activeState ?? null
  if (!state || typeof state !== "object") {
    throw workflow_error(
      "workflow_unavailable",
      `ComfyUI hasn't loaded the workflow '${workflow_label(workflow)}' yet. ` +
      "Switch to its tab once and try again."
    )
  }
  return state
}

// Let ComfyUI notice a change made to a stored state directly.
export function stored_state_changed(workflow) {
  try {
    workflow?.changeTracker?.updateModified?.()
  } catch (err) {
    console.warn("AYON: Unable to update the workflow's modified state", err)
  }
}

// The serialized `AYON Context` node of a stored state, or null.
export function stored_context_node(state) {
  return (state?.nodes ?? []).find((node) => node?.type === "AYON Context") ?? null
}

// The context node's text (its only widget) in a stored state.
export function read_stored_context(state) {
  const value = stored_context_node(state)?.widgets_values?.[0]
  return typeof value === "string" ? value : ""
}

export function write_stored_context(workflow, value) {
  const node = stored_context_node(stored_state(workflow))
  if (!node) {
    throw workflow_error(
      "workflow_inactive",
      `The ComfyUI workflow '${workflow_label(workflow)}' has no AYON Context ` +
      "node yet. Switch to its tab and try again."
    )
  }
  if (!Array.isArray(node.widgets_values)) {
    node.widgets_values = []
  }
  node.widgets_values[0] = value
  stored_state_changed(workflow)
}
