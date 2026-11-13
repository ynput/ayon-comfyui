// AYON pickers on ComfyUI nodes: folder -> product -> version ->
// representation widgets on the `AYON Load ...` nodes.
//
// The lists come from the AYON session paired with this tab, over the bridge
// (`picker.*` methods in `api/pickers.py`). Picking a product, version or
// representation asks AYON to load it into the node; AYON uploads the files
// and answers with the node's new container, which is written to the node's
// `ayon_container_info` widget (the only data node execution reads) and to
// the AYON Context node of the same graph.
//
// Robustness to frontend changes:
// - Only standard `combo` and `button` widgets, added in `onNodeCreated`, so
//   they work on the classic canvas and on Nodes 2.0 alike.
// - The widgets are UI only: not saved in the workflow (`serialize`) and not
//   sent with the prompt (`options.serialize`). They are rebuilt from the
//   container whenever it changes, so nothing is lost when a frontend
//   restores them differently.
// - Combo values are labels (folder path, product name, ...), which are
//   unique within a list. The ids live in the container's `selection`.
// - Nodes 2.0 renders a combo from a copy of its options, so lists are
//   updated in place (the array object never changes); the dropdown reads
//   them again whenever it opens.
// - While AYON isn't connected the node keeps what it loads and shows that;
//   nothing is ever cleared or overwritten on errors.
//
// ComfyUI loads every .js file of an extension, so this module must not have
// side effects on import.

export const LOAD_NODE_TYPES = [
  "AYON Load Image",
  "AYON Load Video",
  "AYON Load 3D Model",
]
export const CONTAINER_WIDGET = "ayon_container_info"
const CONTEXT_NODE_TYPE = "AYON Context"
const CONTEXT_WIDGET = "ayon_context_info"

const QUERY_TIMEOUT_MS = 15000
// How long AYON may take to upload a picked representation.
const APPLY_TIMEOUT_MS = 5 * 60 * 1000
// How long AYON keeps a node waiting for the Loader (LOAD_TARGET_TTL).
const LOADER_TARGET_TTL_MS = 30 * 60 * 1000
const LATEST = "latest"
const STATUS_BATCH_MS = 30
const REFRESH_DEBOUNCE_MS = 50

const WIDGETS = {
  folder: ["ayon_pick_folder", "folder"],
  product: ["ayon_pick_product", "product"],
  version: ["ayon_pick_version", "version"],
  representation: ["ayon_pick_representation", "representation"],
}
const STATUS_WIDGET = "ayon_pick_status"
const LOADER_WIDGET = "ayon_pick_loader"
const WAITING_FOR_LOADER =
  "waiting for the AYON Loader: use 'Load into waiting ComfyUI node'"
// Errors the AYON host sends when the Loader was closed or opened for
// another node: not worth a toast.
const QUIET_LOADER_ERRORS = [
  "The AYON Loader was opened for another node.",
  "The AYON Loader was closed.",
]

export function parse_json(text) {
  if (typeof text !== "string" || !text) {
    return null
  }
  try {
    const value = JSON.parse(text)
    return value && typeof value === "object" ? value : null
  } catch {
    return null
  }
}

export function find_widget(node, name) {
  return node?.widgets?.find((widget) => widget.name === name) ?? null
}

export function version_label(version) {
  if (typeof version !== "number") {
    return ""
  }
  if (version < 0) {
    return "hero"
  }
  return `v${String(version).padStart(3, "0")}`
}

// Nodes of a root graph, including the nodes inside its subgraphs.
export function graph_nodes(root) {
  const nodes = [...(root?.nodes ?? [])]
  const subgraphs = root?.subgraphs
  if (subgraphs) {
    const values = typeof subgraphs.values === "function"
      ? subgraphs.values()
      : Object.values(subgraphs)
    for (const subgraph of values) {
      nodes.push(...(subgraph?.nodes ?? []))
    }
  }
  return nodes
}

function root_graph_of(node) {
  const graph = node?.graph
  return graph?.rootGraph ?? graph ?? null
}

