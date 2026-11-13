"""AYON save nodes: write the outputs of a publish instance.

Each node writes into its own staging folder inside ComfyUI's output
directory, `AYON/<instance id>/<prompt id>/`, so runs of different instances,
prompts or artists never overwrite each other. Nothing here talks to AYON:
the AYON host queues the prompt, waits for it in ComfyUI's history and reads
the files from the node's `ayon` UI output (see `ayon_output_entry`).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import struct
import time
import uuid
from fractions import Fraction
from secrets import token_hex

import av
import av.audio.resampler
import folder_paths
import numpy as np
import torch
from comfy_api.latest import AudioInput, ImageInput, Types, io, ui
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from torch import Tensor

try:
    from comfy_execution.utils import get_executing_context
except ImportError:  # ComfyUI before the execution context existed
    get_executing_context = None

log = logging.getLogger(__name__)

# Folder in ComfyUI's output directory that holds all AYON outputs.
AYON_OUTPUT_ROOT = "AYON"
# Every run of a save node writes a new folder; keep this many per instance
# (the newest), so publishing an earlier run still finds its files without
# the output directory growing forever.
KEEP_RUNS_PER_INSTANCE = 5
# ...and never delete runs younger than this (seconds), since copies of a
# workfile (other artists, on a shared ComfyUI) write to the same folder.
KEEP_RUNS_MIN_AGE = 24 * 60 * 60

_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]")
_MAX_ID_LENGTH = 64


def parse_ayon_info(ayon_info: str) -> dict:
    """Return the publish instance stored on an AYON save node."""
    try:
        data = json.loads(ayon_info)
    except (TypeError, ValueError) as exc:
        msg = (
            "The AYON save node has no valid publish instance data. Recreate "
            "it with the AYON Creator."
        )
        raise ValueError(msg) from exc
    if not isinstance(data, dict) or not isinstance(
        data.get("creator_attributes"), dict
    ):
        msg = (
            "The AYON save node's publish instance data is incomplete. "
            "Recreate it with the AYON Creator."
        )
        raise ValueError(msg)
    return data


def _safe_id(value: object) -> str:
    return _UNSAFE_ID_CHARS.sub("", str(value or ""))[:_MAX_ID_LENGTH]


def safe_file_stem(value: object, fallback: str = "ayon") -> str:
    """Return `value` usable as (the start of) a file name."""
    stem = _UNSAFE_NAME_CHARS.sub("", str(value or "")).lstrip(".")
    return stem[:_MAX_ID_LENGTH] or fallback


def current_prompt_id() -> str | None:
    """Return the id of the prompt being executed, if ComfyUI tells us."""
    if get_executing_context is None:
        return None
    context = get_executing_context()
    if context is None:
        return None
    return _safe_id(context.prompt_id) or None


def staging_folder(ayon_json: dict) -> tuple[str, str, str, str]:
    """Return the staging folder of a publish instance for this prompt.

    Returns:
        Tuple of the absolute folder, its subfolder relative to the output
        directory (with forward slashes), the instance id and the prompt id.
    """
    instance_id = str(ayon_json.get("instance_id") or "")
    try:
        valid = str(uuid.UUID(instance_id)) == instance_id
    except ValueError:
        valid = False
    if not valid:
        msg = (
            "The AYON save node's publish instance has no valid instance id. "
            "Recreate it with the AYON Creator."
        )
        raise ValueError(msg)
    prompt_id = current_prompt_id() or f"run-{token_hex(8)}"

    output_dir = os.path.abspath(folder_paths.get_output_directory())
    subfolder = f"{AYON_OUTPUT_ROOT}/{instance_id}/{prompt_id}"
    folder = os.path.abspath(os.path.join(output_dir, subfolder))
    if os.path.commonpath([folder, output_dir]) != output_dir:
        msg = f"Refusing to write outside the output directory: {folder}"
        raise ValueError(msg)
    os.makedirs(folder, exist_ok=True)
    prune_old_runs(os.path.dirname(folder), keep=folder)
    return folder, subfolder, instance_id, prompt_id


def prune_old_runs(instance_folder: str, keep: str) -> None:
    """Delete an instance's run folders beyond the newest, once old."""
    try:
        runs = [
            entry for entry in os.scandir(instance_folder)
            if entry.is_dir(follow_symlinks=False) and entry.path != keep
        ]
        runs.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
        cutoff = time.time() - KEEP_RUNS_MIN_AGE
    except OSError:
        return
    for entry in runs[KEEP_RUNS_PER_INSTANCE - 1:]:
        try:
            if entry.stat().st_mtime > cutoff:
                # Recent: e.g. another artist working on a copy of this
                # workfile may be about to publish it.
                continue
        except OSError:
            continue
        shutil.rmtree(entry.path, ignore_errors=True)
        log.debug("AYON: Removed old outputs %s", entry.path)


