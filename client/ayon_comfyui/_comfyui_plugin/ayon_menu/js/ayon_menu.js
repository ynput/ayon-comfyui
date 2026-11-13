import { app } from "../../scripts/app.js";
import { AyonBridge, PROTOCOL, bridge_ws_url } from "./lib/ayon_bridge.js";

const AYON_EXTENSION_NAME = "AYON.ComfyMenu"
const AYON_SAVE_WORKFILE_COMMAND_ID = "AYON.SaveWorkfile"
const AYON_SIDEBAR_TAB_ID = "ayon"
const AYON_SIDEBAR_ICON_CLASS = "ayon-sidebar-icon"
const AYON_SIDEBAR_STYLE_ID = "ayon-sidebar-style"
const AYON_ICON_URL = new URL("./assets/ayon-icon.png", import.meta.url).href
const AYON_TOOL_ACTIONS = [
  {
    id: "showPublisher",
    label: "Publisher",
    tool_name: "publisher",
    description: "Open the AYON Publisher tool."
  },
  {
    id: "showCreator",
    label: "Creator",
    tool_name: "create",
    description: "Open the AYON Creator tool."
  },
  {
    id: "showWorkfiles",
    label: "Workfiles",
    tool_name: "workfiles",
    description: "Browse and manage AYON workfiles."
  },
  {
    id: "showLoader",
    label: "Loader",
    tool_name: "loader",
    description: "Load AYON content into the current graph."
  },
  {
    id: "showInventory",
    label: "Scene Inventory",
    tool_name: "sceneinventory",
    description: "Inspect AYON scene inventory items."
  },
  {
    id: "showScriptEditor",
    label: "Script Editor",
    tool_name: "scripteditor",
    description: "Open AYON Script Editor."
  }
]

function get_ayon_extension() {
  const exts = app.extensions;
  return exts.find((el) => el.name == AYON_EXTENSION_NAME)
}

// Connection to the AYON session that opened this tab (see lib/ayon_bridge.js)
let BRIDGE = null
const STATUS_VIEWS = new Set()

function show_toast(severity, detail, life = 6000) {
  const toast = app.extensionManager?.toast
  if (toast?.add) {
    toast.add({severity, summary: "AYON", detail, life})
  } else {
    console.warn(`AYON: ${detail}`)
  }
}

// Call `method` on the AYON host; failures are shown as a toast instead of
// silently doing nothing.
async function call_ayon(method, params = {}) {
  if (!BRIDGE) {
    show_toast("warn", "The AYON extension is still starting.")
    return null
  }
  try {
    return await BRIDGE.call(method, params)
  } catch (err) {
    show_toast("warn", String(err?.message ?? err))
    return null
  }
}

function request_ayon_tool(tool_name) {
  return call_ayon("requestToolByName", {tool_name})
}

function describe_bridge_status(bridge) {
  if (!bridge) {
    return {level: "warn", text: "Starting..."}
  }
  if (bridge.state === "connected") {
    if (!bridge.host_connected) {
      return {
        level: "warn",
        text: "AYON is not connected. Waiting for the AYON session...",
      }
    }
    const info = bridge.host_info ?? {}
    const context = [info.project, info.folder, info.task]
      .filter(Boolean)
      .join(" / ")
    let text = "Connected to AYON"
    if (info.user) {
      text += ` as ${info.user}`
    }
    if (context) {
      text += `: ${context}`
    }
    return {level: "ok", text}
  }
  if (bridge.state === "connecting") {
    return {level: "warn", text: bridge.reason || "Connecting to AYON..."}
  }
  return {level: "error", text: bridge.reason || "Not connected to AYON."}
}

function describe_bridge_details(bridge) {
  if (!bridge || bridge.state !== "connected") {
    return ""
  }
  const info = bridge.host_info ?? {}
  const parts = []
  if (info.hostname) {
    parts.push(`AYON on ${info.hostname}`)
  }
  if (info.addon_version) {
    parts.push(`addon ${info.addon_version}`)
  }
  parts.push(`bridge protocol ${PROTOCOL}`)
  return parts.join(", ")
}

function update_status_views() {
  STATUS_VIEWS.forEach((update) => update())
}

let LAST_BRIDGE_SUMMARY = null