function new_token() {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"))
    .join("")
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return {promise, resolve, reject}
}

function error_message(err) {
  return String(err?.message ?? err)
}

function add_ui_widget(node, type, name, label, callback, options) {
  const widget = node.addWidget(type, name, type === "combo" ? "" : null,
    callback, options)
  widget.label = label
  // UI only: not saved with the workflow, not sent with the prompt.
  widget.serialize = false
  widget.options ??= {}
  widget.options.serialize = false
  return widget
}

// Show `labels` in a combo, with `value` selected. The list is updated in
// place, see the note at the top.
function set_combo(widget, labels, value) {
  const values = widget.options.values
  const items = [...labels]
  if (value && !items.includes(value)) {
    items.unshift(value)
  }
  values.splice(0, values.length, ...items)
  if (widget.value !== value) {
    widget.value = value
  }
}

// --- one node --------------------------------------------------------------

// The pickers of one `AYON Load ...` node.
export class LoadPicker {
  constructor(node, hub) {
    this.node = node
    this.hub = hub
    this.generation = 0
    this.applying = null
    this.selection = {}
    this.latest = null
    // Representation name to keep when picking another product.
    this.preferred_representation = null
    this.lists = {folders: [], products: [], versions: [], representations: []}
    this.state = {kind: "idle", text: ""}

    this.widgets = {}
    for (const [key, [name, label]] of Object.entries(WIDGETS)) {
      this.widgets[key] = add_ui_widget(
        node, "combo", name, label,
        (value) => this.on_pick(key, value),
        {values: []}
      )
    }
    this.status_widget = add_ui_widget(
      node, "button", STATUS_WIDGET, "AYON", () => this.on_status_click(), {}
    )
    this.loader_widget = add_ui_widget(
      node, "button", LOADER_WIDGET, "Open AYON Loader…",
      () => this.open_loader(), {}
    )
    // Token of an open "Open AYON Loader" request.
    this.browse_token = null
    this.sync_from_container()
  }

  get node_type() {
    return this.node.comfyClass ?? this.node.type
  }

  // The container on the node, or null for a node nothing was loaded into.
  container() {
    return parse_json(find_widget(this.node, CONTAINER_WIDGET)?.value)
  }

  // Show what the node loads, from its container (no AYON queries).
  sync_from_container() {
    const container = this.container()
    const selection = container?.selection
    this.selection = selection && typeof selection === "object"
      ? {...selection}
      : {}
    if (!this.selection.version_mode) {
      this.selection.version_mode = "pinned"
    }
    this.latest = null
    if (!container?.representation) {
      this.set_state("idle", "Pick a folder and a product to load")
    } else if (!this.hub.connected) {
      this.set_state("offline")
    } else {
      this.set_state("ok")
    }
    this.render()
  }

  render() {
    const sel = this.selection
    set_combo(this.widgets.folder,
      this.lists.folders.map((folder) => folder.path), sel.folder_path ?? "")
    set_combo(this.widgets.product,
      this.lists.products.map((product) => product.name),
      sel.product_name ?? "")
    let version_value = ""
    if (sel.product_id) {
      version_value = sel.version_mode === LATEST
        ? LATEST
        : version_label(sel.version)
    }
    const versions = this.lists.versions.map((version) => version.label)
    set_combo(this.widgets.version,
      versions.length ? [LATEST, ...versions] : [], version_value)
    set_combo(this.widgets.representation,
      this.lists.representations.map((repre) => repre.name),
      sel.representation_name ?? "")
    this.render_status()
  }

  set_state(kind, text = "") {
    this.state = {kind, text}
    this.render_status()
  }

