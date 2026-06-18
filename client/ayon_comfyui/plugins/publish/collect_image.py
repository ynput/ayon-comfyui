import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlretrieve

import pyblish.api
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

    def process(self, instance: pyblish.api.Instance):
        host: ComfyUIHost = registered_host()
        image_urls = host.stub.get_publish_node_images(instance.data)
        ext = ".png"
        instance.data["anatomyData"] = instance.context.data["anatomyData"]
        staging_dir = os.path.join(
            get_instance_staging_dir(instance),
            instance.data.get("productName"),
        )
        self.log.info("Outputting image to %s", staging_dir)

        files = []

        for image in image_urls:
            self.log.debug("Downloading image: %s", image)
            parse = urlsplit(image)
            self.log.debug(parse)
            query = parse_qs(parse.query)
            self.log.debug(query)
            filename = next(iter(query.get("filename")), None)
            if filename is None:
                continue
            self.log.debug("Got filename: %s", filename)
            destination = os.path.join(staging_dir, filename)
            files.append(filename)
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            urlretrieve(image, destination)  # noqa: S310

        instance.context.data["currentFile"] = files[0]

        if len(files) == 1:
            files = files[0]

        # marking instance as reviewable
        instance.data["review"] = True
        instance.data["families"].append("review")

        # creating representation
        instance.data["representations"].append(
            {
                "name": ext[1:],
                "ext": ext[1:],
                "files": files,
                "stagingDir": staging_dir,
                "tags": ["review"],
            }
        )

        # NOTE(@sas): Maybe generate a tiled image for batched images

        thumbnail_img = files
        if isinstance(thumbnail_img, list):
            thumbnail_img = thumbnail_img[0]

        # Thumbnail
        thumbnail = {
            "name": "thumbnail",
            "ext": ext[1:],
            "files": thumbnail_img,
            "stagingDir": staging_dir,
            "tags": ["thumbnail"],
        }

        instance.data["representations"].append(thumbnail)
