"""AYON load nodes: read the files of a loaded AYON representation.

AYON writes a container into the node's `ayon_container_info` when it loads
or updates a representation. The node resolves the files from it while it
executes, with nothing to ask AYON:

- `path_reference.files`: AYON rootless paths (`{root[work]}/...`), read in
  place when this ComfyUI server has those roots configured (see
  `paths.py`). Opt-in on the AYON side.
- `image_upload_info`: copies AYON uploaded into ComfyUI's input directory,
  the default, which works wherever ComfyUI runs. Also the fallback when a
  path reference doesn't resolve here.

`fingerprint_inputs` is based on the resolved files' paths, sizes and
modification times, so a node runs again when AYON re-uploads or a file
changes in place (e.g. a hero version), and stays cached otherwise.
"""

from __future__ import annotations

import json
import logging
import os

import folder_paths
import node_helpers
import numpy as np
import torch
from comfy_api.latest import InputImpl, Types, io, ui
from PIL import Image, ImageOps, ImageSequence

from ..paths import resolve_rootless

log = logging.getLogger(__name__)

# Decoded through ComfyUI's own (PyAV) decoder, which keeps 16-bit and float
# precision; Pillow reads 16-bit PNGs as 8-bit and can't open EXR at all.
FULL_PRECISION_EXTENSIONS = {".png", ".exr", ".tif", ".tiff", ".dpx", ".hdr"}
# Uploaded files a browser can show as the node's preview as they are.
BROWSER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class ContainerError(ValueError):
    """The node's AYON container can't be resolved to files."""


def parse_container(ayon_container_info: str) -> dict:
    """Return the AYON container stored on a load node."""
    try:
        container = json.loads(ayon_container_info)
    except (TypeError, ValueError) as exc:
        msg = "The AYON load node has no valid container. Load it again."
        raise ContainerError(msg) from exc
    if not isinstance(container, dict):
        msg = "The AYON load node has no valid container. Load it again."
        raise ContainerError(msg)
    return container


def _input_file(upload_info: dict) -> str:
    input_dir = os.path.abspath(folder_paths.get_input_directory())
    relative = os.path.join(
        str(upload_info.get("subfolder") or ""), str(upload_info.get("name"))
    )
    path = os.path.abspath(os.path.join(input_dir, relative))
    try:
        common = os.path.commonpath([path, input_dir])
    except ValueError:
        common = ""
    if os.path.normcase(common) != os.path.normcase(input_dir):
        msg = f"Refusing to read outside ComfyUI's input directory: {relative}"
        raise ContainerError(msg)
    return path


def uploaded_files(container: dict) -> list[str]:
    """Return the paths of the container's uploaded copies."""
    upload_infos = container.get("image_upload_info") or []
    if isinstance(upload_infos, dict):
        upload_infos = [upload_infos]
    return [
        _input_file(info)
        for info in upload_infos
        if isinstance(info, dict) and info.get("name")
    ]


def referenced_files(container: dict) -> list[str] | None:
    """Return the container's path references resolved on this server.

    Returns None when the container has none, or when not all of them
    resolve to existing files here.
    """
    reference = container.get("path_reference")
    if not isinstance(reference, dict):
        return None
    rootless = reference.get("files")
    if not isinstance(rootless, list) or not rootless:
        return None
    paths = [resolve_rootless(path) for path in rootless]
    if all(path and os.path.isfile(path) for path in paths):
        return paths
    return None


def container_files(container: dict) -> list[str]:
    """Return the files to read for a container.

    Raises:
        ContainerError: When there are none, or some don't exist.
    """
    paths = referenced_files(container)
    if paths is None:
        paths = uploaded_files(container)
        if not paths and container.get("path_reference"):
            msg = (
                "The files of this AYON load node are referenced by path, "
                "but this ComfyUI server can't reach them (check its AYON "
                "roots configuration), and there is no uploaded copy. Load "
                "the product again without path reference."
            )
            raise ContainerError(msg)
    if not paths:
        msg = "The AYON load node's container has no files. Load it again."
        raise ContainerError(msg)
    missing = [path for path in paths if not os.path.isfile(path)]
    if missing:
        msg = (
            f"{len(missing)} file(s) of this AYON load node are missing, "
            f"e.g. {missing[0]}. Load the product again."
        )
        raise ContainerError(msg)
    return paths