def file_stem(ayon_json: dict) -> str:
    """Return the file name stem chosen in the creator attributes.

    The prefix and unique name are both optional (PR #40); without either,
    the product name is used.
    """
    creator_attrs = ayon_json["creator_attributes"]
    parts = [safe_file_stem(creator_attrs.get("prefix"), "")]
    if creator_attrs.get("use_unique_name", True):
        parts.append(safe_file_stem(creator_attrs.get("unique_name"), ""))
    stem = "_".join(part for part in parts if part)
    return stem or safe_file_stem(ayon_json.get("productName"))


def unique_filename(folder: str, filename: str) -> str:
    """Return `filename`, or a numbered variant that doesn't exist yet.

    A node runs more than once per prompt when its input is a list, and all
    runs write into the same staging folder.
    """
    if not os.path.exists(os.path.join(folder, filename)):
        return filename
    stem, ext = os.path.splitext(filename)
    index = 2
    while os.path.exists(os.path.join(folder, f"{stem}_{index}{ext}")):
        index += 1
    return f"{stem}_{index}{ext}"


def output_file(filename: str, subfolder: str, role: str = "main") -> dict:
    """Describe one file a save node wrote, for the AYON host."""
    return {
        "filename": filename,
        "subfolder": subfolder,
        "type": "output",
        "role": role,
    }


def ayon_output_entry(
    instance_id: str, prompt_id: str, files: list[dict]
) -> dict:
    """Return the `ayon` UI output entry the AYON host collects.

    The files are nested inside the entry, so ComfyUI doesn't treat them as
    extra previews.
    """
    return {
        "instance_id": instance_id,
        "prompt_id": prompt_id,
        "files": files,
    }


class AyonSaveNode(io.ComfyNode):
    """A node that allows the user to Batch Save images with metadata."""

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.Image.Input("images_in", "Input Image"),
            io.Boolean.Input("recook", "Recook on publish", default=False),
            io.String.Input("ayon_info", "info"),
        ]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="AYON Image Save",
            display_name="AYON Image Save",
            category="AYON",
            inputs=AyonSaveNode.define_inputs(),
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
            is_output_node=True,
        )

    # Ensure unique publish
    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return token_hex(16)

    @classmethod
    def execute(
        cls,
        images_in: Tensor | list[Tensor],
        recook: bool,  # Not used in code.
        ayon_info: str,
    ) -> io.NodeOutput:
        """Save the images as a numbered PNG sequence."""
        ayon_json = parse_ayon_info(ayon_info)
        creator_attrs = ayon_json["creator_attributes"]

        keep_metadata = bool(creator_attrs.get("keep_metadata", True))
        compress_level = int(creator_attrs.get("compression_level", 4))
        stem = file_stem(ayon_json)

        folder, subfolder, instance_id, prompt_id = staging_folder(ayon_json)

        metadata = None
        if keep_metadata:
            metadata = PngInfo()
            if cls.hidden.prompt is not None:
                metadata.add_text("prompt", json.dumps(cls.hidden.prompt))
            if (extra_pnginfo := cls.hidden.extra_pnginfo) is not None:
                for key, value in extra_pnginfo.items():
                    metadata.add_text(key, json.dumps(value))

        # A node with a list input runs once per item, all writing into the
        # same folder, so continue the frame numbers of earlier runs.
        prefix = f"{stem}_"
        frame = 1 + sum(
            1
            for name in os.listdir(folder)
            if name.startswith(prefix) and name.endswith(".png")
        )

        previews = []
        files = []
        for image in images_in:
            image_data = 255.0 * image.cpu().numpy()
            img_pil = Image.fromarray(
                np.clip(image_data, 0, 255).astype(np.uint8)
            )
            filename = unique_filename(folder, f"{prefix}{frame:04}.png")
            frame += 1
            img_pil.save(
                os.path.join(folder, filename),
                pnginfo=metadata,
                compress_level=compress_level,
            )
            previews.append(
                ui.SavedResult(filename, subfolder, io.FolderType.output)
            )
            files.append(output_file(filename, subfolder))

        return io.NodeOutput(ui={
            "images": previews,
            "ayon": [ayon_output_entry(instance_id, prompt_id, files)],
        })


