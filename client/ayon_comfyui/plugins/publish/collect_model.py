"""Define collector for video."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlretrieve

import pyblish.api
import pyblish.plugin
from ayon_comfyui.api.rpc_stub import PublishType
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish.lib import get_instance_staging_dir

if TYPE_CHECKING:
    from ayon_comfyui.api.pipeline import ComfyUIHost


class CollectModel(pyblish.api.InstancePlugin):
    """Collect 3D Model for publish.

    TODO(@sas): Only supports exports for singular models,
    expand so that sequences of objs/glbs can be properly taken in.
    """

    order = pyblish.api.CollectorOrder + 0.17
    label = "Collect Generated Model"
    hosts: ClassVar[list[str]] = ["comfyui"]
    families: ClassVar[list[str]] = ["model"]

    default_variant = "Main"

    model_exts: ClassVar[list[str]] = [
        ".gltf",
        ".glb",
        ".obj",
        ".fbx",
        ".stl",
        ".spz",
        ".splat",
        ".ply",
        ".ksplat",
    ]

    def process(self, instance: pyblish.plugin.Instance):
        proj = os.environ.get("AYON_PROJECT_NAME")[:3]
        task = os.environ.get("AYON_TASK_NAME")
        folder = os.environ.get("AYON_FOLDER_PATH").split("/")[-1]
        workdir = os.environ.get("AYON_WORKDIR")
        self.log.debug(workdir)
        self.log.debug(instance)
        self.log.debug(instance.data)
        host: ComfyUIHost = registered_host()
        image_urls = host.stub.get_publish_node_images(
            instance.data, publish_type=PublishType.MODEL3D
        )

        instance.data["anatomyData"] = instance.context.data["anatomyData"]
        staging_dir = get_instance_staging_dir(instance)
        self.log.info(f"Outputting model to {staging_dir}")

        model_link = next(iter(image_urls))
        if model_link is None:
            self.log.warning("Nothing could be collected. (No url returned.)")
            return

        # Download model
        self.log.info(model_link)
        parse = urlsplit(model_link)
        self.log.info(parse)
        query = parse_qs(parse.query)
        self.log.info(query)
        filename = next(iter(query.get("filename")), None)
        if filename is None:
            self.log.warning(
                "Nothing could be collected. (No filename in query.)"
            )
            return
        if (extension := Path(filename).suffix) not in self.model_exts:
            self.log.warning(
                "Nothing could be collected. "
                "(filename has invalid extension for video.)"
            )
            return
        self.log.info(filename)
        self.log.info(staging_dir)
        destination = os.path.join(
            staging_dir, instance.data.get("productName"), filename
        )
        model_file = os.path.join(instance.data.get("productName"), filename)
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(model_link, destination)  # noqa: S310

        instance.context.data["currentFile"] = model_file

        # creating representation
        instance.data["representations"].append(
            {
                "name": extension[1:],
                "ext": extension[1:],
                "files": model_file,
                "stagingDir": staging_dir,
            }
        )
        # no thumbnail here...