// Toast when the connection state changes in a way the artist should know.
function notify_bridge_change(bridge) {
  const summary = bridge.connected ? "connected" : bridge.state
  const previous = LAST_BRIDGE_SUMMARY
  LAST_BRIDGE_SUMMARY = summary
  if (summary === previous) {
    return
  }
  if (summary === "connected") {
    show_toast("success", describe_bridge_status(bridge).text, 3000)
  } else if (previous === "connected" || summary === "superseded") {
    show_toast("warn", describe_bridge_status(bridge).text)
  } else if (summary === "rejected" || summary === "ended") {
    show_toast("error", describe_bridge_status(bridge).text)
  }
}

function create_status_view() {
  const status = document.createElement("div")
  status.className = "ayon-sidebar-status"

  const line = document.createElement("div")
  line.className = "ayon-sidebar-status-line"
  const dot = document.createElement("span")
  dot.className = "ayon-sidebar-status-dot"
  const text = document.createElement("span")
  line.append(dot, text)

  const reconnect = document.createElement("button")
  reconnect.type = "button"
  reconnect.className = "ayon-sidebar-small-button"
  reconnect.textContent = "Use this tab for AYON"
  reconnect.addEventListener("click", () => BRIDGE?.reconnect_here())

  // Manual pairing: for a tab not opened by AYON, or when the launch link
  // lost its code (e.g. through an SSO login redirect).
  const pair = document.createElement("form")
  pair.className = "ayon-sidebar-pair"
  const code_input = document.createElement("input")
  code_input.type = "text"
  code_input.placeholder = "Pairing code from AYON"
  code_input.autocomplete = "off"
  const pair_button = document.createElement("button")
  pair_button.type = "submit"
  pair_button.className = "ayon-sidebar-small-button"
  pair_button.textContent = "Connect"
  pair.append(code_input, pair_button)
  pair.addEventListener("submit", (event) => {
    event.preventDefault()
    const code = code_input.value.trim()
    if (code && BRIDGE) {
      BRIDGE.pair_with_code(code)
      code_input.value = ""
    }
  })

  // Which AYON session this tab is attached to, for support questions.
  const details = document.createElement("div")
  details.className = "ayon-sidebar-status-details"

  status.append(line, details, reconnect, pair)

  const update = () => {
    const {level, text: message} = describe_bridge_status(BRIDGE)
    status.dataset.level = level
    text.textContent = message
    details.textContent = describe_bridge_details(BRIDGE)
    details.hidden = !details.textContent
    const state = BRIDGE?.state
    reconnect.hidden = state !== "superseded"
    pair.hidden = !["not_paired", "rejected", "ended"].includes(state)
    status.closest(".ayon-sidebar-panel")
      ?.querySelectorAll(".ayon-sidebar-action")
      .forEach((button) => {
        button.disabled = !BRIDGE?.connected
      })
  }
  return {element: status, update}
}

function create_ayon_tool_panel(container) {
  const root = document.createElement("div")
  root.className = "ayon-sidebar-panel"

  const header = document.createElement("div")
  header.className = "ayon-sidebar-panel-header"

  const logo = document.createElement("span")
  logo.className = "ayon-sidebar-panel-logo"

  const heading_wrap = document.createElement("div")

  const title = document.createElement("h2")
  title.className = "ayon-sidebar-panel-title"
  title.textContent = "AYON"

  const description = document.createElement("p")
  description.className = "ayon-sidebar-panel-description"
  description.textContent = "Launch AYON tools directly from ComfyUI."

  heading_wrap.append(title, description)
  header.append(logo, heading_wrap)

  const status_view = create_status_view()

  const actions = document.createElement("div")
  actions.className = "ayon-sidebar-panel-actions"

  AYON_TOOL_ACTIONS.forEach((action) => {
    const button = document.createElement("button")
    button.type = "button"
    button.className = "ayon-sidebar-action"

    const label = document.createElement("span")
    label.className = "ayon-sidebar-action-label"
    label.textContent = action.label

    const detail = document.createElement("span")
    detail.className = "ayon-sidebar-action-description"
    detail.textContent = action.description

    button.append(label, detail)
    button.addEventListener("click", () => {
      request_ayon_tool(action.tool_name)
    })
    actions.append(button)
  })

  root.append(header, status_view.element, actions)
  container.replaceChildren(root)

  // Only the most recently rendered panel is kept up to date.
  STATUS_VIEWS.clear()
  STATUS_VIEWS.add(status_view.update)
  status_view.update()
}

