// Tests of the AYON node pickers' browser code (`js/lib/ayon_pickers.js`)
// with stand-ins for the ComfyUI graph and the AYON bridge.
//
// Run from the repository root with `node --test tests/js/pickers.test.mjs`.
import assert from "node:assert/strict"
import { test } from "node:test"

import {
  LoadPicker,
  PickerHub,
} from "../../client/ayon_comfyui/_comfyui_plugin/ayon_menu/js/lib/ayon_pickers.js"

// Don't let the pickers' long timeouts (a load waiting minutes for AYON)
// keep the test run alive; short ones (batching) still run normally.
const set_timeout = globalThis.setTimeout
globalThis.setTimeout = (callback, delay, ...args) => {
  const timer = set_timeout(callback, delay, ...args)
  if (delay > 1000) {
    timer.unref?.()
  }
  return timer
}

function make_node(type, container = null) {
  return {
    type,
    widgets: [{
      name: type === "AYON Context" ? "ayon_context_info" : "ayon_container_info",
      value: container === null ? "" : JSON.stringify(container),
    }],
    addWidget(widget_type, name, value, callback, options) {
      const widget = {type: widget_type, name, value, callback, options}
      this.widgets.push(widget)
      return widget
    },
    setDirtyCanvas() {},
  }
}

function make_hub(root) {
  const app = {rootGraph: root, extensionManager: {}}
  const hub = new PickerHub(app)
  hub.bridge = {connected: true}
  return hub
}

test("the status line tells when a node reads its files by path", () => {
  const container = {
    container_uuid: "u1",
    representation: "r",
    path_reference: {files: ["{root[work]}/a.png"]},
    selection: {product_name: "plateMain", version: 1, version_mode: "pinned"},
  }
  const node = make_node("AYON Load Image", container)
  const picker = new LoadPicker(node, make_hub({nodes: [node]}))
  picker.set_state("ok")
  assert.equal(picker.status_widget.label, "↻ plateMain v001 (by path) · refresh")

  node.widgets[0].value = JSON.stringify({...container, path_reference: null})
  picker.set_state("ok")
  assert.equal(picker.status_widget.label, "↻ plateMain v001 · refresh")
})

test("picker widgets are UI only", () => {
  const node = make_node("AYON Load Image")
  new LoadPicker(node, make_hub({nodes: [node]}))
  for (const widget of node.widgets.slice(1)) {
    assert.ok(widget.name.startsWith("ayon_pick_"), widget.name)
    assert.equal(widget.serialize, false)
    assert.equal(widget.options.serialize, false)
  }
})

test("containers without a load node are pruned from the context node", () => {
  const live = make_node("AYON Load Image", {container_uuid: "live"})
  const inner = make_node("AYON Load Video", {container_uuid: "inner"})
  const context = make_node("AYON Context", {
    context: {project: "demo"},
    instances: [{instance_id: "i1"}],
    containers: [
      {container_uuid: "live"},
      {container_uuid: "inner"},
      {container_uuid: "deleted"},
    ],
  })
  const root = {
    nodes: [live, context],
    subgraphs: new Map([["sg", {nodes: [inner]}]]),
  }
  const hub = make_hub(root)
  assert.equal(hub.prune_containers(), 1)
  const data = JSON.parse(context.widgets[0].value)
  assert.deepEqual(
    data.containers.map((item) => item.container_uuid), ["live", "inner"])
  // Everything else on the context node is kept.
  assert.deepEqual(data.instances, [{instance_id: "i1"}])
  assert.equal(hub.prune_containers(), 0)
})

test("status queries are split into batches the host accepts", async () => {
  const hub = make_hub({nodes: []})
  const sizes = []
  hub.call = async (method, params) => {
    assert.equal(method, "picker.status")
    sizes.push(params.representation_ids.length)
    return {items: Object.fromEntries(
      params.representation_ids.map((id) => [id, {representation_id: id}]))}
  }
  const ids = Array.from({length: 1200}, (_, index) => `r${index}`)
  const answers = await Promise.all(ids.map((id) => hub.status_of(id)))
  assert.deepEqual(sizes, [500, 500, 200])
  assert.deepEqual(answers.map((item) => item.representation_id), ids)
})