  render_status() {
    const {kind, text} = this.state
    const sel = this.selection
    const loaded = sel.product_name
      ? `${sel.product_name} ${version_label(sel.version)}`
      : ""
    let label
    switch (kind) {
      case "offline":
        label = "AYON not connected: keeping what is loaded"
        break
      case "busy":
        label = `… ${text}`
        break
      case "error":
        label = `⚠ ${text} (click to refresh)`
        break
      case "update":
        label = `⬆ Update to ${version_label(this.latest?.version)} ` +
          `(${version_label(sel.version)} loaded)`
        break
      case "ok":
        label = `↻ ${loaded}` +
          (sel.version_mode === LATEST ? " (latest)" : "") +
          " · refresh"
        break
      default:
        label = text || "↻ refresh"
    }
    this.status_widget.label = label
    this.node.setDirtyCanvas?.(true, true)
  }

  // Reload the lists and what the node loads from AYON.
  async refresh({force = false} = {}) {
    const generation = ++this.generation
    this.hub.pickers.add(this)
    if (this.applying) {
      return
    }
    this.sync_from_container()
    if (!this.hub.connected) {
      return
    }
    const container = this.container()
    this.set_state("busy", "loading AYON lists")
    try {
      const folders = await this.hub.folders({force})
      if (generation !== this.generation) {
        return
      }
      this.lists.folders = folders
      // E.g. loaded from a library project with the AYON Loader: the
      // pickers only browse the session's project.
      const loaded_project =
        container?.project_name ?? container?.selection?.project_name
      const project = this.hub.project_name
      if (container?.representation && loaded_project && project &&
          loaded_project !== project) {
        this.render()
        this.set_state("idle",
          `Loaded from project ${loaded_project}; pick to load from ${project}`)
        return
      }
      const status = container?.representation
        ? await this.hub.status_of(container.representation)
        : null
      if (generation !== this.generation) {
        return
      }
      let warning = ""
      if (status?.missing) {
        warning = `The loaded ${status.missing} no longer exists in AYON`
      } else if (status) {
        // AYON is the truth for labels: picks up renamed entities.
        this.selection = {
          ...this.selection,
          folder_id: status.folder_id,
          folder_path: status.folder_path,
          product_id: status.product_id,
          product_name: status.product_name,
          version_id: status.version_id,
          version: status.version,
          representation_id: status.representation_id,
          representation_name: status.representation_name,
        }
        this.latest = {
          id: status.latest_version_id,
          version: status.latest_version,
        }
      }
      if (this.selection.folder_id &&
          folders.some((folder) => folder.id === this.selection.folder_id)) {
        await this.load_options({
          folder_id: this.selection.folder_id,
          product_id: this.selection.product_id,
          version_id: this.selection.version_id,
          refresh: force,
        }, generation)
      } else if (this.selection.folder_id && !warning && container) {
        warning = "The loaded folder is not in the current project"
      }
      if (generation !== this.generation) {
        return
      }
      this.render()
      if (warning) {
        this.set_state("error", warning)
      } else if (!container?.representation) {
        this.set_state("idle", "Pick a folder and a product to load")
      } else if (this.hub.shares_container(this.node, container)) {
        this.set_state("error",
          "Shares its container with another node: pick to separate them")
      } else if (
        this.selection.version_mode === LATEST &&
        this.latest && this.latest.id !== this.selection.version_id
      ) {
        this.set_state("update")
      } else {
        this.set_state("ok")
      }
      if (this.browse_token) {
        this.set_state("busy", WAITING_FOR_LOADER)
      }
    } catch (err) {
      if (generation === this.generation) {
        this.render()
        this.set_state("error", error_message(err))
      }
    }
  }

  async load_options(params, generation) {
    const options = await this.hub.call("picker.options", {
      node_type: this.node_type,
      ...params,
    })
    if (generation !== this.generation) {
      return null
    }
    this.lists.products = options.products ?? []
    this.lists.versions = options.versions ?? []
    this.lists.representations = options.representations ?? []
    return options
  }

