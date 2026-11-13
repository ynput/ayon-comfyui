// AYON pickers on the `AYON Load ...` nodes, see lib/ayon_pickers.js.
import { app } from "../../scripts/app.js";
import {
  LOAD_NODE_TYPES,
  LoadPicker,
  PickerHub,
  parse_json,
} from "./lib/ayon_pickers.js";

const AYON_MENU_EXTENSION = "AYON.ComfyMenu"
const BRIDGE_WAIT_MS = 30000

const HUB = new PickerHub(app)

// The bridge to AYON belongs to the AYON menu extension (ayon_menu.js).
async function wait_for_bridge() {
  const started = Date.now()
  while (Date.now() - started < BRIDGE_WAIT_MS) {
    const bridge = app.extensions
      ?.find((extension) => extension.name === AYON_MENU_EXTENSION)?.bridge
    if (bridge) {
      return bridge
    }
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  return null
}

// Run `after` once the AYON menu's handler for `method` is done, so the
// pickers show changes AYON makes to load nodes directly (Loader, Scene
// Inventory).
function after_handler(bridge, method, after) {
  const handler = bridge.handlers?.get(method)
  if (!handler) {
    console.warn(`AYON pickers: no '${method}' handler to follow`)
    return
  }
  bridge.register(method, async (params) => {
    const result = await handler(params)
    try {
      after(params)
    } catch (err) {
      console.warn(`AYON pickers: failed to follow '${method}'`, err)
    }
    return result
  })
}

app.registerExtension({
  name: "AYON.NodePickers",

  async setup() {
    const bridge = await wait_for_bridge()
    if (!bridge) {
      console.warn("AYON pickers: the AYON bridge is not available")
      return
    }
    HUB.attach(bridge)
    after_handler(bridge, "updateLoadProductNode", (params) => {
      const container = parse_json(params?.container_json)
      HUB.sync_container(container?.container_uuid ?? null)
    })
    after_handler(bridge, "addLoadProductNode", () => HUB.sync_container())
  },

  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!LOAD_NODE_TYPES.includes(nodeData?.name)) {
      return
    }

    const on_created = nodeType.prototype.onNodeCreated
    nodeType.prototype.onNodeCreated = function () {
      const result = on_created?.apply(this, arguments)
      try {
        this.ayon_picker = new LoadPicker(this, HUB)
        HUB.register(this.ayon_picker)
      } catch (err) {
        console.error("AYON pickers: unable to add the pickers", err)
      }
      return result
    }

    // After a workflow loads or a node is pasted: show the restored
    // container.
    const on_configure = nodeType.prototype.onConfigure
    nodeType.prototype.onConfigure = function () {
      const result = on_configure?.apply(this, arguments)
      if (this.ayon_picker) {
        this.ayon_picker.sync_from_container()
        HUB.register(this.ayon_picker)
      }
      return result
    }

    const on_removed = nodeType.prototype.onRemoved
    nodeType.prototype.onRemoved = function () {
      this.ayon_picker?.dispose()
      return on_removed?.apply(this, arguments)
    }
  },
})
