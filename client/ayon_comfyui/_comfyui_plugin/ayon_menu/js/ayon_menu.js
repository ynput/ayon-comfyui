import { app } from "../../scripts/app.js";
import "../../../../extensions/ayon_menu/lib/wsrpc.js";
import {RPCServer} from "../../../../extensions/ayon_menu/lib/rpc_server.js"
import {AYON_ORIGIN_ADRESS} from "../../../../extensions/ayon_menu/lib/consts.js"

app.registerExtension({
    name: "comfy_ayon_menu",
    async afterConfigureGraph(graphData) {

        async function execute_single_node(node) {
          const proompt = await app.graphToPrompt(node.graph);
          const id = `${node.id}`;
          const output_obj = {}
          output_obj[id] = proompt.output[id]
          
          const prompt_t = {
            output: output_obj  
          };
          
          console.log(prompt_t)
          await app.api.queuePrompt(0,prompt_t);
        }

        async function generate_thumbnails_loadimage_nodes(){
          const nodeType = "AYON Load Image"
          let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          console.log(foundNodes)
          foundNodes.forEach((node) => {
            console.log(node)
            execute_single_node(node);
          })
        }

        async function generate_thumbnails_loadvideo_nodes(){
          const nodeType = "AYON Load Video"
          let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          console.log(foundNodes)
          foundNodes.forEach((node) => {
            console.log(node)
            execute_single_node(node);
          })
        }

        async function generate_thumbnails_load3dmodel_nodes(){
          const nodeType = "AYON 3D Model Save"
          let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          console.log(foundNodes)
          foundNodes.forEach((node) => {
            console.log(node)
            execute_single_node(node);
          })
        }

        console.log("AYON: Graph loaded.");
        // generate thumbnails for AYON Load Images / AYON Load Videos
        requestAnimationFrame(() =>{
          console.log("animation frame retrieved, cooking Load Image thumbnails")
          generate_thumbnails_loadimage_nodes()
          generate_thumbnails_loadvideo_nodes()
          generate_thumbnails_load3dmodel_nodes() // Don't know if this will actually make UI thumbnails, but it will at least load stuff in memory
      })
    },
    async setup() {
        console.log("AYON")

        this.map_images = new Map()
        this.expecting_id = null
        this.resolved_id = null

        function get_this() {
          const exts = app.extensions;
          return exts.find((el) => el.name == "comfy_ayon_menu")
        }

        function reset_expectations(expecting = null) {
          const local_this = get_this()
          local_this.expecting_id = expecting
          local_this.resolved_id = null
        }

        function predictate_is_resolved(){
          const local_this = get_this()
          return local_this.expecting_id == local_this.resolved_id
        }

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

        app.api.addEventListener("executed", (e) => {
          console.log("EXECUTED EVENT:", e.detail);
          const local_this = get_this()
          // map node id (e.g. '29') to array of output images.
          local_this.map_images[e.detail.node] = e.detail.output?.images;
          local_this.resolved_id = e.detail.node
          console.log(local_this)
        })

        function waitForFlag(getFlagFn, interval = 100) {
          return new Promise((resolve) => {
              const timer = setInterval(() => {
                  try {
                      if (getFlagFn()) {
                          clearInterval(timer);
                          resolve();
                      }
                  } catch (err) {
                      clearInterval(timer);
                      throw err; // Stop if condition function throws
                  }
              }, interval);
          });
        }

        async function execute_single_node(node) {
          const proompt = await app.graphToPrompt(node.graph);
          const id = `${node.id}`;
          const output_obj = {}
          output_obj[id] = proompt.output[id]
          
          const prompt_t = {
            output: output_obj  
          };
          console.log(prompt_t)
          await app.api.queuePrompt(0,prompt_t);
        }

        async function execute_node_subgraph(node_out) {
          const proompt = await app.graphToPrompt(node_out.graph);
        
          const subgraph = {};
          const stack = [node_out.id];
        
          while (stack.length) {
            const id = stack.pop();
            if (subgraph[id]) continue;
          
            const node = proompt.output[id];
            if (!node) continue;
          
            subgraph[id] = node;
          
            for (const input of Object.values(node.inputs || {})) {
              if (Array.isArray(input)) {
                stack.push(input[0]);
              }
            }
          }
          console.log(subgraph)
          return await app.api.queuePrompt(0, {
            output: subgraph
          });
        }

        async function getNodeImages(node,recook) {
          const local_this = get_this();
          
          if (!recook){
            return local_this.map_images[node.id]
          }

          reset_expectations(node.id)
          await execute_node_subgraph(node)
          await waitForFlag(() => predictate_is_resolved())
          reset_expectations()

          return local_this.map_images[node.id]
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

        async function nodeRetrieveImages(node, recook) {
          // API point to view image
          const baseurl =  `${window.location.protocol}//${window.location.host}/api/view`;
          // look into if '/' or '\\' in url doesn't give any problems
          console.log("getNodeImages")
          // Flatten in case of "animated" output. This outputs a list of arrays.
          const images = (await getNodeImages(node, recook)).flat()
          let urls = images.map((image) => 
            `${baseurl}?filename=${image.filename}&subfolder=${image.subfolder.replace("\\","/")}&type=${image.type}`)
            .flat()
          return urls
        }

        // DO NOT THE WSRPC HERE, WE DO IFRAME THROUGH PROXY.JS
        // Retrieve host URL from consts. Will always be http
        this.IFRAMERPC = new RPCServer(window.parent, AYON_ORIGIN_ADRESS)

        this.PROC_QUEUE = new Array()

        console.log(this.PROC_QUEUE)

        this.IFRAMERPC.register("alert", (data) => {
          console.log("from parent iframe:", data.text);
          alert(data.text)
        });

        function retrieve_latest_procqueue() {
          const exts = app.extensions;
          const ext = exts.find((el) => el.name == "comfy_ayon_menu")
          if (ext.PROC_QUEUE.length > 0)
            return ext.PROC_QUEUE.pop()
          return null
        }

        this.IFRAMERPC.register("pop_process", (data) => {
          let result = retrieve_latest_procqueue()
          if (result !== null)
            console.log("pop_process",result)
          return result
        })

        this.IFRAMERPC.register('getPublishNodes', (data) => {
          const nodeType = data.node_type

          let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          return JSON.stringify(foundNodes)
        })


        this.IFRAMERPC.register('getWorkfile', (data) => {
          // Fetch clientId from session storage,
          // because workflows are saved as workflow:<id>
          const client = window.sessionStorage.getItem("clientId")
          const workflow_key = `workflow:${client}`
          let workfile = window.sessionStorage.getItem(workflow_key)
          if (workfile == null){
            // overwrite workfile in case of new API for this. Gets current tab.
            workfile = get_workfiles_v2()
          }
          console.log("workfile requested", workfile)
          return workfile
        })

        this.IFRAMERPC.register('updateTab', (data) => {
          console.log(data);
          app.loadGraphData(app.graph.serialize(), true, true, data.new_name);
          return true;
        })

        this.IFRAMERPC.register('addPublishNode', (data) => {
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


        this.IFRAMERPC.register('removePublishNodes', (data) => {
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

        this.IFRAMERPC.register('getPublishNodeImages', async (data) => {
          const nodeType = data.node_type;
          let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          console.log("getting publish node images", data)
          for (const node of foundNodes) {

            const info_widget = node.widgets.find(widget => widget.name == "ayon_info");
            const ayon_info = JSON.parse(info_widget.value);
            // let recook = ayon_info.creator_attributes.force_recook_on_publish;

            const recook_widget = node.widgets.find(widget => widget.name == "recook")
            const recook = recook_widget.value

            console.log(ayon_info, data.id_for_images)

            if (data.id_for_images == ayon_info.instance_id) {
              console.log("Retrieving images")
              let imgs = await nodeRetrieveImages(node, recook);
              console.log(imgs);
              return JSON.stringify(imgs);
            }
  
            }
          return JSON.stringify([]); // none found
        });

        this.IFRAMERPC.register('addLoadProductNode', (data) => {
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
          execute_single_node(loadimg_node); // make sure image shows up
          return true
        });

        this.IFRAMERPC.register('removeLoadProductNodes', (data) => {
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

        this.IFRAMERPC.register('updateLoadProductNode', async (data) => {
          const nodeType = data.node_type
          let foundNodes = null

          
          if (nodeType == "ALL") {
            const nodes = ["AYON Load Image", "AYON Load Video", "AYON Load 3D Model"]
            foundNodes = app.graph.nodes.filter((node) => nodes.includes(node.type));
          } else {
            foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);
          }
          const ayon_info_update = JSON.parse(data.container_json)

          foundNodes.forEach(async (node) => {
            const info_widget = node.widgets.find(widget => widget.name == "ayon_container_info")
            const ayon_info = JSON.parse(info_widget.value)
            if (ayon_info_update.container_uuid == ayon_info.container_uuid) {
              info_widget.value = data.container_json
              execute_single_node(node); // make sure image shows up
              return true
            }
          });
          return true
        });

        

        this.IFRAMERPC.register('setImprintContext', (data) => {
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


        this.IFRAMERPC.register('getImprintContext', (data) => {
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

        this.IFRAMERPC.register('loadWorkfile', (data) => {
          console.log("loading from passed in Workfile")
          const workfile_parse = JSON.parse(data.workfile_json)
          try {
            if (data.workfile_name) {
              app.loadGraphData(workfile_parse, true, true, data.workfile_name)
            } else {
              app.loadGraphData(workfile_parse)
            }
              
          } catch (error) {
            console.log(error)
            return false
          }
          return true
        })

      
        //this.RPC.connect();
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
        ext.PROC_QUEUE.push({function: 'ayonComfyUI.pingAyonMenu',args: {"message" :`Ping from web`}})
        // ext.RPC.call('ayonComfyUI.pingAyonMenu', {"message" :`Ping from web`}).then(function (data) {
        // console.log('pong: ', data);
        // }, function (error) {
        //   alert(error);
        // });
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
        ext.PROC_QUEUE.push({function: 'ayonComfyUI.requestToolByName',args: {"tool_name" : "workfiles"}})
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
        ext.PROC_QUEUE.push({function:'ayonComfyUI.requestToolByName', args: {"tool_name" : "create"}})
      } 
    },
    { 
      id: "showPublisher", 
      label: "Publisher", 
      function: () => {
        // find plugin in array
        const exts = app.extensions;
        const ext = exts.find((el) => el.name == "comfy_ayon_menu")

        console.log(app.extensions);
        ext.PROC_QUEUE.push({function:'ayonComfyUI.requestToolByName', args: {"tool_name" : "publisher"}})
      } 
    },
    { 
      id: "showLoader", 
      label: "Loader", 
      function: () => {
        // find plugin in array
        const exts = app.extensions;
        const ext = exts.find((el) => el.name == "comfy_ayon_menu")

        console.log(app.extensions);
        ext.PROC_QUEUE.push({function:'ayonComfyUI.requestToolByName', args: {"tool_name" : "loader"}})
      } 
    },

    { 
      id: "showInventory", 
      label: "Scene Inventory", 
      function: () => {
        // find plugin in array
        const exts = app.extensions;
        const ext = exts.find((el) => el.name == "comfy_ayon_menu")

        console.log(app.extensions);
        ext.PROC_QUEUE.push({function:'ayonComfyUI.requestToolByName', args: {"tool_name" : "sceneinventory",}})
      } 
    },

    {
      id: "saveLocal",
      label: "Ayon Save Workfile",
      function: () => {
        function showToast(text, duration = 2000) {
          const el = document.createElement("div");
          el.textContent = text;
              
          Object.assign(el.style, {
              position: "fixed",
              top: "10px",
              left: "10px",
              background: "#249b9b",
              color: "white",
              padding: "8px 12px",
              borderRadius: "6px",
              zIndex: 9999,
              fontSize: "14px",
              fontFamily: "sans-serif",
              boxShadow: "0 2px 6px rgba(0,0,0,0.3)",
              opacity: "1",
              transition: "opacity 0.3s ease"
          });
        
          // attach to ComfyUI root instead of body if possible
          (app.canvasElRef?.parentElement || document.body).appendChild(el);
        
          setTimeout(() => {
              el.style.opacity = "0";
              setTimeout(() => el.remove(), 300);
          }, duration);
        }

        // v2 adapter for newer comfyui
        function get_workfiles_save() {
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
        
        console.log("called save local")
        // Attempt OpenPaths first, to get current tab.  
        const clientId = window.sessionStorage.getItem("clientId");
        const openpath_str = window.sessionStorage.getItem(`Comfy.Workflow.OpenPaths:${clientId}`)
        let path_str = null
        if (openpath_str !== null) {
          const openpath_parse = JSON.parse(openpath_str)
          path_str = openpath_parse.paths[openpath_parse.activeIndex]
        } else {
          const activepath_str = window.sessionStorage.getItem(`Comfy.Workflow.ActivePath:${clientId}`);
          path_str = JSON.parse(activepath_str).path;
          if (!path_str) {
            return null;
          }
        }
        const path = path_str

        const formatted_path = path.replace(".json","").replace("workflows/","")
      

        // find plugin in array
        const exts = app.extensions;
        const ext = exts.find((el) => el.name == "comfy_ayon_menu")

        const workfile = get_workfiles_save()

        ext.PROC_QUEUE.push({function:'ayonComfyUI.requestSaveByName', args: {"file_name" : `${formatted_path}`, "workfile_contents": `${workfile}`}})

        showToast("Ayon Saved!")
        
      }


    },
  ],
  // Add commands to menu
  menuCommands: [
    { 
      path: ["AYON"],
      commands: ["showPublisher","showCreator","showWorkfiles","showLoader","showInventory"] 
    },
  ]
})