  // A pick in one of the combos.
  async on_pick(key, value) {
    this.hub.pickers.add(this)
    if (this.applying) {
      this.render()
      return
    }
    if (!this.hub.connected) {
      this.hub.toast("warn", this.hub.not_connected_message())
      this.render()
      return
    }
    const generation = ++this.generation
    try {
      if (key === "folder") {
        await this.pick_folder(value, generation)
      } else if (key === "product") {
        await this.pick_product(value, generation)
      } else if (key === "version") {
        await this.pick_version(value, generation)
      } else if (key === "representation") {
        await this.pick_representation(value)
      }
    } catch (err) {
      if (generation === this.generation) {
        this.fail(error_message(err))
      }
    }
  }

  async pick_folder(path, generation) {
    const folder = this.lists.folders.find((item) => item.path === path)
    if (!folder || folder.id === this.selection.folder_id) {
      this.render()
      return
    }
    // Only show the folder's products; nothing loads until a product is
    // picked.
    if (this.selection.representation_name) {
      this.preferred_representation = this.selection.representation_name
    }
    this.selection = {
      folder_id: folder.id,
      folder_path: folder.path,
      version_mode: this.selection.version_mode,
    }
    this.lists.products = []
    this.lists.versions = []
    this.lists.representations = []
    this.render()
    this.set_state("busy", "loading products")
    if (!await this.load_options({folder_id: folder.id}, generation)) {
      return
    }
    this.render()
    this.set_state("idle", this.lists.products.length
      ? "Pick a product to load"
      : "No loadable products in this folder")
  }

  async pick_product(name, generation) {
    const product = this.lists.products.find((item) => item.name === name)
    if (!product) {
      this.render()
      return
    }
    this.set_state("busy", `loading ${product.name}`)
    const options = await this.load_options({
      folder_id: this.selection.folder_id,
      product_id: product.id,
    }, generation)
    if (!options) {
      return
    }
    const latest = this.lists.versions[0]
    if (!latest) {
      this.render()
      this.set_state("error", `${product.name} has no versions`)
      return
    }
    this.selection = {
      ...this.selection,
      product_id: product.id,
      product_name: product.name,
      version_mode: LATEST,
      version_id: latest.id,
      version: latest.version,
    }
    this.latest = {id: latest.id, version: latest.version}
    await this.apply_with_representation()
  }

  async pick_version(label, generation) {
    const versions = this.lists.versions
    const version = label === LATEST
      ? versions[0]
      : versions.find((item) => item.label === label)
    if (!version) {
      this.render()
      return
    }
    const options = await this.load_options({
      folder_id: this.selection.folder_id,
      product_id: this.selection.product_id,
      version_id: version.id,
    }, generation)
    if (!options) {
      return
    }
    this.selection = {
      ...this.selection,
      version_mode: label === LATEST ? LATEST : "pinned",
      version_id: version.id,
      version: version.version,
    }
    await this.apply_with_representation()
  }

  async pick_representation(name) {
    if (!this.lists.representations.some((repre) => repre.name === name)) {
      this.render()
      return
    }
    this.selection = {...this.selection, representation_name: name}
    await this.apply()
  }

  // Keep the representation name when the new version has it.
  async apply_with_representation() {
    const names = this.lists.representations.map((repre) => repre.name)
    if (!names.length) {
      this.render()
      this.set_state("error",
        `${this.selection.product_name} ` +
        `${version_label(this.selection.version)} has nothing this node ` +
        "can load")
      return
    }
    const wanted = this.selection.representation_name ??
      this.preferred_representation
    this.selection.representation_name = names.includes(wanted)
      ? wanted
      : names[0]
    await this.apply()
  }

  // Ask AYON to load the selection into this node.
  async apply() {
    const sel = this.selection
    const container = this.container()
    let container_uuid = container?.container_uuid ?? null
    if (container_uuid && this.hub.shares_container(this.node, container)) {
      // A pasted copy: AYON makes it a container of its own.
      container_uuid = null
    }
    const token = new_token()
    this.applying = token
    this.render()
    this.set_state("busy",
      `loading ${sel.product_name} ` +
      `${sel.version_mode === LATEST ? LATEST : version_label(sel.version)}`)
    this.hub.pending.set(token, {picker: this, root: root_graph_of(this.node)})
    try {
      await this.hub.call("picker.apply", {
        token,
        node_type: this.node_type,
        container_uuid,
        product_id: sel.product_id,
        version_mode: sel.version_mode,
        version_id: sel.version_mode === LATEST ? null : sel.version_id,
        representation_name: sel.representation_name,
        // Keep reading files in place when the node does.
        reference: !!container?.path_reference,
      })
    } catch (err) {
      this.hub.pending.delete(token)
      this.applying = null
      this.fail(error_message(err))
      return
    }
    setTimeout(() => {
      if (this.hub.pending.delete(token) && this.applying === token) {
        this.applying = null
        this.fail("AYON didn't finish loading in time")
      }
    }, APPLY_TIMEOUT_MS)
  }

