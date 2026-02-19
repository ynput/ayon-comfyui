# Ayon ComfyUI
Integration for ComfyUI inside the AYON ecosystem.


Featuring plentiful abuse of Websockets.

Some issues I had, explored and solved are on the Ayon Forums:

https://community.ynput.io/t/associating-a-custom-host-with-an-addon/2898

To outline how I plan to keep everything in sync:
- The "front end" (ayon plugin) sends over ip and hostname and a UUID
- the "back end" (ComfyUI plugin) sends over a hash based on these.
- The "back end" creates an entry for the current session and associates the UUID with the generated hash

Notes:

It seems that graph info is only accessible through js as well as many other things.

images belonging to nodes are accessible by querying the app state holder object graph, then matching node `type` in the app.graph.nodes array (watch out, initially the `title` is the same, but this can be edited),

```js
const nodeType = "Ayon_node_id_as_defined_in_python"

let foundNodes = app.graph.nodes.filter((node) => node.type == nodeType);

// API point to view image
const baseurl =  `${window.location.protocol}//${window.location.host}/api/view`;

// Array[Array[url]] -> flat -> Array[url]
// retrieve URLs for downloading the image
let urls = foundNodes.map((node) => 
    node.images.map((image) => 
        `${baseurl}?filename=${image.filename}&subfolder=${image.subfolder}&type=${image.type}`
    )
).flat()
```

`node.is_selected` holds whether a node is selected

`app.canvas.selected_nodes` holds selected nodes

`node.widgets` holds a list of on-node elements that can hold a `node.widgets[index].value` (lazy evaluated)

/history/<prompt_id> endpoint holds metadata on some execution including saved images

We can partially copy nodes.py -> SaveImage to look at how batching images work, use the filename to encode things about the asset like representation ID and then urlretrieve a list of images to download. Alternatively, a protocol can be thought up to "prepare" AYON to download some images to the right folder by causing a flag update before cook or something along those lines.

For the SaveImage node to work, we plugins to go through the process of:
- creating a product and making sure it's in the scene (Called "imprinting" in AYON terminology)
- collecting information about containers (api/pipeline > `ls()`, `Host.get_containers()`)
- actually publishing the thing

Note: We might need different nodes for 8bit png, 16 bit png, exr, and with exr we'd need to actually create the file serverside requiring the OpenEXR python module.

Some other notes:

- We can't register functions on JS clientside to be called from the server without proper connection ID context

the imprint to context needs to behave more like photoshop's imprint function to accomodate for insertion of more data.

---

For running ComfyUI through python, ive made a system of letting people select their own python source,
or if they haven't, that it can be deduced.

From there on out the plugin, if told (default = on) to make a managed environment,
will make a local python environment and pip install all the requirements to it.

The python embedded version had this _pth file screwing up the environment that was rightfully set in the thing.

I was unable to get comfyui to work with a regular 3.13 but it at least could import the "comfy" module.
the _pth file sets the path for that interpreter specifically.