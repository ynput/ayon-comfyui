from __future__ import annotations

import json
import os
from fractions import Fraction
from pathlib import Path
from secrets import token_hex
from traceback import print_tb

import av
import av.audio.resampler
import folder_paths
import numpy as np
import torch
from comfy_api.latest import AudioInput, ImageInput, Types, io, ui
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from torch import Tensor


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
        """Main execution function."""

        # parse ayon_info and retrieve settings from there.
        try:
            ayon_json = json.loads(ayon_info)
        except BaseException as e:
            print_tb(e)

        creator_attrs = ayon_json["creator_attributes"]

        keep_metadata = creator_attrs["keep_metadata"]
        file_prefix = creator_attrs["prefix"]
        use_unique_name = creator_attrs["use_unique_name"]
        unique_name = creator_attrs["unique_name"]

        compress_level = creator_attrs.get("compression_level", 4)

        output_dir = folder_paths.get_output_directory()

        # for:
        # folder_paths.get_save_image_path(
        #     filename_prefix = "renders/dragon"
        #     self.output_dir = "C:/ComfyUI/output"
        #     width = 1024
        #     height = 1024
        # )

        # full_output_folder = "C:/ComfyUI/output/renders"
        # filename = "dragon_1024x1024"
        # counter = 1 <- increments based on files that are already there
        # subfolder = "renders"
        # filename_prefix = "dragon"

        # I'm choosing to ignore the counter, and we're just going to overwrite the files.

        full_prefix = file_prefix
        if use_unique_name:
            full_prefix += f"_{unique_name}"

        full_output_folder, filename, counter, subfolder, filename_prefix = (
            folder_paths.get_save_image_path(
                f"AYON/{ayon_json['productName']}/{full_prefix}",
                output_dir,
                images_in[0].shape[1],
                images_in[0].shape[0],
            )
        )

        images_processed = []

        for idx, image in enumerate(images_in, start=1):
            image_data = 255.0 * image.cpu().numpy()
            img_pil = Image.fromarray(np.clip(image_data, 0, 255).astype(np.uint8))
            # clip to 8 bit PNG. This could need work, png also supports 16 bit,1
            # if data needs to exist as float, and we need to export within OpenEXR,
            # we're screwed if we do this.

            metadata = None
            if keep_metadata:
                metadata = PngInfo()
                if cls.hidden.prompt is not None:
                    metadata.add_text("prompt", json.dumps(cls.hidden.prompt))
                if (extra_pnginfo := cls.hidden.extra_pnginfo) is not None:
                    for info in cls.hidden.extra_pnginfo:
                        metadata.add_text(info, json.dumps(extra_pnginfo[info]))

            filename_out = f"{filename}_{idx:0>4}.png"
            img_path = os.path.join(full_output_folder, filename_out)

            # ensure path existence.

            Path(img_path).parent.mkdir(parents=True, exist_ok=True)
            img_pil.save(img_path, pnginfo=metadata, compress_level=compress_level)

            images_processed.append(
                ui.SavedResult(filename_out, subfolder, io.FolderType.output)
            )

        return io.NodeOutput(ui=ui.SavedImages(results=images_processed))


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
        # parse ayon_info and retrieve settings from there.
        try:
            ayon_json = json.loads(ayon_info)
        except BaseException as e:
            print_tb(e)

        creator_attrs = ayon_json["creator_attributes"]

        keep_metadata: bool = creator_attrs["keep_metadata"]
        file_prefix: str = creator_attrs["prefix"]
        use_unique_name: bool = creator_attrs["use_unique_name"]
        unique_name: str = creator_attrs["unique_name"]

        # mp4/h264 | webm/vp9 | webm/av1
        formatcodec: str = creator_attrs["formatcodec"]

        webm_no_audio: bool = creator_attrs["webm_noaudio"]
        # 0- > 63 (32 middleground), higher better quality
        webm_crf: float = float(creator_attrs["webm_crf"])

        format, codec = [x.strip() for x in formatcodec.split("/")]

        output_dir = folder_paths.get_output_directory()

        full_prefix = file_prefix
        if use_unique_name:
            full_prefix += f"_{unique_name}"

        components = video_in.get_components()
        images, audio, fps, metadata = (
            components.images,
            components.audio,
            components.frame_rate,
            components.metadata,
        )

        full_output_folder, filename, counter, subfolder, filename_prefix = (
            folder_paths.get_save_image_path(
                f"AYON/{ayon_json['productName']}/{full_prefix}",
                output_dir,
                images[0].shape[1],
                images[0].shape[0],
            )
        )

        saved_metadata = metadata if metadata else {}
        if not keep_metadata:
            metadata = {}
            if cls.hidden.extra_pnginfo is not None:
                metadata.update(cls.hidden.extra_pnginfo)
            if cls.hidden.prompt is not None:
                metadata["prompt"] = cls.hidden.prompt
            if len(metadata) > 0:
                saved_metadata = metadata

        filename_with_ext = f"{filename}.{format}"
        filename_thumbnail = f"{filename}_{format}_thumb.png"

        # thumbnail
        thumb_image = images[0]
        thumb_image_data = 255.0 * thumb_image.cpu().numpy()
        thumb_img_pil = Image.fromarray(
            np.clip(thumb_image_data, 0, 255).astype(np.uint8)
        )
        thumb_loc = os.path.join(full_output_folder, filename_thumbnail)
        thumb_img_pil.save(thumb_loc, compress_level=4)

        video_saved = None

        if format == "mp4":
            video_in.save_to(
                os.path.join(full_output_folder, filename_with_ext),
                format=Types.VideoContainer.MP4,
                codec=Types.VideoCodec.H264,
                metadata=saved_metadata,
            )
            video_saved = [
                ui.SavedResult(filename_with_ext, subfolder, io.FolderType.output)
            ]
        elif format == "webm":
            if webm_no_audio:
                audio = None

            video_saved = [
                cls.save_webm(
                    full_output_folder,
                    filename + ".webm",
                    subfolder,
                    codec,
                    webm_crf,
                    fps,
                    images,
                    audio,
                )
            ]

        return io.NodeOutput(ui=ui.PreviewVideo(video_saved))

    @classmethod
    def save_webm(
        cls,
        full_output_folder: str,
        file: str,
        subfolder: str,
        codec: str,
        crf: float,
        fps: float,
        images: ImageInput,
        audio_input: AudioInput | None = None,
    ):
        container = av.open(os.path.join(full_output_folder, file), mode="w")

        if cls.hidden.prompt is not None:
            container.metadata["prompt"] = json.dumps(cls.hidden.prompt)

        if cls.hidden.extra_pnginfo is not None:
            for x in cls.hidden.extra_pnginfo:
                container.metadata[x] = json.dumps(cls.hidden.extra_pnginfo[x])

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
                audio_stream = container.add_stream("libopus", rate=target_sample_rate)
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

        return ui.SavedResult(file, subfolder, io.FolderType.output)