  // Let the artist pick in the AYON Loader what this node loads.
  async open_loader() {
    if (this.applying) {
      return
    }
    if (!this.hub.connected) {
      this.hub.toast("warn", this.hub.not_connected_message())
      return
    }
    const container = this.container()
    let container_uuid = container?.container_uuid ?? null
    if (container_uuid && this.hub.shares_container(this.node, container)) {
      container_uuid = null
    }
    if (this.browse_token) {
      this.hub.pending.delete(this.browse_token)
    }
    const token = new_token()
    this.browse_token = token
    this.hub.pending.set(token, {picker: this, root: root_graph_of(this.node)})
    this.set_state("busy", WAITING_FOR_LOADER)
    setTimeout(() => {
      if (this.browse_token === token) {
        this.hub.pending.delete(token)
        this.browse_token = null
        this.refresh()
      }
    }, LOADER_TARGET_TTL_MS)
    try {
      await this.hub.call("picker.browse", {
        token,
        node_type: this.node_type,
        container_uuid,
        reference: !!container?.path_reference,
      })
    } catch (err) {
      this.hub.pending.delete(token)
      if (this.browse_token === token) {
        this.browse_token = null
        this.fail(error_message(err))
      }
    }
  }

  // Whether `token` is this node's pending load or Loader request; ends it.
  take_token(token) {
    if (token && token === this.applying) {
      this.applying = null
      return true
    }
    if (token && token === this.browse_token) {
      this.browse_token = null
      return true
    }
    return false
  }

  // AYON loaded the selection: put the container on the node.
  applied(token, container) {
    if (!this.take_token(token)) {
      return false
    }
    // The node got what it loads; stop waiting for the Loader as well.
    if (this.browse_token) {
      this.hub.pending.delete(this.browse_token)
      this.browse_token = null
    }
    const widget = find_widget(this.node, CONTAINER_WIDGET)
    if (!widget) {
      this.fail("The node has no AYON container input")
      return false
    }
    widget.value = JSON.stringify(container)
    const title = this.node.title ?? ""
    if (!title || title === this.node.type || title.startsWith("AYON Container (")) {
      this.node.title = `AYON Container (${container.name})`
    }
    update_context_container(root_graph_of(this.node), container)
    this.hub.graph_changed(this.node)
    this.sync_from_container()
    this.refresh()
    return true
  }

  failed(token, message) {
    if (!this.take_token(token)) {
      return
    }
    if (QUIET_LOADER_ERRORS.includes(message)) {
      this.refresh()
      return
    }
    this.fail(message)
  }

  // Show an error and go back to what the node loads.
  fail(message) {
    this.hub.toast("warn", message)
    this.sync_from_container()
    this.set_state("error", message)
  }

  on_status_click() {
    if (this.applying) {
      return
    }
    if (this.state.kind === "update" && this.hub.connected) {
      this.selection = {
        ...this.selection,
        version_id: this.latest.id,
        version: this.latest.version,
      }
      this.apply()
      return
    }
    this.hub.invalidate()
    this.refresh({force: true})
  }

  // The node was removed. `live_pickers` stops refreshing it; a node that
  // is still in use (e.g. moved into a subgraph) registers again when used.
  dispose() {
    this.generation += 1
    for (const token of [this.applying, this.browse_token]) {
      if (token) {
        this.hub.pending.delete(token)
      }
    }
    this.applying = null
    this.browse_token = null
    this.hub.forget(this)
  }

