"""Define collector for video."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlretrieve

import pyblish.api
import pyblish.plugin
from ayon_comfyui.api.rpc_stub import PublishType
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish.lib import get_instance_staging_dir

if TYPE_CHECKING:
    from ayon_comfyui.api.pipeline import ComfyUIHost


@dataclass
class VideoInfo:
    """Contains information about a video for publishing."""

    video_file: str | None = field(default=None)
    video_extension: str | None = field(default=None)
    thumbnail_file: str | None = field(default=None)
    thumbnail_extension: str | None = field(default=None)


def naive_reconstruct_querydict(qs_parsed: dict[str, list]) -> str:
    """Return reconstructed query string without leading '?'."""
    qs = []
    for key, values in qs_parsed.items():
        qs.extend([f"{key}={value}" for value in values])
    return "&".join(qs)


class CollectVideo(pyblish.api.InstancePlugin):
    """Collect video for publish."""

    order = pyblish.api.CollectorOrder + 0.16
    label = "Collect Generated Video + Thumbnail"
    hosts = ["comfyui"]
    families = ["render"]

    default_variant = "Main"

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
            instance.data, publish_type=PublishType.VIDEO
        )

        video_info = VideoInfo()

        video_exts = {".mp4", ".webm"}
        video_info.thumbnail_extension = ".png"

        # f"{filename}_{format}_thumb.png"

        instance.data["anatomyData"] = instance.context.data["anatomyData"]
        staging_dir = get_instance_staging_dir(instance)
        self.log.info("Outputting video to %s", staging_dir)

        video_link = next(iter(image_urls))
        if video_link is None:
            self.log.warning("Nothing could be collected. (No url returned.)")
            return

        # Download video
        self.log.info(video_link)
        parse = urlsplit(video_link)
        self.log.info(parse)
        query = parse_qs(parse.query)
        self.log.info(query)
        filename = next(iter(query.get("filename")), None)
        if filename is None:
            self.log.warning(
                "Nothing could be collected. (No filename in query.)"
            )
            return
        if (extension := Path(filename).suffix) not in video_exts:
            self.log.warning(
                "Nothing could be collected. "
                "(filename has invalid extension for video.)"
            )
            return
        video_info.video_extension = extension
        self.log.info(filename)
        self.log.info(staging_dir)
        destination = os.path.join(
            staging_dir, instance.data.get("productName"), filename
        )
        video_info.video_file = os.path.join(
            instance.data.get("productName"), filename
        )
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(video_link, destination)  # noqa: S310

        # retrieve thumbnail
        thumb_filename = f"{Path(filename).stem}_{extension[1:]}_thumb.png"
        query["filename"] = [thumb_filename]
        thumb_url = parse._replace(
            query=naive_reconstruct_querydict(query)
        ).geturl()
        self.log.info("Retrieving generated thumbnail")
        self.log.info(thumb_url)
        thumb_destination = os.path.join(
            staging_dir, instance.data.get("productName"), thumb_filename
        )
        urlretrieve(thumb_url, thumb_destination)  # noqa: S310
        video_info.thumbnail_file = os.path.join(
            instance.data.get("productName"), thumb_filename
        )

        instance.context.data["currentFile"] = video_info.video_file

        # creating representation
        instance.data["representations"].append(
            {
                "name": video_info.video_extension[1:],
                "ext": video_info.video_extension[1:],
                "files": video_info.video_file,
                "stagingDir": staging_dir,
            }
        )

        # Thumbnail
        thumbnail = {
            "name": "thumbnail",
            "ext": video_info.thumbnail_extension[1:],
            "files": video_info.thumbnail_file,
            "stagingDir": staging_dir,
            "tags": ["thumbnail"],
        }

        instance.data["representations"].append(thumbnail)
