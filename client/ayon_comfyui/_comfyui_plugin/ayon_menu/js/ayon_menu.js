import { app } from "../../scripts/app.js";
import "../../../../extensions/ayon_menu/lib/wsrpc.js";
import {AYON_WEBUI_PORT} from "../../../../extensions/ayon_menu/lib/consts.js"

app.registerExtension({
    name: "comfy_ayon_menu",
    async setup() {
        console.log("AYON")
        //let port = window.location.port
        //let host = window.location.hostname
        //let url = (window.location.protocol==="https):"?"wss://":"ws://")+ host +":55055" + '/ws/';
        // RPC connection should actually be made with a localhost WSRPC port.
        function addNodeAtCenter(type) {
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
        // TODO: Account for https
        let url = `ws://localhost:${AYON_WEBUI_PORT}/ws/`
        this.RPC = new WSRPC(url);

        this.RPC.addRoute('getPublishNodes', (data) => {
          const nodeType = "AYON Image Save"

          let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          return JSON.stringify(foundNodes)
        })

        this.RPC.addRoute('getWorkfile', (data) => {
          // Fetch clientId from session storage,
          // because workflows are saved as workflow:<id>
          let client = window.sessionStorage.getItem("clientId")
          let workflow_key = `workflow:${client}`
          console.log("workfile requested", window.sessionStorage.getItem(workflow_key))
          return window.sessionStorage.getItem(workflow_key)
        })

        this.RPC.addRoute('imprint', (data) => {
          console.log("adding node...")
          const imprint_node = addNodeAtCenter("AYON Image Save")
          const info_widget = imprint_node.widgets.find(widget => widget.name == "ayon_info")
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

        this.RPC.addRoute('setImprintContext', (data) => {
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

        this.RPC.addRoute('getImprintContext', (data) => {
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

        this.RPC.addRoute('loadWorkfile', (data) => {
          console.log("loading from passed in Workfile")
          const workfile_parse = JSON.parse(data.workfile_json)
          try {
            app.loadGraphData(workfile_parse)
          } catch (error) {
            console.log(error)
            return false
          }
          return true
        })

        this.RPC.connect();
    },
    commands: [
    { 
      id: "myCommand", 
      label: "Ping Ayon Plugin Websocket RPC server", 
      function: () => {
        // find plugin in array
        const exts = app.extensions;
        const ext = exts.find((el) => el.name == "comfy_ayon_menu")

        // console.log(app.extensions);
        ext.RPC.call('ayonComfyUI.pingAyonMenu', {"message" :`Ping from web`}).then(function (data) {
        console.log('pong: ', data);
        }, function (error) {
          alert(error);
        });
      } 
    },

    { 
      id: "showWorkfiles", 
      label: "Workfiles", 
      function: () => {
        // find plugin in array
        const exts = app.extensions;
        const ext = exts.find((el) => el.name == "comfy_ayon_menu")

        console.log(app.extensions);
        ext.RPC.call('ayonComfyUI.requestToolByName', {"tool_name" : "workfiles"}).then(function (data) {
        console.log('pong: ', data);
        }, function (error) {
          alert(error);
        });
      } 
    },

    { 
      id: "showCreator", 
      label: "Creator", 
      function: () => {
        // find plugin in array
        const exts = app.extensions;
        const ext = exts.find((el) => el.name == "comfy_ayon_menu")

        console.log(app.extensions);
        ext.RPC.call('ayonComfyUI.requestToolByName', {"tool_name" : "create"}).then(function (data) {
        console.log('pong: ', data);
        }, function (error) {
          alert(error);
        });
      } 
    },

    { 
      id: "logGraph", 
      label: "log graph to console", 
      function: () => {
        console.log(app.graph.serialize())
        console.log(app.graph)
      } 
    },
    { 
      id: "logApp", 
      label: "log app object to console", 
      function: () => {
        console.log(app)
      } 
    },
  ],
  // Add commands to menu
  menuCommands: [
    { 
      path: ["AYON"],
      commands: ["myCommand","showWorkfiles","showCreator","logGraph","logApp"] 
    },
  ]
})