  // AYON disconnected: nothing will answer pending requests.
  abandon_requests() {
    this.take_token(this.applying)
    this.take_token(this.browse_token)
  }
}

// Record `container` in the AYON Context node of `root`, which holds the
// graph's containers for AYON's Scene Inventory.
function update_context_container(root, container) {
  if (!root) {
    return
  }
  let context_node = (root.nodes ?? []).find(
    (node) => node.type === CONTEXT_NODE_TYPE
  )
  if (!context_node) {
    const LiteGraph = globalThis.LiteGraph
    context_node = LiteGraph?.createNode?.(CONTEXT_NODE_TYPE)
    if (!context_node) {
      console.warn("AYON: unable to create the AYON Context node")
      return
    }
    root.add(context_node)
  }
  const widget = find_widget(context_node, CONTEXT_WIDGET)
  if (!widget) {
    return
  }
  const data = parse_json(widget.value) ?? {}
  data.context ??= {}
  data.instances ??= []
  data.containers ??= []
  const index = data.containers.findIndex(
    (item) => item?.container_uuid === container.container_uuid
  )
  if (index >= 0) {
    data.containers[index] = container
  } else {
    data.containers.push(container)
  }
  widget.value = JSON.stringify(data)
}

// --- all nodes of the tab --------------------------------------------------

// Shared by the pickers of a tab: the bridge to AYON, the folder list,
// batched status queries and loads waiting for AYON.
export class PickerHub {
  constructor(app) {
    this.app = app
    this.bridge = null
    this.pickers = new Set()
    this.pending = new Map()
    this.folders_promise = null
    // The session's project, as reported with the folders.
    this.project_name = null
    this.status_batch = null
    this.refresh_queue = new Set()
    this.refresh_timer = null
    this.was_connected = false
  }

  get connected() {
    return !!this.bridge?.connected
  }

  not_connected_message() {
    return this.bridge?.not_connected_message?.() ?? "Not connected to AYON."
  }

  attach(bridge) {
    this.bridge = bridge
    bridge.register("pickerApplied", (params) => this.on_applied(params))
    bridge.register("pickerInvalidate", () => {
      this.invalidate()
      this.refresh_all()
      return true
    })
    bridge.addEventListener("change", () => this.on_bridge_change())
    this.on_bridge_change()
  }

  on_bridge_change() {
    const connected = this.connected
    if (connected === this.was_connected) {
      return
    }
    this.was_connected = connected
    if (!connected) {
      // Answers to pending loads won't arrive anymore.
      for (const {picker} of this.pending.values()) {
        picker.abandon_requests()
      }
      this.pending.clear()
    }
    this.invalidate()
    this.refresh_all()
  }

  toast(severity, detail) {
    const toast = this.app.extensionManager?.toast
    if (toast?.add) {
      toast.add({severity, summary: "AYON", detail, life: 6000})
    } else {
      console.warn(`AYON: ${detail}`)
    }
  }

  call(method, params = {}) {
    if (!this.bridge) {
      return Promise.reject(new Error("The AYON extension is still starting."))
    }
    return this.bridge.call(method, params, QUERY_TIMEOUT_MS)
  }

  register(picker) {
    this.pickers.add(picker)
    this.schedule_refresh(picker)
  }

  forget(picker) {
    this.pickers.delete(picker)
    this.refresh_queue.delete(picker)
  }

  invalidate() {
    this.folders_promise = null
  }

  folders({force = false} = {}) {
    if (force || !this.folders_promise) {
      const promise = this.call("picker.folders", {refresh: force})
        .then((result) => {
          this.project_name = result.project_name ?? null
          return result.folders ?? []
        })
      promise.catch(() => {
        if (this.folders_promise === promise) {
          this.folders_promise = null
        }
      })
      this.folders_promise = promise
    }
    return this.folders_promise
  }

