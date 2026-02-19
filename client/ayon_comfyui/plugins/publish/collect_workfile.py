import os
import re
import shutil

import pyblish.api
from ayon_comfyui.api.pipeline import ComfyUIHost
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import get_instance_staging_dir


class CollectWorkfile(pyblish.api.InstancePlugin):
    """Collect current script for publish."""

    order = pyblish.api.CollectorOrder + 0.1
    label = "Collect Workfile"
    hosts = ["comfyui"]
    families = ["workfile"]

    default_variant = "Main"

    def process(self, instance):
        """DEBUG: Setting job env: AYON_PROJECT_NAME: testing
        DEBUG: Setting job env: AYON_FOLDER_PATH: /sh0010
        DEBUG: Setting job env: AYON_TASK_NAME: concept
        DEBUG: Setting job env: AYON_USERNAME: sas.vangulik
        DEBUG: Setting job env: AYON_HOST_NAME: comfyui
        DEBUG: Setting job env: AYON_BUNDLE_NAME: Submarine-2025-11-05-02_dev
        DEBUG: Setting job env: AYON_WORKDIR: C:\\Users\\Public\\Documents\\testing\\sh0010\\work\\concept
        """
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

        max_file = next(file for file in files if f"v{max_ver:03}" in file)

        ext = ".json"
        instance.data["anatomyData"] = instance.context.data["anatomyData"]
        instance.data["do_increment"] = True
        staging_dir = get_instance_staging_dir(instance)

        if not vers:
            max_file = f"{proj}_{folder}_{task}_v{max_ver:03}.json"
            host: ComfyUIHost = registered_host()
            host.save_workfile(dst_pth=os.path.join(staging_dir, max_file))
            instance.data["do_increment"] = False
        else:
            source = os.path.join(workdir, max_file)
            destination = os.path.join(staging_dir, max_file)
            shutil.copy2(source, destination)

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