test("updating to the latest version keeps or replaces the representation",
  async () => {
    const container = {
      container_uuid: "11111111-2222-4333-8444-555555555555",
      representation: "r1",
      selection: {
        folder_id: "f", product_id: "p", product_name: "renderMain",
        version_mode: "latest", version_id: "v1", version: 1,
        representation_name: "exr",
      },
    }
    const node = make_node("AYON Load Image", container)
    const hub = make_hub({nodes: [node]})
    const calls = []
    hub.call = async (method, params) => {
      calls.push([method, params])
      if (method === "picker.options") {
        // The new version has no exr.
        return {
          products: [{id: "p", name: "renderMain"}],
          versions: [{id: "v2", version: 2, label: "v002"}],
          version_id: "v2",
          representations: [{id: "r2", name: "png"}],
        }
      }
      return {scheduled: true}
    }
    const picker = new LoadPicker(node, hub)
    picker.latest = {id: "v2", version: 2}
    picker.state = {kind: "update", text: ""}
    await picker.update_to_latest()
    const apply = calls.find(([method]) => method === "picker.apply")[1]
    assert.equal(apply.version_mode, "latest")
    assert.equal(apply.representation_name, "png")
    assert.equal(apply.container_uuid, container.container_uuid)
  })

// Runs `func` with the pickers' long timers (> 1 s) captured instead of
// started; returns them, for the test to fire.
async function with_long_timers(func) {
  const timers = []
  const saved = globalThis.setTimeout
  globalThis.setTimeout = (callback, delay, ...args) => {
    if (delay > 1000) {
      timers.push(() => callback(...args))
      return 0
    }
    return saved(callback, delay, ...args)
  }
  try {
    await func()
  } finally {
    globalThis.setTimeout = saved
  }
  return timers
}

// A picker that picked renderMain, and the AYON Context node of its graph.
function make_pick() {
  const node = make_node("AYON Load Image")
  const context = make_node("AYON Context",
    {context: {}, instances: [], containers: []})
  const root = {nodes: [node, context]}
  node.graph = root
  const hub = make_hub(root)
  const toasts = []
  hub.toast = (severity, detail) => toasts.push([severity, detail])
  hub.call = async () => ({scheduled: true})
  const picker = new LoadPicker(node, hub)
  // No AYON queries for the lists.
  picker.refresh = async () => {}
  picker.selection = {
    folder_id: "f", product_id: "p", product_name: "renderMain",
    version_mode: "latest", representation_name: "png",
  }
  return {node, context, hub, picker, toasts}
}

// The node gave up waiting for AYON to load what it picked, e.g. while AYON
// was busy publishing; returns the load's token.
async function load_taking_long(picker) {
  const timers = await with_long_timers(() => picker.apply())
  const token = picker.applying
  assert.ok(token)
  timers.forEach((fire) => fire())
  assert.equal(picker.applying, null)
  return token
}

test("a load answered after the node stopped waiting still updates it",
  async () => {
    const {node, context, hub, picker, toasts} = make_pick()
    const token = await load_taking_long(picker)
    assert.equal(picker.state.kind, "busy")
    assert.equal(toasts.length, 1)

    const container = {container_uuid: "u1", representation: "r1"}
    const answer = {token, container_json: JSON.stringify(container)}
    assert.equal(hub.on_applied(answer), true)
    assert.deepEqual(JSON.parse(node.widgets[0].value), container)
    assert.deepEqual(
      JSON.parse(context.widgets[0].value).containers, [container])
    assert.equal(picker.state.kind, "ok")
    // Only once.
    assert.equal(hub.on_applied(answer), false)
  })

test("a newer load replaces a load the node stopped waiting for",
  async () => {
    const {node, hub, picker} = make_pick()
    const late = await load_taking_long(picker)
    await with_long_timers(() => picker.apply())
    const newer = picker.applying
    assert.ok(newer && newer !== late)

    // The older load's answer comes after all: the newer pick wins.
    const container = {container_uuid: "old", representation: "r1"}
    assert.equal(hub.on_applied(
      {token: late, container_json: JSON.stringify(container)}), false)
    assert.equal(node.widgets[0].value, "")
    assert.equal(picker.applying, newer)
  })

test("a newer load AYON refused keeps the late answer", async () => {
  const {node, hub, picker} = make_pick()
  const late = await load_taking_long(picker)
  hub.call = async () => {
    throw new Error("AYON is still loading into this node.")
  }
  await picker.apply()
  assert.equal(picker.applying, null)

  const container = {container_uuid: "u1", representation: "r1"}
  assert.equal(hub.on_applied(
    {token: late, container_json: JSON.stringify(container)}), true)
  assert.deepEqual(JSON.parse(node.widgets[0].value), container)
})