class AyonSaveVideoNode(io.ComfyNode):
    """A node that allows the user to save mp4/webm Videos with metadata."""

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.Video.Input("video_in", "Input Video"),
            io.Boolean.Input("recook", "Recook on publish", default=False),
            io.String.Input("ayon_info", "info"),
        ]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="AYON Video Save",
            display_name="AYON Video Save",
            category="AYON",
            inputs=AyonSaveVideoNode.define_inputs(),
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
            is_output_node=True,
        )

    # Ensure unique publish
    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return token_hex(16)

    @classmethod
    def execute(cls, video_in: io.Video.Type, recook: bool, ayon_info: str):
        """Save the video plus a PNG thumbnail of its first frame."""
        ayon_json = parse_ayon_info(ayon_info)
        creator_attrs = ayon_json["creator_attributes"]

        keep_metadata = bool(creator_attrs.get("keep_metadata", True))
        stem = file_stem(ayon_json)

        # mp4/h264 | webm/vp9 | webm/av1
        formatcodec: str = creator_attrs.get("formatcodec", "mp4/h264")
        webm_no_audio = bool(creator_attrs.get("webm_noaudio", False))
        # 0- > 63 (32 middleground), higher better quality
        webm_crf = float(creator_attrs.get("webm_crf", 32))

        container_format, codec = (
            x.strip() for x in formatcodec.split("/", 1)
        )
        if container_format not in {"mp4", "webm"}:
            msg = f"Unsupported AYON video format: {formatcodec}"
            raise ValueError(msg)

        components = video_in.get_components()
        images, audio, fps = (
            components.images,
            components.audio,
            components.frame_rate,
        )

        folder, subfolder, instance_id, prompt_id = staging_folder(ayon_json)

        # Keep the source video's own metadata, and add the prompt and
        # workflow like ComfyUI's own save nodes when asked to.
        saved_metadata = dict(components.metadata or {})
        if keep_metadata:
            if cls.hidden.extra_pnginfo is not None:
                saved_metadata.update(cls.hidden.extra_pnginfo)
            if cls.hidden.prompt is not None:
                saved_metadata["prompt"] = cls.hidden.prompt

        filename = unique_filename(folder, f"{stem}.{container_format}")
        video_stem = os.path.splitext(filename)[0]
        thumbnail = unique_filename(
            folder, f"{video_stem}_{container_format}_thumb.png"
        )

        thumb_image_data = 255.0 * images[0].cpu().numpy()
        Image.fromarray(
            np.clip(thumb_image_data, 0, 255).astype(np.uint8)
        ).save(os.path.join(folder, thumbnail), compress_level=4)

        if container_format == "mp4":
            video_in.save_to(
                os.path.join(folder, filename),
                format=Types.VideoContainer.MP4,
                codec=Types.VideoCodec.H264,
                metadata=saved_metadata,
            )
        else:
            cls.save_webm(
                os.path.join(folder, filename),
                codec,
                webm_crf,
                fps,
                images,
                None if webm_no_audio else audio,
                saved_metadata if keep_metadata else None,
            )

        files = [
            output_file(filename, subfolder),
            output_file(thumbnail, subfolder, role="thumbnail"),
        ]
        preview = ui.SavedResult(filename, subfolder, io.FolderType.output)
        return io.NodeOutput(ui={
            **ui.PreviewVideo([preview]).as_dict(),
            "ayon": [ayon_output_entry(instance_id, prompt_id, files)],
        })

    @classmethod
    def save_webm(  # noqa: PLR0913, PLR0917
        cls,
        filepath: str,
        codec: str,
        crf: float,
        fps: float,
        images: ImageInput,
        audio_input: AudioInput | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Encode `images` (and audio) as a WebM file at `filepath`."""
        container = av.open(filepath, mode="w")

        for key, value in (metadata or {}).items():
            container.metadata[key] = (
                value if isinstance(value, str) else json.dumps(value)
            )

        # Video
        codec_map = {"vp9": "libvpx-vp9", "av1": "libsvtav1"}

        stream = container.add_stream(
            codec_map[codec],
            rate=Fraction(round(fps * 1000), 1000),
        )

        stream.width = images.shape[-2]
        stream.height = images.shape[-3]
        stream.pix_fmt = "yuv420p10le" if codec == "av1" else "yuv420p"
        stream.bit_rate = 0
        stream.options = {"crf": str(crf)}

        if codec == "av1":
            stream.options["preset"] = "6"

        # Audio
        audio_stream = None

        if audio_input:
            audio_ts: torch.Tensor = audio_input.get("waveform")  # [B, C, T]
            input_sample_rate: int = audio_input.get("sample_rate")

            if audio_ts is not None:
                audio = audio_ts.detach().cpu().numpy()

                if audio.ndim != 3:
                    raise ValueError(f"Expected [B, C, T], got {audio.shape}")

                B, C, T = audio.shape

                if B > 1:
                    # flatten batches into time
                    audio = audio.reshape(B * T, C).T  # (C, T)
                else:
                    audio = audio[0]  # (C, T)

                # Ensure float32 + contiguous
                audio = np.ascontiguousarray(audio.astype(np.float32))

                layout = "stereo" if C == 2 else "mono"
                target_sample_rate = 48000

                # Create audio stream
                audio_stream = container.add_stream(
                    "libopus", rate=target_sample_rate
                )
                audio_stream.layout = layout

                # Resample (planar)
                resampler = av.audio.resampler.AudioResampler(
                    format="fltp",  # planar
                    layout=layout,
                    rate=target_sample_rate,
                )

                input_frame = av.AudioFrame.from_ndarray(
                    audio,
                    format="fltp",  # planar expects (C, T)
                    layout=layout,
                )
                input_frame.sample_rate = input_sample_rate

                resampled_frames = resampler.resample(input_frame)

        # Encode video
        for img in images:
            frame = av.VideoFrame.from_ndarray(
                torch.clamp(img[..., :3] * 255, 0, 255)
                .to(device=torch.device("cpu"), dtype=torch.uint8)
                .numpy(),
                format="rgb24",
            )

            for packet in stream.encode(frame):
                container.mux(packet)

        # Flush video
        for packet in stream.encode():
            container.mux(packet)

        # Encode audio
        if audio_stream is not None:
            for frame in resampled_frames:
                for packet in audio_stream.encode(frame):
                    container.mux(packet)

            # Flush audio
            for packet in audio_stream.encode(None):
                container.mux(packet)

        container.close()


class AyonSave3DModelNode(io.ComfyNode):
    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.MultiType.Input(
                io.Mesh.Input("mesh", "Mesh/File"),
                types=[
                    io.File3DAny,
                    io.File3DFBX,
                    io.File3DGLB,
                    io.File3DGLTF,
                    io.File3DGLTF,
                    io.File3DOBJ,
                    io.File3DSTL,
                    io.File3DSTL,
                    io.File3DUSDZ,
                    io.Mesh,
                ],
            ),
            io.Boolean.Input("recook", "Recook on publish", default=False),
            io.String.Input("ayon_info", "info"),
        ]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="AYON 3D Model Save",
            display_name="AYON 3D Model Save",
            category="AYON",
            inputs=AyonSave3DModelNode.define_inputs(),
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
            is_output_node=True,
        )

    # Ensure unique publish
    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        return token_hex(16)

    @classmethod
    def execute(
        cls, mesh: Types.MESH | Types.File3D, recook: bool, ayon_info: str
    ) -> io.NodeOutput:
        """Save the model as-is, or a mesh as GLB/OBJ."""
        ayon_json = parse_ayon_info(ayon_info)
        creator_attrs = ayon_json["creator_attributes"]

        keep_metadata = bool(creator_attrs.get("keep_metadata", True))
        fallback_format = creator_attrs.get("fallback_format", "obj")
        if fallback_format not in {"glb", "obj"}:
            fallback_format = "obj"

        if isinstance(mesh, Types.File3D):
            model_format = safe_file_stem(mesh.format, "glb").lower()
        else:
            model_format = fallback_format
        stem = f"{file_stem(ayon_json)}_{model_format}"

        folder, subfolder, instance_id, prompt_id = staging_folder(ayon_json)

        metadata = {}
        if keep_metadata:
            if cls.hidden.prompt is not None:
                metadata["prompt"] = json.dumps(cls.hidden.prompt)
            if cls.hidden.extra_pnginfo is not None:
                for key, value in cls.hidden.extra_pnginfo.items():
                    metadata[key] = json.dumps(value)

        results = []
        if isinstance(mesh, Types.File3D):
            filename = unique_filename(folder, f"{stem}.{model_format}")
            mesh.save_to(os.path.join(folder, filename))
            results.append(filename)
        else:
            for idx in range(mesh.vertices.shape[0]):
                filename = unique_filename(
                    folder, f"{stem}_{idx + 1:04}.{fallback_format}"
                )
                filepath = os.path.join(folder, filename)
                if fallback_format == "glb":
                    cls.save_glb(
                        mesh.vertices[idx], mesh.faces[idx], filepath, metadata
                    )
                else:
                    cls.save_obj(mesh.vertices[idx], mesh.faces[idx], filepath)
                results.append(filename)

        previews = [
            {"filename": name, "subfolder": subfolder, "type": "output"}
            for name in results
        ]
        files = [output_file(name, subfolder) for name in results]
        # ComfyUI shows `3d` outputs in its 3D viewer.
        return io.NodeOutput(ui={
            "3d": previews,
            "ayon": [ayon_output_entry(instance_id, prompt_id, files)],
        })

    @classmethod
    def save_glb(cls, vertices, faces, filepath, metadata=None):  # noqa: ANN001, ANN206
        """
        Borrowed from ComfyUI/comfy_extras/nodes_hunyuan3d.py

        Save PyTorch tensor vertices and faces as a GLB file without external
        dependencies.

        Parameters:
        vertices: torch.Tensor of shape (N, 3) - The vertex coordinates
        faces: torch.Tensor of shape (M, 3) - The face indices (triangle faces)
        filepath: str - Output filepath (should end with .glb)
        """

        # Convert tensors to numpy arrays
        vertices_np = vertices.cpu().numpy().astype(np.float32)
        faces_np = faces.cpu().numpy().astype(np.uint32)

        vertices_buffer = vertices_np.tobytes()
        indices_buffer = faces_np.tobytes()

        def pad_to_4_bytes(buffer):
            padding_length = (4 - (len(buffer) % 4)) % 4
            return buffer + b"\x00" * padding_length

        vertices_buffer_padded = pad_to_4_bytes(vertices_buffer)
        indices_buffer_padded = pad_to_4_bytes(indices_buffer)

        buffer_data = vertices_buffer_padded + indices_buffer_padded

        vertices_byte_length = len(vertices_buffer)
        vertices_byte_offset = 0
        indices_byte_length = len(indices_buffer)
        indices_byte_offset = len(vertices_buffer_padded)

        gltf = {
            "asset": {"version": "2.0", "generator": "ComfyUI"},
            "buffers": [{"byteLength": len(buffer_data)}],
            "bufferViews": [
                {
                    "buffer": 0,
                    "byteOffset": vertices_byte_offset,
                    "byteLength": vertices_byte_length,
                    "target": 34962,  # ARRAY_BUFFER
                },
                {
                    "buffer": 0,
                    "byteOffset": indices_byte_offset,
                    "byteLength": indices_byte_length,
                    "target": 34963,  # ELEMENT_ARRAY_BUFFER
                },
            ],
            "accessors": [
                {
                    "bufferView": 0,
                    "byteOffset": 0,
                    "componentType": 5126,  # FLOAT
                    "count": len(vertices_np),
                    "type": "VEC3",
                    "max": vertices_np.max(axis=0).tolist(),
                    "min": vertices_np.min(axis=0).tolist(),
                },
                {
                    "bufferView": 1,
                    "byteOffset": 0,
                    "componentType": 5125,  # UNSIGNED_INT
                    "count": faces_np.size,
                    "type": "SCALAR",
                },
            ],
            "meshes": [
                {
                    "primitives": [
                        {
                            "attributes": {"POSITION": 0},
                            "indices": 1,
                            "mode": 4,  # TRIANGLES
                        }
                    ]
                }
            ],
            "nodes": [{"mesh": 0}],
            "scenes": [{"nodes": [0]}],
            "scene": 0,
        }

        if metadata is not None:
            gltf["asset"]["extras"] = metadata

        # Convert the JSON to bytes
        gltf_json = json.dumps(gltf).encode("utf8")

        def pad_json_to_4_bytes(buffer):
            padding_length = (4 - (len(buffer) % 4)) % 4
            return buffer + b" " * padding_length

        gltf_json_padded = pad_json_to_4_bytes(gltf_json)

        # Create the GLB header
        # Magic glTF
        glb_header = struct.pack(
            "<4sII",
            b"glTF",
            2,
            12 + 8 + len(gltf_json_padded) + 8 + len(buffer_data),
        )

        # Create JSON chunk header (chunk type 0)
        json_chunk_header = struct.pack(
            "<II", len(gltf_json_padded), 0x4E4F534A
        )  # "JSON" in little endian

        # Create BIN chunk header (chunk type 1)
        bin_chunk_header = struct.pack(
            "<II", len(buffer_data), 0x004E4942
        )  # "BIN\0" in little endian

        # Write the GLB file
        with open(filepath, "wb") as f:
            f.write(glb_header)
            f.write(json_chunk_header)
            f.write(gltf_json_padded)
            f.write(bin_chunk_header)
            f.write(buffer_data)

        return filepath

    @classmethod
    def save_obj(cls, vertices, faces, filepath):  # noqa: ANN001, ANN206
        """
        Save PyTorch tensor vertices and faces as an OBJ file.

        Parameters:
        vertices: torch.Tensor of shape (N, 3)
        faces: torch.Tensor of shape (M, 3) - triangle indices
        filepath: str - Output filepath (should end with .obj)
        """

        vertices_np = vertices.cpu().numpy()
        faces_np = faces.cpu().numpy()

        with open(filepath, "w") as f:
            for v in vertices_np:
                f.write(f"v {v[0]} {v[1]} {v[2]}\n")

            # OBJ uses 1-based indexing.
            # The vertices described in the earlier section,
            # are referenced by face entries base 1
            # v <x> <y> <z> <- vertex # 1
            # v <x> <y> <z> <- vertex # 2
            # v <x> <y> <z> <- vertex # 3
            # v ...         <- vertex # ...
            for face in faces_np:
                f.write(f"f {face[0] + 1} {face[1] + 1} {face[2] + 1}\n")

        return filepath