// --- ComfyUI workflow (tab) management -------------------------------------
//
// We deliberately go through the *public* ComfyUI frontend extension API
// (`app.extensionManager.workflow`, typed as `ExtensionManager.workflow` in
// the frontend's `extensionTypes.ts`) and only use the workflow store's
// actions (`renameWorkflow`, `saveWorkflow`, ...). That way the workflow
// manager keeps its own bookkeeping (tabs, drafts, bookmarks, thumbnails)
// consistent and we do not duplicate its internals, which are likely to
// change. If the store is not available (older frontends) we gracefully
// degrade: files still save to disk, but tabs are not renamed/saved.

const AYON_EXTRA_KEY = "AYON"

function get_workflow_store() {
  try {
    return app.extensionManager?.workflow ?? null
  } catch (err) {
    console.warn("AYON: Unable to access ComfyUI workflow store:", err)
    return null
  }
}

function get_root_graph() {
  return app.rootGraph ?? app.graph
}

function merge_into_extra(target, extra) {
  Object.keys(extra).forEach((key) => {
    const value = extra[key]
    const current = target[key]
    if (
      value !== null && typeof value === "object" && !Array.isArray(value) &&
      current !== null && typeof current === "object" && !Array.isArray(current)
    ) {
      target[key] = {...current, ...value}
    } else {
      target[key] = value
    }
  })
  return target
}

function get_ayon_extra() {
  return get_root_graph()?.extra?.[AYON_EXTRA_KEY] ?? null
}

function set_ayon_extra(values) {
  const graph = get_root_graph()
  graph.extra ??= {}
  graph.extra[AYON_EXTRA_KEY] = {...(graph.extra[AYON_EXTRA_KEY] ?? {}), ...values}
  return graph.extra[AYON_EXTRA_KEY]
}

function capture_tracker_state(tracker) {
  // `checkState` was deprecated in favor of `captureCanvasState`
  if (typeof tracker?.captureCanvasState === "function") {
    tracker.captureCanvasState()
  } else {
    tracker?.checkState?.()
  }
}

function sync_change_tracker(workflow = null) {
  // Make ComfyUI's change tracker pick up direct graph mutations
  // (like `graph.extra`) so that drafts and saves include them.
  const tracker = (workflow ?? get_workflow_store()?.activeWorkflow)?.changeTracker
  try {
    capture_tracker_state(tracker)
  } catch (err) {
    console.warn("AYON: Failed to sync change tracker:", err)
  }
}

function serialize_graph() {
  return JSON.stringify(get_root_graph().serialize())
}

async function rename_workflow(store, workflow, name) {
  // Rename the workflow (tab) to `name`, keeping it in its current directory.
  const directory = workflow.directory ?? "workflows"
  const new_path = `${directory}/${name}.json`
  if (workflow.path === new_path) {
    return
  }
  const existing = store.getWorkflowByPath(new_path)
  if (existing && existing !== workflow) {
    if (store.isOpen(existing)) {
      throw new Error(`Workflow '${new_path}' is already open in another tab.`)
    }
    // A closed ComfyUI-side copy of this same AYON workfile. The file on
    // disk managed by AYON is the source of truth, so we replace it.
    await store.deleteWorkflow(existing)
  }
  await store.renameWorkflow(workflow, new_path)
}

