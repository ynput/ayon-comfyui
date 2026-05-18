from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from ayon_comfyui.api.rpc_stub import RPCStub
    from ayon_core.pipeline.create.context import CreateContext

from ayon_comfyui.api.pipeline import list_instances
from ayon_comfyui.api.qt_rpc import QRPCManager
from ayon_comfyui.api.rpc_stub import PublishType
from ayon_core.lib import BoolDef, EnumDef, NumberDef, TextDef
from ayon_core.pipeline import CreatedInstance, Creator, CreatorError
from ayon_core.pipeline.create import PRODUCT_NAME_ALLOWED_SYMBOLS


class VideoCreator(Creator):
    """Creator for video before publishing.

    On create, spawn a node that is to be associated with
    this publish.
    """

    identifier = "io.ayon.creators.comfyui.render"
    label = "Video"
    product_base_type = "render"
    product_type = product_base_type
    description = "Video generated using ComfyUI"

    default_variant = "Main"
    default_vid_name = "ayon"

    icon = "gears"

    enabled = True

    enum_output_format: ClassVar[dict] = {
        "mp4/h264": "MP4 | H.264",
        "webm/av1": "WEBM | AV1",
        "webm/vp9": "WEBM | VP9",
    }

    def create(  # noqa: D102
        self,
        product_name: str,
        data: dict[str, Any],
        pre_create_data: dict[str, bool | str],
    ) -> None:
        stub: RPCStub = QRPCManager.get_instance().stub

        keep_metadata: bool = pre_create_data.get("keep_metadata")
        prefix: str = pre_create_data.get("file_prefix")
        use_unique_name: bool = pre_create_data.get("use_unique_name")
        unique_name: str = pre_create_data.get("unique_name")
        formatcodec: str = pre_create_data.get("formatcodec")
        webm_noaudio: bool = pre_create_data.get("webm_noaudio")
        webm_crf: float = pre_create_data.get("webm_crf")
        force_recook: bool = pre_create_data.get("force_recook_on_publish")

        context: CreateContext = self.create_context
        project_name = context.get_current_project_name()
        folder_path = context.get_current_folder_path()
        task_name = context.get_current_task_name()
        # host_name = context.host_name

        prefix = re.sub(f"[^{PRODUCT_NAME_ALLOWED_SYMBOLS}]+", "", prefix)

        unique_name = re.sub(
            f"[^{PRODUCT_NAME_ALLOWED_SYMBOLS}]+", "", unique_name
        )

        data.update(
            {
                "folderPath": folder_path,
                "task": task_name,
                "variant": self.default_variant,
                "projectName": project_name,
            }
        )

        if use_unique_name:
            product_name = f"{prefix}_{unique_name}_{product_name}"
        else:
            product_name = f"{prefix}_{product_name}"

        creator_attributes = {
            "keep_metadata": keep_metadata,
            "use_unique_name": use_unique_name,
            "prefix": prefix,
            "unique_name": unique_name,
            "formatcodec": formatcodec,
            "webm_noaudio": webm_noaudio,
            "webm_crf": int(webm_crf),
            "force_recook_on_publish": force_recook,
        }
        data.update(
            {
                "productName": product_name,
                "creator_attributes": creator_attributes,
            }
        )

        # Check for collisions with existing names.
        instances = [
            instance
            for instance in list_instances()
            if instance.get("productType") == self.product_type
        ]

        if any(
            instance.get("productName") == product_name
            for instance in instances
        ):
            raise CreatorError(
                "Name collision. "  # noqa: EM101
                "please specify a different prefix / unique name"
            )

        new_instance = CreatedInstance(
            self.product_type, product_name, data, self
        )

        self._add_instance_to_context(new_instance)
        stub.create_publish_node(
            new_instance.data_to_store(), PublishType.VIDEO
        )
        stub.update_instance(new_instance.data_to_store())

    def collect_instances(self):
        for instance_data in list_instances():
            # Process only instances that were created by this creator
            creator_id = instance_data.get("creator_identifier")
            if creator_id == self.identifier:
                # Create instance object from existing data
                instance = CreatedInstance.from_existing(instance_data, self)
                # Add instance to create context
                self._add_instance_to_context(instance)

    def update_instances(  # noqa: D102, PLR6301
        self, update_list: list[tuple[CreatedInstance, Any]]
    ) -> None:
        stub: RPCStub = QRPCManager.get_instance().stub
        updated = [
            instance.data_to_store() for instance, _changes in update_list
        ]
        stub.update_instance(updated)

    def remove_instances(self, instances: list[CreatedInstance]):
        stub: RPCStub = QRPCManager.get_instance().stub
        stub.remove_publish_nodes(
            [i.data_to_store() for i in instances], PublishType.VIDEO
        )
        stub.remove_instance(instances)
        for instance in instances:
            self._remove_instance_from_context(instance)

    def get_pre_create_attr_defs(self):
        return [
            BoolDef("keep_metadata", default=True, label="Keep metadata?"),
            BoolDef(
                "force_recook_on_publish",
                default=False,
                label="Force re-cook on publish?",
            ),
            TextDef(
                "file_prefix",
                multiline=False,
                default=self.default_vid_name,
                label="Extra prefix for file",
            ),
            BoolDef(
                "use_unique_name",
                default=True,
                label="Use unique product name?",
            ),
            TextDef(
                "unique_name",
                multiline=False,
                default=self.default_vid_name,
                label="Unique name included in saved file",
            ),
            EnumDef(
                "formatcodec",
                items=self.enum_output_format,
                label="Output Format | Codec",
            ),
            BoolDef("webm_noaudio", default=False, label="WebM omit audio?"),
            NumberDef(
                "webm_crf",
                minimum=0,
                maximum=63,
                decimals=0,
                default=32,
                label="WebM Compression (FFMPEG CRF)",
            ),
        ]

    def get_detail_description(self) -> str:  # noqa: D102, PLR6301
        return """Creator plugin for publishing ComfyUI videos.

        Use the "Create Video" builtin node to construct a video first.
        WebM is a bit experimental but supports audio using OPUS.

        Audio is automatically resampled to conform to OPUS' standard.
        """