def files_fingerprint(container: dict, paths: list[str]) -> str:
    """Return what changes when the loaded files change."""
    parts = [str(container.get("representation", ""))]
    for path in paths:
        stat = os.stat(path)
        parts.append(f"{path}|{stat.st_size}|{stat.st_mtime_ns}")
    return "\n".join(parts)


def fingerprint(ayon_container_info: str) -> str:
    """`fingerprint_inputs` of the load nodes."""
    try:
        container = parse_container(ayon_container_info)
        return files_fingerprint(container, container_files(container))
    except (ContainerError, OSError):
        # Validation reports the problem; keep the cache key stable.
        return ayon_container_info


def validate(ayon_container_info: str) -> bool | str:
    """`validate_inputs` of the load nodes."""
    try:
        container_files(parse_container(ayon_container_info))
    except ContainerError as exc:
        return str(exc)
    return True


# --- decoding -----------------------------------------------------------

# One decoded frame: image (H, W, 3) and alpha (H, W) or None.
Frame = tuple[torch.Tensor, "torch.Tensor | None"]


def _decode_full_precision(path: str) -> list[Frame]:
    components = InputImpl.VideoFromFile(path).get_components()
    images = components.images.to(device="cpu", dtype=torch.float32)
    alpha = components.alpha
    if alpha is not None:
        alpha = alpha.to(device="cpu", dtype=torch.float32)
    return [
        (images[i], None if alpha is None else alpha[i, ..., 0])
        for i in range(images.shape[0])
    ]


def _decode_pillow(path: str) -> list[Frame]:
    """Mimic ComfyUI's LoadImage (8-bit, EXIF orientation, MPO)."""
    frames = []
    img = node_helpers.pillow(Image.open, path)
    for frame in ImageSequence.Iterator(img):
        frame = node_helpers.pillow(ImageOps.exif_transpose, frame)
        if frame.mode == "I":
            frame = frame.point(lambda value: value * (1 / 255))
        rgb = np.array(frame.convert("RGB")).astype(np.float32) / 255.0
        alpha = None
        if "A" in frame.getbands():
            alpha = np.array(frame.getchannel("A")).astype(np.float32) / 255.0
        elif frame.mode == "P" and "transparency" in frame.info:
            alpha = np.array(
                frame.convert("RGBA").getchannel("A")
            ).astype(np.float32) / 255.0
        frames.append((
            torch.from_numpy(rgb),
            None if alpha is None else torch.from_numpy(alpha),
        ))
        if img.format == "MPO":
            # Only the first image of an MPO is the picture.
            break
    return frames


def decode_image(path: str) -> list[Frame]:
    """Return (image HxWx3, alpha HxW or None) for each frame in `path`."""
    if os.path.splitext(path)[1].lower() in FULL_PRECISION_EXTENSIONS:
        try:
            return _decode_full_precision(path)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "AYON: ComfyUI's decoder couldn't read %s (%s), reading it "
                "with Pillow at 8-bit instead.", path, exc,
            )
    return _decode_pillow(path)


def load_images(paths: list[str]) -> tuple[torch.Tensor, torch.Tensor]:
    """Return an IMAGE batch and its MASK (1 - alpha) for `paths`."""
    images = []
    masks = []
    size = None
    for path in paths:
        for image, alpha in decode_image(path):
            height, width = image.shape[0], image.shape[1]
            if size is None:
                size = (width, height)
            elif (width, height) != size:
                log.warning(
                    "AYON: Skipping a frame of %s: it is %sx%s, the batch "
                    "is %sx%s.", path, width, height, *size,
                )
                continue
            images.append(image)
            if alpha is None:
                masks.append(torch.zeros((height, width), dtype=torch.float32))
            else:
                masks.append(1.0 - alpha)
    if not images:
        msg = "The AYON load node found no images to load."
        raise ContainerError(msg)
    return torch.stack(images), torch.stack(masks)