function ensure_ayon_sidebar_style() {
  if (document.getElementById(AYON_SIDEBAR_STYLE_ID)) {
    return
  }

  const style = document.createElement("style")
  style.id = AYON_SIDEBAR_STYLE_ID
  style.textContent = `
    .${AYON_SIDEBAR_ICON_CLASS} {
      display: inline-block;
      width: 1.1rem;
      height: 1.1rem;
      background-image: url("${AYON_ICON_URL}");
      background-position: center;
      background-repeat: no-repeat;
      background-size: contain;
    }

    .ayon-sidebar-panel {
      display: flex;
      flex-direction: column;
      gap: 1rem;
      padding: 1rem;
      color: var(--input-text);
    }

    .ayon-sidebar-panel-header {
      display: flex;
      gap: 0.75rem;
      align-items: center;
    }

    .ayon-sidebar-panel-logo {
      width: 2rem;
      height: 2rem;
      flex-shrink: 0;
      background-image: url("${AYON_ICON_URL}");
      background-position: center;
      background-repeat: no-repeat;
      background-size: contain;
    }

    .ayon-sidebar-panel-title {
      margin: 0;
      font-size: 1rem;
      line-height: 1.25rem;
    }

    .ayon-sidebar-panel-description {
      margin: 0.25rem 0 0;
      color: var(--descrip-text);
      font-size: 0.875rem;
      line-height: 1.25rem;
    }

    .ayon-sidebar-panel-actions {
      display: grid;
      gap: 0.5rem;
    }

    .ayon-sidebar-action {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
      width: 100%;
      padding: 0.875rem 1rem;
      border: 1px solid var(--border-color, var(--input-border-color, #3a3a3a));
      border-radius: 0.75rem;
      background: var(--comfy-input-bg);
      color: inherit;
      text-align: left;
      cursor: pointer;
      transition: border-color 0.15s ease, background-color 0.15s ease, transform 0.15s ease;
    }

    .ayon-sidebar-action:hover {
      background: var(--comfy-menu-bg);
      border-color: var(--theme-color);
      transform: translateY(-1px);
    }

    .ayon-sidebar-action-label {
      font-size: 0.95rem;
      font-weight: 600;
      line-height: 1.25rem;
    }

    .ayon-sidebar-action-description {
      color: var(--descrip-text);
      font-size: 0.8125rem;
      line-height: 1.125rem;
    }

    .ayon-sidebar-action:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      transform: none;
    }

    .ayon-sidebar-status {
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      padding: 0.75rem;
      border: 1px solid var(--border-color, var(--input-border-color, #3a3a3a));
      border-radius: 0.75rem;
      font-size: 0.8125rem;
      line-height: 1.125rem;
    }

    .ayon-sidebar-status-line {
      display: flex;
      gap: 0.5rem;
      align-items: baseline;
    }

    .ayon-sidebar-status-dot {
      flex-shrink: 0;
      width: 0.5rem;
      height: 0.5rem;
      border-radius: 50%;
      background: #d9a521;
    }

    .ayon-sidebar-status[data-level="ok"] .ayon-sidebar-status-dot {
      background: #3fa34d;
    }

    .ayon-sidebar-status[data-level="error"] .ayon-sidebar-status-dot {
      background: #d64545;
    }

    .ayon-sidebar-status-details {
      color: var(--descrip-text);
      font-size: 0.75rem;
      padding-left: 1rem;
    }

    .ayon-sidebar-pair {
      display: flex;
      gap: 0.5rem;
    }

    .ayon-sidebar-pair input {
      flex: 1;
      min-width: 0;
      padding: 0.25rem 0.5rem;
      border: 1px solid var(--border-color, var(--input-border-color, #3a3a3a));
      border-radius: 0.5rem;
      background: var(--comfy-input-bg);
      color: inherit;
    }

    .ayon-sidebar-small-button {
      padding: 0.25rem 0.75rem;
      border: 1px solid var(--border-color, var(--input-border-color, #3a3a3a));
      border-radius: 0.5rem;
      background: var(--comfy-input-bg);
      color: inherit;
      cursor: pointer;
    }

    .ayon-sidebar-status [hidden] {
      display: none;
    }
  `
  document.head.appendChild(style)
}

function register_ayon_sidebar_tab() {
  if (!app.extensionManager?.registerSidebarTab) {
    return
  }

  const existing_tabs = app.extensionManager.getSidebarTabs?.() ?? []
  if (existing_tabs.some((tab) => tab.id === AYON_SIDEBAR_TAB_ID)) {
    return
  }

  app.extensionManager.registerSidebarTab({
    id: AYON_SIDEBAR_TAB_ID,
    title: "AYON",
    tooltip: "AYON",
    icon: AYON_SIDEBAR_ICON_CLASS,
    type: "custom",
    render(container) {
      create_ayon_tool_panel(container)
    }
  })
}

// The prompts this tab queued, newest first, as {prompt_id, workflow_path}.
// The AYON host only publishes earlier runs ("Recook on publish" off) from
// these, and only those of the workflow being published, so it never picks
// up another artist's run, or a copied workflow's run, of the same AYON
// instance. Kept in sessionStorage so they survive reloads of the tab.
const AYON_QUEUED_PROMPTS_KEY = "ayon.queued_prompts"
const AYON_QUEUED_PROMPTS_LIMIT = 200

function get_queued_prompts() {
  try {
    const entries = JSON.parse(sessionStorage.getItem(AYON_QUEUED_PROMPTS_KEY) ?? "[]")
    return Array.isArray(entries)
      ? entries.filter((entry) => typeof entry?.prompt_id === "string")
      : []
  } catch (err) {
    return []
  }
}

function remember_queued_prompt(prompt_id, workflow_path) {
  if (typeof prompt_id !== "string" || !prompt_id) {
    return
  }
  try {
    const entries = get_queued_prompts().filter((entry) => entry.prompt_id !== prompt_id)
    entries.unshift({prompt_id, workflow_path: workflow_path ?? null})
    sessionStorage.setItem(
      AYON_QUEUED_PROMPTS_KEY,
      JSON.stringify(entries.slice(0, AYON_QUEUED_PROMPTS_LIMIT))
    )
  } catch (err) {
    console.warn("AYON: Unable to remember queued prompt", err)
  }
}

