// Tests of `ayon_workflows.js`: run with `node tests/js/workflows.test.mjs`.
import assert from "node:assert/strict"
import test from "node:test"

import {
  WorkflowKeys,
  read_stored_context,
  stored_state,
  write_stored_context,
} from "../../client/ayon_comfyui/_comfyui_plugin/ayon_menu/js/lib/ayon_workflows.js"

class MemoryStorage {
  constructor() {
    this.items = new Map()
  }

  getItem(key) {
    return this.items.has(key) ? this.items.get(key) : null
  }

  setItem(key, value) {
    this.items.set(key, String(value))
  }
}

function workflow(path, state = null) {
  let modified = 0
  return {
    path,
    filename: path.split("/").pop(),
    activeState: state,
    changeTracker: {updateModified: () => { modified += 1 }},
    modified: () => modified,
  }
}

test("keys are unique per open workflow and stable", () => {
  const keys = new WorkflowKeys(new MemoryStorage())
  const v001 = workflow("workflows/shot_v001.json")
  const copy = workflow("workflows/shot_v001 (2).json")
  assert.equal(keys.key(v001), keys.key(v001))
  assert.notEqual(keys.key(v001), keys.key(copy))
  assert.equal(keys.find([copy, v001], keys.key(v001)), v001)
  assert.equal(keys.find([copy, v001], "other"), null)
  assert.equal(keys.key(null), null)
})

test("a renamed workflow keeps its key, also after a reload", () => {
  const storage = new MemoryStorage()
  const keys = new WorkflowKeys(storage)
  const tab = workflow("workflows/Unsaved Workflow.json")
  const key = keys.key(tab)
  // AYON saves a workfile by renaming the tab.
  tab.path = "workflows/shot_v001.json"
  assert.equal(keys.key(tab), key)

  // Reloading the page restores the tab as a new object.
  const reloaded = new WorkflowKeys(storage)
  assert.equal(reloaded.key(workflow("workflows/shot_v001.json")), key)
  // The old path no longer has that key.
  assert.notEqual(reloaded.key(workflow("workflows/Unsaved Workflow.json")), key)
})

test("a workflow opened at a path another one left gets its own key", () => {
  const keys = new WorkflowKeys(new MemoryStorage())
  // Saved as v002 (renamed) without asking for its key after the rename.
  const v001 = workflow("workflows/shot_v001.json")
  const key = keys.key(v001)
  v001.path = "workflows/shot_v002.json"
  // v001 opened again next to it.
  const reopened = workflow("workflows/shot_v001.json")
  assert.notEqual(keys.key(reopened), key)
  assert.equal(keys.find([v001, reopened], key), v001)

  // Closed, and a new workflow at its path.
  const unsaved = workflow("workflows/Unsaved Workflow.json")
  const unsaved_key = keys.key(unsaved)
  assert.notEqual(keys.key(workflow("workflows/Unsaved Workflow.json")), unsaved_key)
})

test("a stored key is restored once, and never to a second workflow", () => {
  const storage = new MemoryStorage()
  const before = new WorkflowKeys(storage)
  const key = before.key(workflow("workflows/a.json"))

  const after = new WorkflowKeys(storage)
  const restored = workflow("workflows/a.json")
  assert.equal(after.key(restored), key)
  // E.g. restored, closed, and opened again: a new workflow.
  assert.notEqual(after.key(workflow("workflows/a.json")), key)
})

test("the page id is per browser tab", () => {
  const storage = new MemoryStorage()
  const page = new WorkflowKeys(storage).page_id()
  // Reloaded: same session storage.
  assert.equal(new WorkflowKeys(storage).page_id(), page)
  // Another browser tab: its own session storage.
  assert.notEqual(new WorkflowKeys(new MemoryStorage()).page_id(), page)
})

test("keys work without storage", () => {
  const keys = new WorkflowKeys(null)
  const tab = workflow("workflows/a.json")
  assert.ok(keys.key(tab))
  assert.equal(keys.key(tab), keys.key(tab))
})

test("the context node of a workflow that isn't active", () => {
  const state = {nodes: [
    {id: 1, type: "KSampler", widgets_values: [1, 2]},
    {id: 2, type: "AYON Context", widgets_values: ['{"instances": []}']},
  ]}
  const tab = workflow("workflows/a.json", state)
  assert.equal(read_stored_context(stored_state(tab)), '{"instances": []}')
  write_stored_context(tab, '{"instances": [1]}')
  assert.equal(state.nodes[1].widgets_values[0], '{"instances": [1]}')
  assert.equal(tab.modified(), 1)
})

test("a workflow without context node or state", () => {
  const tab = workflow("workflows/a.json", {nodes: []})
  assert.equal(read_stored_context(stored_state(tab)), "")
  assert.throws(() => write_stored_context(tab, "{}"), {code: "workflow_inactive"})
  assert.throws(
    () => stored_state(workflow("workflows/b.json")),
    {code: "workflow_unavailable"}
  )
})
