"""Download an instance's ComfyUI outputs and add its representations."""

from __future__ import annotations

import os
from typing import ClassVar

import pyblish.api
from ayon_core.pipeline.publish import KnownPublishError
from ayon_core.pipeline.publish.lib import get_instance_staging_dir

from ayon_comfyui.api import comfy_publish
from ayon_comfyui.api.publish_lib import (
    COMFYUI_KEY,
    OUTPUT_FAMILIES,
    get_comfy_http,
)

VIDEO_EXTENSIONS = {".mp4", ".webm"}
MODEL_EXTENSIONS = {
    ".gltf", ".glb", ".obj", ".fbx", ".stl", ".spz", ".splat", ".ply",
    ".ksplat", ".usdz",
}


class ExtractComfyUIOutputs(pyblish.api.InstancePlugin):
    """Download the outputs of the instance's ComfyUI run.

    The files are fetched through ComfyUI's `/view` API with URLs built
    from this session's ComfyUI URL, never from URLs given by the browser.

    - Images: one (sequence) representation for review, plus the first
      image as thumbnail.
    - Videos: the video for review, plus the save node's thumbnail.
    - Models: the model file(s).
    """

    order = pyblish.api.ExtractorOrder - 0.44
    label = "Collect ComfyUI Output Files"
    hosts: ClassVar[list[str]] = ["comfyui"]
    families: ClassVar[list[str]] = OUTPUT_FAMILIES

    def process(self, instance: pyblish.api.Instance) -> None:
        data = instance.data.get(COMFYUI_KEY) or {}
        files = data.get("outputs") or []
        main = [f for f in files if f.get("role", "main") == "main"]
        thumbnails = [f for f in files if f.get("role") == "thumbnail"]
        if not main:
            msg = (
                f"ComfyUI produced no files for "
                f"'{instance.data.get('productName')}'."
            )
            raise KnownPublishError(msg)

        staging_dir = get_instance_staging_dir(instance)
        self.log.info("Downloading %s file(s) to %s", len(files), staging_dir)
        http = get_comfy_http()
        try:
            names = comfy_publish.download_files(http, main, staging_dir)
            thumbnail_names = comfy_publish.download_files(
                http, thumbnails, staging_dir
            )
        except comfy_publish.PublishError as exc:
            raise KnownPublishError(str(exc)) from exc

        exts = {os.path.splitext(name)[1].lower() for name in names}
        if len(exts) != 1:
            msg = (
                "The outputs of an AYON save node must share one file type, "
                f"got: {', '.join(sorted(names))}"
            )
            raise KnownPublishError(msg)
        ext = exts.pop()
        product_type = instance.data.get("productType")
        self._check_extension(product_type, ext)
        if product_type != "image" and len(names) > 1:
            # Only image sequences are numbered frames; several videos or
            # models (a list input) don't make one representation.
            msg = (
                f"'{instance.data.get('productName')}' got {len(names)} "
                f"files ({', '.join(sorted(names))}), but a "
                f"{product_type} product publishes one. Feed its AYON save "
                "node a single input."
            )
            raise KnownPublishError(msg)

        representations = instance.data.setdefault("representations", [])
        representation = {
            "name": ext[1:],
            "ext": ext[1:],
            "files": names[0] if len(names) == 1 else names,
            "stagingDir": staging_dir,
        }
        if product_type in {"image", "render"}:
            representation["tags"] = ["review"]
        representations.append(representation)

        thumbnail = None
        if thumbnail_names:
            thumbnail = thumbnail_names[0]
        elif product_type == "image":
            thumbnail = names[0]
        if thumbnail:
            representations.append({
                "name": "thumbnail",
                "ext": os.path.splitext(thumbnail)[1][1:],
                "files": thumbnail,
                "stagingDir": staging_dir,
                "tags": ["thumbnail"],
            })

    @staticmethod
    def _check_extension(product_type: str | None, ext: str) -> None:
        allowed = {
            "render": VIDEO_EXTENSIONS,
            "model": MODEL_EXTENSIONS,
        }.get(product_type)
        if allowed is not None and ext not in allowed:
            msg = f"Unexpected '{ext}' output for a {product_type} product."
            raise KnownPublishError(msg)
