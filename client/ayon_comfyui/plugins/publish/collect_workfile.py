import os
import re

import pyblish.api
from ayon_comfyui.api.pipeline import ComfyUIHost
from ayon_core.pipeline import (
    registered_host,
)


class CollectWorkfile(pyblish.api.InstancePlugin):
    """Collect current script for publish."""

    order = pyblish.api.CollectorOrder + 0.1
    label = "Collect Workfile"
    hosts = ["comfyui"]
    families = ["workfile"]

    default_variant = "Main"

    def process(self, instance):
        proj = os.environ.get("AYON_PROJECT_NAME")[:3]
        task = os.environ.get("AYON_TASK_NAME")
        folder = os.environ.get("AYON_FOLDER_PATH").split("/")[-1]
        workdir = os.environ.get("AYON_WORKDIR")
        self.log.debug(workdir)

        regex = rf"{proj}_{folder}_{task}" + r"_v(\d{3})[\w\.]+"
        self.log.debug(os.listdir(workdir))
        self.log.debug(regex)
        files = [
            file for file in os.listdir(workdir) if file.endswith(".json")
        ]
        self.log.debug(files)
        vers = [
            int(re.match(regex, file).group(1))
            for file in files
            if re.match(regex, file) is not None
        ]
        max_ver = max(vers) if vers else 1

        max_file = next(
            (file for file in files if f"v{max_ver:03}" in file), None
        )

        ext = ".json"
        instance.data["anatomyData"] = instance.context.data["anatomyData"]
        self.log.debug(instance.data["anatomyData"])
        instance.data["do_increment"] = True

        # staging_dir = get_instance_staging_dir(instance)
        staging_dir = workdir

        if not vers or max_file is None:
            max_file = f"{proj}_{folder}_{task}_v{max_ver:03}.json"
            host: ComfyUIHost = registered_host()
            host.save_workfile(os.path.join(staging_dir, max_file))
            instance.data["do_increment"] = False
        else:
            pass
            # save_next_version will do this
            # source = os.path.join(workdir, max_file)
            # destination = os.path.join(staging_dir, max_file)
            #
            # shutil.copy2(source, destination)

        instance.context.data["currentFile"] = max_file

        # creating representation
        instance.data["representations"].append(
            {
                "name": ext[1:],
                "ext": ext[1:],
                "files": max_file,
                "stagingDir": staging_dir,
            }
        )