// Record every prompt this tab queues (Run, Queue, partial runs), with the
// workflow it was queued from.
function track_queued_prompts(api) {
  const original = api?.queuePrompt
  if (typeof original !== "function" || original.__ayon_tracked) {
    return
  }
  const tracked = async function (...args) {
    const workflow_path = get_workflow_store()?.activeWorkflow?.path
    const result = await original.apply(this, args)
    remember_queued_prompt(result?.prompt_id, workflow_path)
    return result
  }
  tracked.__ayon_tracked = true
  api.queuePrompt = tracked
}

// The `extra_data` the frontend adds when it queues a prompt itself
// (ComfyApi.queuePrompt): Comfy.org credentials for API nodes, and the
// preview method. ComfyUI keeps the credentials out of its history.
function queue_extra_data() {
  const extra = {}
  if (app.api.authToken) {
    extra.auth_token_comfy_org = app.api.authToken
  }
  if (app.api.apiKey) {
    extra.api_key_comfy_org = app.api.apiKey
  }
  const preview_method = app.extensionManager?.setting?.get?.("Comfy.Execution.PreviewMethod")
  if (preview_method && preview_method !== "default") {
    extra.preview_method = preview_method
  }
  return extra
}

// Queue just `node` so it shows its preview (load nodes only: they have no
// inputs to compute).
async function execute_single_node(node) {
  const prompt = await app.graphToPrompt()
  const id = `${node.id}`
  if (!prompt.output[id]) {
    return
  }
  await app.api.queuePrompt(0, {output: {[id]: prompt.output[id]}})
}

function preview_load_node(node) {
  execute_single_node(node).catch((err) => {
    console.warn("AYON: Unable to show the load node's preview", err)
  })
}

