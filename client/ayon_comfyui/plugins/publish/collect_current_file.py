import pyblish.api

from ayon_core.pipeline import registered_host


class CollectCurrentFile(pyblish.api.ContextPlugin):
    """Inject the current working file into context

    Note that ComfyUI does not represent files on disk natively. As such, all
    we can track is whether the current graph in some way was stored on disk
    at some point, if we have stored that as metadata in the graph.
    """

    order = pyblish.api.CollectorOrder - 0.5
    label = "Current Workfile"
    hosts = ["comfyui"]

    def process(self, context):
        host = registered_host()
        path = host.get_current_workfile()
        context.data["currentFile"] = path
        self.log.debug(f"Current workfile: {path}")
        if path is None:
            self.log.warning("Current workfile is unsaved.")
