import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlretrieve

import pyblish.api
import pyblish.plugin
from ayon_comfyui.api.pipeline import ComfyUIHost
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish.lib import get_instance_staging_dir


class CollectImage(pyblish.api.InstancePlugin):
    """Collect  for publish."""

    order = pyblish.api.CollectorOrder + 0.15
    label = "Collect Generated Images"
    hosts = ["comfyui"]
    families = ["image"]

    default_variant = "Main"

    def process(self, instance: pyblish.plugin.Instance):
        # DEBUG: Setting job env: AYON_PROJECT_NAME: testing
        # DEBUG: Setting job env: AYON_FOLDER_PATH: /sh0010
        # DEBUG: Setting job env: AYON_TASK_NAME: concept
        # DEBUG: Setting job env: AYON_USERNAME: sas.vangulik
        # DEBUG: Setting job env: AYON_HOST_NAME: comfyui
        # DEBUG: Setting job env: AYON_BUNDLE_NAME: Submarine-2025-11-05-02_dev
        # DEBUG: Setting job env: AYON_WORKDIR: C:\\Users\\Public\\Documents\\testing\\sh0010\\work\\concept

        proj = os.environ.get("AYON_PROJECT_NAME")[:3]
        task = os.environ.get("AYON_TASK_NAME")
        folder = os.environ.get("AYON_FOLDER_PATH").split("/")[-1]
        workdir = os.environ.get("AYON_WORKDIR")
        self.log.debug(workdir)
        self.log.debug(instance)
        self.log.debug(instance.data)
        host: ComfyUIHost = registered_host()
        image_urls = host.stub.get_publish_node_images(instance.data)
        ext = ".png"
        instance.data["anatomyData"] = instance.context.data["anatomyData"]
        staging_dir = get_instance_staging_dir(instance)
        self.log.info(f"Outputting image to {staging_dir}")

        # http://127.0.0.1:8188/api/view?filename=Big_Slop_0001.png&subfolder=AYON/Big_Slop_imageMain&type=output

        files = []

        for image in image_urls:
            self.log.info(image)
            parse = urlsplit(image)
            self.log.info(parse)
            query = parse_qs(parse.query)
            self.log.info(query)
            filename = next(iter(query.get("filename")), None)
            if filename is None:
                continue
            self.log.info(filename)
            self.log.info(staging_dir)
            destination = os.path.join(
                staging_dir, instance.data.get("productName"), filename
            )
            files.append(
                os.path.join(instance.data.get("productName"), filename)
            )
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            urlretrieve(image, destination)  # noqa: S310

        instance.context.data["currentFile"] = files[0]

        # creating representation
        instance.data["representations"].append(
            {
                "name": ext[1:],
                "ext": ext[1:],
                "files": files,
                "stagingDir": staging_dir,
            }
        )