app.registerExtension({
    name: AYON_EXTENSION_NAME,
    async setup() {
        console.log("AYON")

        ensure_ayon_sidebar_style()
        register_ayon_sidebar_tab()
        track_queued_prompts(app.api)

        // v2 adapter for newer comfyui
        function get_workfiles_v2(){
          // Attempt OpenPaths first.
          const clientId = window.sessionStorage.getItem("clientId");
          const openpath_str = window.sessionStorage.getItem(`Comfy.Workflow.OpenPaths:${clientId}`)
          let path_str = null
          if (openpath_str !== null) {
            const openpath_parse = JSON.parse(openpath_str)
            path_str = openpath_parse.paths[openpath_parse.activeIndex]
          } else {
            path_str = window.sessionStorage.getItem(`Comfy.Workflow.ActivePath:${clientId}`);
            if (!path_str) {
              return null;
            }
            path_str = JSON.parse(path_str).path;
          }
          const path = path_str

          if (!path) {
            return null;
          }

          const draftindex_str = window.localStorage.getItem("Comfy.Workflow.DraftIndex.v2:personal");
          if (!draftindex_str) {
            return null;
          }

          const draftindex = JSON.parse(draftindex_str);
          const keys = Object.keys(draftindex.entries);

          const personal_key = keys.filter((key) => {
            if (draftindex.entries[key].path == path) {
              return true;
            }
          })[0]

          if (personal_key === undefined){
            return null;
          }

          const data_str = window.localStorage.getItem(`Comfy.Workflow.Draft.v2:personal:${personal_key}`);
          
          if (!data_str) {
            return null;
          }
          // workfiles data as a string
          const data = JSON.parse(data_str).data

          return data
        }

        function addNodeAtCenter_v1(type) {
          // Uses device pixel ratio to account for visible area at 100%
          const node = LiteGraph.createNode(type);
          app.graph.add(node);

          const va = app.canvas.visible_area;

          const w = node.size[0];
          const h = node.size[1];

          const dpr = window.devicePixelRatio;

          if (va) {
              node.pos = [
                  va[0] + va[2] / (2 * dpr) - (w / 2),
                  va[1] + va[3] / (2 * dpr) - (h / 2)
              ];
          }
          
          app.graph.setDirtyCanvas(true, true);
          return node;
        }

        function getViewportCenter() {
          const canvas = app.canvas;
          const rect = canvas.canvas.getBoundingClientRect();

          const center = canvas.convertEventToCanvasOffset({
            clientX: rect.left + rect.width / 2,
            clientY: rect.top + rect.height / 2
          });
        
          return center;
        }

        function addNodeAtCenter(type) {
          const node = LiteGraph.createNode(type);
          app.graph.add(node);

          const [cx, cy] = getViewportCenter();

          node.pos = [
            cx - node.size[0] / 2,
            cy - node.size[1] / 2
          ];

          app.graph.afterChange(); 
          app.graph.setDirtyCanvas(true, true);
          return node;
        }

        function ensureAyonContextNode() {
          // janky way of enforcing a single context node.
          const nodeType = "AYON Context"
          let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          if (foundNodes.length == 1){
            // already present
            return foundNodes[0]
          }
          else if (foundNodes.length > 1) {
            // remove any nodes but the first one if others have been created
            foundNodes.map((node, i) => {
              if (i > 0) {
                app.graph.remove(node)
              }
            })
            foundNodes.splice(1)
            return foundNodes[0]
          }
          else {
            return addNodeAtCenter("AYON Context")
          }

        }

        // Requests from the AYON host arrive over the bridge; the handlers
        // below run them against this tab's graph.
        const bridge = new AyonBridge(bridge_ws_url(app.api))
        BRIDGE = bridge
        this.bridge = bridge
        bridge.addEventListener("change", () => {
          update_status_views()
          notify_bridge_change(bridge)
        })
        bridge.addEventListener("notice", (event) => {
          show_toast("warn", event.detail)
        })

        // The API-format prompt of the active workflow, made by the
        // frontend's own conversion (bypass, subgraphs, reroutes,
        // primitives), for the AYON host to queue when publishing.
        bridge.register('getApiPrompt', async () => {
          const {output, workflow} = await app.graphToPrompt()
          return {
            prompt: output,
            workflow,
            client_id: app.api.clientId ?? app.api.initialClientId ?? null,
            workflow_path: get_workflow_store()?.activeWorkflow?.path ?? null,
            extra_data: queue_extra_data(),
          }
        })

        // The prompts this tab queued, newest first.
        bridge.register('getQueuedPrompts', () => {
          return {prompts: get_queued_prompts()}
        })


        bridge.register('getWorkfile', (data) => {
          // Serialize the live graph so the result always reflects the
          // current state, instead of ComfyUI's debounced storage drafts.
          const graph = get_root_graph()
          if (graph?.serialize) {
            return serialize_graph()
          }

          // Legacy fallback: fetch from session storage,
          // because workflows are saved as workflow:<id>
          const client = window.sessionStorage.getItem("clientId")
          let workfile = window.sessionStorage.getItem(`workflow:${client}`)
          if (workfile == null){
            workfile = get_workfiles_v2()
          }
          return workfile
        })

        // Allow host to set arbitrary extra metadata on the current graph
        bridge.register('setGraphExtra', (data) => {
          const extra = typeof data.extra_json === 'string' ? JSON.parse(data.extra_json) : data.extra_json
          const graph = get_root_graph()
          graph.extra ??= {}
          merge_into_extra(graph.extra, extra)
          sync_change_tracker()
          return true
        })

        // Return graph.extra (stringified JSON), optionally a single key.
        bridge.register('getGraphExtra', (data) => {
          const extra = get_root_graph()?.extra ?? {}
          if (data && data.key) {
            return JSON.stringify(extra[data.key] ?? null)
          }
          return JSON.stringify(extra)
        })

        // Return the AYON workfile path the current workflow was saved to or
        // opened from, or null when it is not (or no longer) an AYON workfile.
        bridge.register('getWorkfilePath', (data) => {
          const ayon = get_ayon_extra()
          const path = ayon?.workfile_path
          if (!path) {
            return null
          }

          // `graph.extra` is copied along when a user duplicates a workflow
          // or uses ComfyUI's own 'Save As'. Only trust the path for the
          // workflow (tab) it was recorded for, so we never report (and then
          // overwrite) another workflow's AYON workfile.
          const active = get_workflow_store()?.activeWorkflow
          if (ayon.comfy_workflow_path && active && active.path !== ayon.comfy_workflow_path) {
            console.debug(
              `AYON: Ignoring workfile path recorded for '${ayon.comfy_workflow_path}' ` +
              `because the active workflow is '${active.path}'`
            )
            return null
          }
          return path
        })

        // Step one of saving an AYON workfile: name the tab after the file,
        // record the AYON workfile path and return the serialized graph.
        // The host writes the result to disk, then calls `finishSaveWorkfile`.
        bridge.register('beginSaveWorkfile', async (data) => {
          const store = get_workflow_store()
          const workflow = store?.activeWorkflow ?? null
          const warnings = []
          let renamed = true

          if (workflow && data.workflow_name) {
            try {
              await rename_workflow(store, workflow, data.workflow_name)
            } catch (err) {
              renamed = false
              console.warn("AYON: Failed to rename workflow:", err)
              warnings.push(`Unable to rename ComfyUI workflow: ${err}`)
            }
          } else if (!workflow) {
            warnings.push("ComfyUI workflow store is unavailable; tab is not renamed or saved.")
          }

          set_ayon_extra({
            workfile_path: data.workfile_path,
            comfy_workflow_path: workflow?.path ?? null,
          })
          sync_change_tracker(workflow)

          return {
            workfile: serialize_graph(),
            // Only when the tab is named after the workfile do we also want
            // to save it inside ComfyUI (see `finishSaveWorkfile`)
            comfy_workflow_path: renamed ? (workflow?.path ?? null) : null,
            warnings,
          }
        })

        // Step two of saving an AYON workfile: after the host wrote the file
        // to disk, also save the workflow in ComfyUI so the tab is no longer
        // flagged as modified.
        bridge.register('finishSaveWorkfile', async (data) => {
          const store = get_workflow_store()
          if (!store || !data.comfy_workflow_path) {
            return false
          }
          const workflow = store.getWorkflowByPath(data.comfy_workflow_path)
          if (!workflow || !store.isActive(workflow)) {
            // User switched tabs in the meantime; do not save another tab.
            return false
          }
          const tracker = workflow.changeTracker
          if (typeof tracker?.prepareForSave === "function") {
            tracker.prepareForSave()
          } else {
            capture_tracker_state(tracker)
          }
          await store.saveWorkflow(workflow)
          return true
        })

        bridge.register('addPublishNode', (data) => {
          console.log("adding node...")
          const nodeType = data.node_type
          const save_node = addNodeAtCenter(nodeType)
          const info_widget = save_node.widgets.find(widget => widget.name == "ayon_info")
          const recook_widget = save_node.widgets.find(widget => widget.name == "recook")
          save_node.color = "#233"
          save_node.bgcolor = "#355"
          try {
            // associated instance information should be put on node.
            info_widget.value = data.instance_json
            const parsed = JSON.parse(data.instance_json)
            recook_widget.value = parsed.creator_attributes.force_recook_on_publish
            let productName = parsed.productName
            save_node.title = `AYON (${productName})`
            app.graph.setDirtyCanvas(true, true);
          } catch (error) {
            console.log(error)
            return false
          }
          return true
        })


        bridge.register('removePublishNodes', (data) => {
          const nodeType = data.node_type
          let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          
          let to_remove = [];
          let ayon_remove = [];

          foundNodes.forEach(node => {
            const info_widget = node.widgets.find(widget => widget.name == "ayon_info")
            const ayon_info = JSON.parse(info_widget.value)
            if (data.ids_to_remove.includes(ayon_info.instance_id)) {
              to_remove.push(node)
              ayon_remove.push(ayon_info)
            }
          });

          let json_removed = JSON.stringify(ayon_remove)

          to_remove.map((node) => {
            app.graph.remove(node)
          })
          
          return json_removed
        })

        bridge.register('addLoadProductNode', (data) => {
          const nodeType = data.node_type
          const loadimg_node = addNodeAtCenter(nodeType)
          const info_widget = loadimg_node.widgets.find(widget => widget.name == "ayon_container_info")
          info_widget.value = data.container_json

          const parsed = JSON.parse(data.container_json)
          let productName = parsed.name
          loadimg_node.title = `AYON Container (${productName})`
          loadimg_node.color = "#233"
          loadimg_node.bgcolor = "#355"
          app.graph.setDirtyCanvas(true, true);
          preview_load_node(loadimg_node)
          return true
        });

        bridge.register('removeLoadProductNodes', (data) => {
          const nodeType = data.node_type
          let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          
          let to_remove = [];
          let ayon_remove = [];

          foundNodes.forEach(node => {
            const info_widget = node.widgets.find(widget => widget.name == "ayon_container_info")
            const ayon_info = JSON.parse(info_widget.value)
            if (data.ids_to_remove.includes(ayon_info.container_uuid)) {
              to_remove.push(node)
              ayon_remove.push(ayon_info)
            }
          });

          let json_removed = JSON.stringify(ayon_remove)

          to_remove.map((node) => {
            app.graph.remove(node)
          })
          
          return json_removed
        })

        // Write an updated container onto its load node(s). Returns whether
        // a node with that container was found.
        bridge.register('updateLoadProductNode', (data) => {
          const nodeType = data.node_type
          const types = nodeType == "ALL"
            ? ["AYON Load Image", "AYON Load Video", "AYON Load 3D Model"]
            : [nodeType]
          const ayon_info_update = JSON.parse(data.container_json)

          let updated = false
          for (const node of app.graph.nodes) {
            if (!types.includes(node.type)) {
              continue
            }
            const info_widget = node.widgets?.find(widget => widget.name == "ayon_container_info")
            let ayon_info = null
            try {
              ayon_info = JSON.parse(info_widget?.value ?? "null")
            } catch (err) {
              console.warn(`AYON: Load node ${node.id} has invalid container data`, err)
              continue
            }
            if (ayon_info?.container_uuid !== ayon_info_update.container_uuid) {
              continue
            }
            updated = true
            if (info_widget.value === data.container_json) {
              // Unchanged (the host sends every container on an update):
              // don't queue a preview run for nothing.
              continue
            }
            info_widget.value = data.container_json
            preview_load_node(node)
          }
          if (updated) {
            app.graph.setDirtyCanvas(true, true)
          }
          return updated
        });


        bridge.register('setImprintContext', (data) => {
          console.log("setting context...", data)
          const imprint_node = ensureAyonContextNode()
          console.log(imprint_node)
          const info_widget = imprint_node.widgets.find(widget => widget.name == "ayon_context_info")
          console.log(imprint_node, info_widget)
          try {
            info_widget.value = data.imprint_info
            app.graph.setDirtyCanvas(true, true);
          } catch (error) {
            console.log(error)
            return false
          }
          return true
        })


        bridge.register('getImprintContext', (data) => {
          console.log("getting context...", data)
          const imprint_node = ensureAyonContextNode()
          console.log(imprint_node)
          const info_widget = imprint_node.widgets.find(widget => widget.name == "ayon_context_info")
          console.log(imprint_node, info_widget)
          try {
            return info_widget.value
          } catch (error) {
            console.log(error)
            return false
          }
        })

        bridge.register('loadWorkfile', async (data) => {
          const graph_data = JSON.parse(data.workfile_json)
          if (data.workfile_path) {
            // Record the AYON workfile path *before* loading, so that it
            // is part of the loaded state (no race with a separate call).
            graph_data.extra ??= {}
            graph_data.extra[AYON_EXTRA_KEY] = {
              ...(graph_data.extra[AYON_EXTRA_KEY] ?? {}),
              workfile_path: data.workfile_path,
              comfy_workflow_path: null,
            }
          }

          await app.loadGraphData(graph_data, true, true, data.workfile_name || null)

          // Record which ComfyUI workflow (tab) this AYON workfile lives in
          // and make that the change tracker baseline, so the freshly opened
          // tab is not flagged as modified.
          const workflow = get_workflow_store()?.activeWorkflow
          if (data.workfile_path && workflow) {
            set_ayon_extra({comfy_workflow_path: workflow.path})
            const tracker = workflow.changeTracker
            try {
              capture_tracker_state(tracker)
              tracker?.reset?.()
              tracker?.updateModified?.()
            } catch (err) {
              console.warn("AYON: Failed to reset change tracker:", err)
            }
          }
          return true
        })

        bridge.start()
    },
    commands: [
    {
      id: "AYON.Ping",
      label: "Ping AYON",
      function: async () => {
        const result = await call_ayon("pingAyonMenu", {message: "Ping from ComfyUI"})
        if (result !== null) {
          show_toast("info", `AYON answered: ${result}`, 3000)
        }
      }
    },
    ...AYON_TOOL_ACTIONS.map((action) => ({
      id: action.id,
      label: action.label,
      function: () => {
        request_ayon_tool(action.tool_name)
      }
    })),
    {
      id: AYON_SAVE_WORKFILE_COMMAND_ID,
      label: "Save Workfile",
      function: () => {
        // Saves to the current AYON workfile path, or opens the
        // Workfiles tool when the workflow isn't an AYON workfile yet.
        call_ayon("requestSaveWorkfile", {})
      }
    },
  ],
  // Add commands to menu
  menuCommands: [
    { 
      path: ["AYON"],
      commands: [
        AYON_SAVE_WORKFILE_COMMAND_ID,
        ...AYON_TOOL_ACTIONS.map((action) => action.id)
      ]
    },
  ]
})
