import pyblish.api
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import KnownPublishError


class CollectCurrentFile(pyblish.api.ContextPlugin):
    """Inject the current working file into context

    Note that ComfyUI does not represent files on disk natively. As such, all
    we can track is whether the current graph in some way was stored on disk
    at some point, if we have stored that as metadata in the graph.

    That's the AYON workfile of the workflow being published, as collected
    by `CollectComfyUIWorkflow`.
    """

    order = pyblish.api.CollectorOrder - 0.5
    label = "Current Workfile"
    hosts = ["comfyui"]

    def process(self, context):
        host = registered_host()
        api_prompt = context.data.get("comfyuiApiPrompt")
        if api_prompt is None:
            path = host.get_current_workfile()
        else:
            path = host.trusted_workfile_path(api_prompt.get("workfile_path"))
            other_tab = api_prompt.get("workfile_open_in")
            if path and other_tab:
                # Saving it would overwrite what the other tab shows (an
                # AYON workfile belongs to a single tab).
                msg = (
                    f"The AYON workfile '{path}' is also open in the ComfyUI "
                    f"tab '{other_tab}'. Close one of them and publish again."
                )
                raise KnownPublishError(msg)
        context.data["currentFile"] = path
        self.log.debug(f"Current workfile: {path}")
        if path is None:
            self.log.warning("Current workfile is unsaved.")