def preview(
    cls: type[io.ComfyNode],
    container: dict,
    paths: list[str],
    images: torch.Tensor,
) -> dict:
    """Return the node's preview UI output.

    Uploaded files a browser can show are previewed as they are; otherwise
    (EXR, 16-bit, files referenced by path) the first frame is written as a
    temporary preview.
    """
    uploads = container.get("image_upload_info") or []
    if isinstance(uploads, dict):
        uploads = [uploads]
    exts = {os.path.splitext(path)[1].lower() for path in paths}
    if (
        paths == uploaded_files(container)
        and exts <= BROWSER_IMAGE_EXTENSIONS
    ):
        return ui.SavedImages([
            ui.SavedResult(
                info["name"], info.get("subfolder", ""), io.FolderType.input
            )
            for info in uploads
        ]).as_dict()
    return ui.PreviewImage(images[:1].clamp(0, 1), cls=cls).as_dict()


class AyonLoadImageNode(io.ComfyNode):
    """Container node loading a specified image."""

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.String.Input("ayon_container_info", "AYON context"),
        ]

    @staticmethod
    def define_outputs() -> list[io.Output]:
        return [
            io.Image.Output("image"),
            io.Mask.Output("mask"),
        ]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="AYON Load Image",
            display_name="AYON Load Image",
            category="AYON",
            inputs=AyonLoadImageNode.define_inputs(),
            outputs=AyonLoadImageNode.define_outputs(),
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, ayon_container_info: str):
        return fingerprint(ayon_container_info)

    @classmethod
    def validate_inputs(cls, ayon_container_info: str):
        return validate(ayon_container_info)

    @classmethod
    def execute(cls, ayon_container_info: str):
        """Load the container's images at full precision."""
        container = parse_container(ayon_container_info)
        paths = container_files(container)
        images, masks = load_images(paths)
        return io.NodeOutput(
            images, masks, ui=preview(cls, container, paths, images)
        )


class AyonLoadVideoNode(io.ComfyNode):
    """Container node loading a specified video."""

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.String.Input("ayon_container_info", "AYON context"),
        ]

    @staticmethod
    def define_outputs() -> list[io.Output]:
        return [
            io.Video.Output("Video"),
        ]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="AYON Load Video",
            display_name="AYON Load Video",
            category="AYON",
            inputs=AyonLoadVideoNode.define_inputs(),
            outputs=AyonLoadVideoNode.define_outputs(),
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, ayon_container_info: str):
        return fingerprint(ayon_container_info)

    @classmethod
    def validate_inputs(cls, ayon_container_info: str):
        return validate(ayon_container_info)

    @classmethod
    def execute(cls, ayon_container_info: str):
        """Load the container's video."""
        container = parse_container(ayon_container_info)
        path = container_files(container)[0]
        video = InputImpl.VideoFromFile(path)

        uploads = container.get("image_upload_info") or []
        if isinstance(uploads, dict):
            uploads = [uploads]
        if uploads and path == uploaded_files(container)[0]:
            result = ui.SavedResult(
                uploads[0]["name"],
                uploads[0].get("subfolder", ""),
                io.FolderType.input,
            )
            return io.NodeOutput(video, ui=ui.PreviewVideo([result]))
        # Referenced by path: the browser can't fetch it, so no preview.
        return io.NodeOutput(video)


class AyonLoad3DModelNode(io.ComfyNode):
    """Container node loading a specified 3D model."""

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.String.Input("ayon_container_info", "AYON context"),
        ]

    @staticmethod
    def define_outputs() -> list[io.Output]:
        return [
            io.File3DAny.Output("model", display_name="model"),
        ]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="AYON Load 3D Model",
            display_name="AYON Load 3D Model",
            category="AYON",
            inputs=AyonLoad3DModelNode.define_inputs(),
            outputs=AyonLoad3DModelNode.define_outputs(),
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, ayon_container_info: str, **kwargs):
        return fingerprint(ayon_container_info)

    @classmethod
    def validate_inputs(cls, ayon_container_info: str, **kwargs):
        return validate(ayon_container_info)

    @classmethod
    def execute(cls, ayon_container_info: str, **kwargs) -> io.NodeOutput:
        """Load the container's model file.

        Supports: .gltf, .glb, .obj, .fbx, .stl, .spz, .splat, .ply,
        .ksplat
        """
        container = parse_container(ayon_container_info)
        model_file = container_files(container)[0]
        ext = os.path.splitext(model_file)[1].lstrip(".").lower()
        return io.NodeOutput(Types.File3D(model_file, ext))
