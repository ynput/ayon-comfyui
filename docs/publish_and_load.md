# Publishing and loading

## Publishing ComfyUI outputs

Publishing is driven by AYON, not by the browser. Each publish instance
(Image, Video, 3D Model) has an **AYON save node** in the graph. A save node
writes its files into its own folder in ComfyUI's output directory,
`AYON/<instance id>/<run id>/`, so runs of different products, runs and
artists never overwrite each other. It keeps its newest five runs (and
everything younger than a day).

What gets published depends on the node's **Recook on publish** toggle:

- **On**: when you publish, AYON queues the workflow as it was collected
  (see below) on ComfyUI itself, running only the AYON save nodes being
  published (and what they need). It then
  waits for the run in ComfyUI's history: there is no time limit, and the
  ComfyUI tab may be reloaded or closed meanwhile. The tab still shows the
  run's progress. A small "AYON - ComfyUI" window shows the progress too,
  with **Cancel render**; cancelling the run in ComfyUI's queue works as
  well.
- **Off**: AYON publishes the newest finished run of that save node that
  this AYON session or its ComfyUI tab queued from this workflow (the
  workflow keeps its identity when it is saved under a new workfile name;
  a duplicated workflow doesn't). Another artist's run of the same workfile
  is never used. Publishing waits for nothing: run the workflow first. If a
  newer run is still in progress, publishing asks you to wait for it.

The published version gets the files the save node wrote, a thumbnail, and
the run's API prompt and workflow as `instance.data["comfyui"]`.

### Working while publishing

A publish acts on one workflow (tab): the one whose instances the Publisher
shows. That tab must be the active one when you click Publish (or Validate);
otherwise the publish asks you to switch to it, or to refresh the Publisher
to publish the active workflow instead. AYON then collects the workflow
once, and everything after works from that:

- the workfile is saved with the collected workflow, and that's what the
  workfile product publishes;
- a recook renders the collected workflow, so its outputs match the
  published workfile and what was validated;
- versioning up the workfile afterwards saves that same tab, including
  what you changed in it meanwhile.

So you can keep working while it publishes: edit the graph, switch tabs,
open other workfiles, or use AYON > Save Workfile. Changes made after
collecting stay unsaved in the tab until you save it. Closing the published
tab doesn't stop the publish either, it just skips versioning up the
workfile.

The Publisher keeps working on the workflow it showed when it opened or
was last refreshed: creating, changing or removing its instances acts on
that workflow, also after you switched tabs. Adding or removing a save node
needs its tab to be the active one.

**Comfy.org API nodes** need your Comfy.org login. AYON reuses the login of
the last run you started in the ComfyUI tab; a login token expires after an
hour, so run the workflow once in the tab before a recook publish if it
fails as unauthorized.

## Loading products

Loaders put a load node in the graph with the product's container. By
default AYON **uploads** the files into ComfyUI's input directory: that works
wherever ComfyUI runs. Load nodes decode PNG, EXR, TIFF, DPX and HDR files
through ComfyUI's own decoder, so 16-bit and floating point images keep
their precision.

### Reference files instead of uploading (opt-in)

In the Loader's options, **Reference files on the ComfyUI server** makes the
load node read the published files where they are, without copying them:
quicker for large plates, and a hero version republished in place is picked
up by the next run. AYON only references the files when the ComfyUI server
reports it can read them; otherwise it uploads them as before, and says why
in the Loader's log and as a warning in the ComfyUI tab (e.g. ComfyUI has
no such AYON root, or ignores it). Updating a container keeps its mode.

The ComfyUI server must know where the AYON roots are on its side:

- `AYON_COMFYUI_ROOTS`: a JSON object of root name to path, e.g.
  `{"work": "/mnt/projects"}`, or the path of a JSON file with it.
- `<ComfyUI user directory>/__ayon/roots.json`, with the same object.
- `AYON_COMFYUI_PROJECTS`: project folders below the roots that may be
  read, as a JSON list or comma separated. Optional, except for a root
  that is a whole drive or share (see below).

When AYON launches ComfyUI locally it sets `AYON_COMFYUI_ROOTS` to this
machine's roots and `AYON_COMFYUI_PROJECTS` to the current project. For a
remote or shared ComfyUI, its administrator configures them.

A root that is a whole drive, share or filesystem (`P:\`, `\\nas\share`,
`/`) is only used while `AYON_COMFYUI_PROJECTS` limits it to project
folders; without that ComfyUI ignores the root (and logs why), so loads
upload instead. AYON sets both when it launches ComfyUI locally, so
projects on a drive letter or a share root can be referenced there; with
an explicit `AYON_COMFYUI_ROOTS`, set `AYON_COMFYUI_PROJECTS` as well.

!!! warning
    Anyone who can queue prompts on that ComfyUI can read media files below
    the configured roots through an AYON load node. On a shared server, map
    roots narrowly and set `AYON_COMFYUI_PROJECTS`, or don't configure roots
    (loading then always uploads). With `AYON_COMFYUI_PROJECTS` set, only
    files inside those project folders can be read, which is why a whole
    drive is only accepted as a root with it.

## Requirements

The AYON plugin installed on ComfyUI must match the addon: it reports the
features it supports (`publish-v1`, `paths-v1`), and AYON asks to update it
when one is missing.