  // What a representation id is (labels, latest version), batched across
  // all nodes refreshing at the same time.
  status_of(representation_id) {
    if (!this.status_batch) {
      const batch = new Map()
      this.status_batch = batch
      setTimeout(() => this.flush_status(batch), STATUS_BATCH_MS)
    }
    let entry = this.status_batch.get(representation_id)
    if (!entry) {
      entry = deferred()
      this.status_batch.set(representation_id, entry)
    }
    return entry.promise
  }

  async flush_status(batch) {
    if (this.status_batch === batch) {
      this.status_batch = null
    }
    try {
      const result = await this.call("picker.status", {
        representation_ids: [...batch.keys()],
      })
      for (const [id, entry] of batch) {
        entry.resolve(result.items?.[id] ?? {missing: "representation"})
      }
    } catch (err) {
      for (const entry of batch.values()) {
        entry.reject(err)
      }
    }
  }

  // Whether another node of the graph holds the same container, e.g. a
  // pasted copy.
  shares_container(node, container) {
    const uuid = container?.container_uuid
    if (!uuid) {
      return false
    }
    return graph_nodes(root_graph_of(node)).some((other) => {
      if (other === node || !LOAD_NODE_TYPES.includes(other.type)) {
        return false
      }
      const other_container = parse_json(
        find_widget(other, CONTAINER_WIDGET)?.value
      )
      return other_container?.container_uuid === uuid
    })
  }

  schedule_refresh(picker) {
    this.refresh_queue.add(picker)
    clearTimeout(this.refresh_timer)
    this.refresh_timer = setTimeout(() => {
      const queue = [...this.refresh_queue]
      this.refresh_queue.clear()
      queue.forEach((item) => item.refresh())
    }, REFRESH_DEBOUNCE_MS)
  }

  // Pickers of the nodes in the open graph.
  live_pickers() {
    const root = this.app.rootGraph ?? this.app.graph
    const nodes = new Set(graph_nodes(root))
    for (const picker of [...this.pickers]) {
      if (!nodes.has(picker.node)) {
        this.forget(picker)
      }
    }
    return [...this.pickers]
  }

  refresh_all() {
    this.live_pickers().forEach((picker) => this.schedule_refresh(picker))
  }

  // Show container changes AYON made directly (Loader, Scene Inventory).
  sync_container(container_uuid = null) {
    for (const picker of this.live_pickers()) {
      if (picker.applying) {
        continue
      }
      const container = picker.container()
      if (!container_uuid || container?.container_uuid === container_uuid) {
        picker.sync_from_container()
        this.schedule_refresh(picker)
      }
    }
  }

  // A load requested by a picker finished on the AYON side.
  on_applied(params) {
    const token = params?.token
    const entry = this.pending.get(token)
    if (!entry) {
      return false
    }
    this.pending.delete(token)
    const {picker, root} = entry
    const current_root = this.app.rootGraph ?? this.app.graph
    const attached = root && root === root_graph_of(picker.node) &&
      graph_nodes(current_root).includes(picker.node)
    if (!attached) {
      // The node was removed, or the artist switched to another workflow;
      // never write into whatever graph is open now.
      picker.take_token(token)
      if (params.error) {
        return false
      }
      this.toast("warn",
        "AYON finished loading after the node was removed or its " +
        "workflow was closed; nothing was changed.")
      return false
    }
    if (params.error) {
      picker.failed(token, params.error)
      return false
    }
    const container = parse_json(params.container_json)
    if (!container?.container_uuid) {
      picker.failed(token, "AYON sent an invalid container")
      return false
    }
    return picker.applied(token, container)
  }

  graph_changed(node) {
    node.setDirtyCanvas?.(true, true)
    const workflow = this.app.extensionManager?.workflow?.activeWorkflow
    const tracker = workflow?.changeTracker
    try {
      if (typeof tracker?.captureCanvasState === "function") {
        tracker.captureCanvasState()
      } else {
        tracker?.checkState?.()
      }
    } catch (err) {
      console.warn("AYON: unable to record the change", err)
    }
  }
}
