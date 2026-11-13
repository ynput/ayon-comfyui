"""Plugin helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import ayon_api
from ayon_core.lib import BoolDef
from ayon_core.pipeline import (
    AutoCreator,
    CreatedInstance,
    Creator,
    LoaderPlugin,
)
from ayon_core.pipeline.load import LoadError

if TYPE_CHECKING:
    from ayon_core.pipeline.create.context import CreateContext

from ayon_comfyui.api.bridge import get_bridge, get_stub
from ayon_comfyui.api.load_util import container_files
from ayon_comfyui.api.pipeline import (
    build_selection,
    list_instances,
    make_container,
    resolve_version_mode,
)
from ayon_comfyui.api.rpc_stub import LoadType, RPCStub


class ComfyUICreator(Creator):
    skip_discovery = True
    settings_category = "comfyui"

    @property
    def stub(self) -> RPCStub:
        """Return the stub to talk to the paired ComfyUI tab."""
        return get_stub()


class ComfyUIAutoCreator(AutoCreator):
    """Generic ComfyUI autocreator to extend."""

    skip_discovery = True
    settings_category = "comfyui"

    def get_instance_attr_defs(self):
        return []

    def collect_instances(self):
        for instance_data in list_instances():
            # Process only instances that were created by this creator
            creator_id = instance_data.get("creator_identifier")
            if creator_id == self.identifier:
                # Create instance object from existing data
                instance = CreatedInstance.from_existing(instance_data, self)
                # Add instance to create context
                self._add_instance_to_context(instance)

    def update_instances(self, update_list: list[tuple[CreatedInstance, Any]]):
        stub = get_stub()
        updated = [
            instance.data_to_store() for instance, _changes in update_list
        ]
        stub.update_instance(updated)

    def create(self, options=None):
        stub = get_stub()
        existing_instance = None
        for instance in self.create_context.instances:
            if instance.product_type == self.product_type:
                existing_instance = instance
                break

        context: CreateContext = self.create_context
        project_name = context.get_current_project_name()
        folder_path = context.get_current_folder_path()
        task_name = context.get_current_task_name()
        host_name = context.host_name

        if existing_instance is None:
            existing_instance_folder = None
        else:
            existing_instance_folder = existing_instance["folderPath"]

        if existing_instance is None:
            folder_entity = ayon_api.get_folder_by_path(
                project_name, folder_path
            )
            task_entity = ayon_api.get_task_by_name(
                project_name, folder_entity["id"], task_name
            )
            product_name = self.get_product_name(
                project_name,
                folder_entity,
                task_entity,
                self.default_variant,
                host_name,
            )
            data = {
                "folderPath": folder_path,
                "task": task_name,
                "variant": self.default_variant,
                "productName": product_name,
                "projectName": project_name,
            }
            data.update(
                self.get_dynamic_data(
                    project_name,
                    folder_entity,
                    task_entity,
                    self.default_variant,
                    host_name,
                    None,
                )
            )

            new_instance = CreatedInstance(
                self.product_type, product_name, data, self
            )
            self._add_instance_to_context(new_instance)
            stub.update_instance(new_instance.data_to_store())

        elif (
            existing_instance_folder != folder_path
            or existing_instance["task"] != task_name
        ):
            folder_entity = ayon_api.get_folder_by_path(
                project_name, folder_path
            )
            task_entity = ayon_api.get_task_by_name(
                project_name, folder_entity["id"], task_name
            )
            product_name = self.get_product_name(
                project_name,
                folder_entity,
                task_entity,
                self.default_variant,
                host_name,
            )
            existing_instance["folderPath"] = folder_path
            existing_instance["task"] = task_name
            existing_instance["productName"] = product_name
            existing_instance["projectName"] = project_name


class ComfyUILoader(LoaderPlugin):
    """Base for loader plugins.

    Loading makes the representation's files available to ComfyUI (uploads
    them to its input directory, or, opt-in, references them by path) and
    puts the resulting container on an `AYON Load ...` node of type
    `load_type`. `build_container` does that and returns the container
    without touching the graph; it is shared by load, update/switch and the
    AYON pickers on the nodes (`ayon_comfyui.api.pickers`).
    """

    hosts: ClassVar[list[str]] = ["comfyui"]
    settings_category = "comfyui"
    # A base class: discovery finds it in every plugin module importing it.
    skip_discovery = True

    # The node type the loader puts its containers on.
    load_type: ClassVar[LoadType | None] = None

    options: ClassVar[list] = [
        BoolDef(
            "reference_files",
            label="Reference files on the ComfyUI server",
            default=False,
            tooltip=(
                "Read the files where they are published instead of "
                "uploading a copy to ComfyUI. Needs the ComfyUI server to "
                "reach the project's AYON roots; otherwise the files are "
                "uploaded after all."
            ),
        ),
    ]

    def make_files_available(
        self,
        context: dict,
        filepaths: list[str],
        subfolder: str,
        *,
        reference: bool = False,
    ) -> dict:
        """Upload `filepaths` to ComfyUI, or reference them in place.

        Returns:
            The container's `image_upload_info` and `path_reference`.
        """
        return container_files(
            self.comfy_url,
            context["project"]["name"],
            filepaths,
            subfolder=subfolder,
            reference=reference,
        )

    def update_files(
        self, container: dict, context: dict, filepaths: list[str]
    ) -> None:
        """Make the files of a new version available, the same way."""
        files = self.make_files_available(
            context,
            filepaths,
            self.upload_subfolder(container, container.get("name") or "AYON"),
            reference=bool(container.get("path_reference")),
        )
        container["representation"] = context["representation"]["id"]
        container["image_upload_info"] = files["image_upload_info"]
        if files["path_reference"]:
            container["path_reference"] = files["path_reference"]
        else:
            container.pop("path_reference", None)

    @staticmethod
    def upload_subfolder(container: dict, default: str) -> str:
        """Return the input subfolder a container's files were uploaded to."""
        uploads = container.get("image_upload_info") or []
        if uploads:
            return uploads[0].get("subfolder") or default
        return default

    @property
    def stub(self) -> RPCStub:
        """Return the stub to talk to the paired ComfyUI tab."""
        return get_stub()

    @property
    def comfy_url(self) -> str:
        """Return the URL of ComfyUI this session is connected to."""
        return get_bridge().comfy_url

    def get_upload_files(self, context: dict) -> list[str]:
        """Return the files of the representation to upload to ComfyUI."""
        return [self.filepath_from_context(context=context)]

    def build_container(  # noqa: PLR0913
        self,
        context: dict,
        container: dict | None = None,
        *,
        name: str | None = None,
        namespace: str | None = None,
        container_uuid: str | None = None,
        version_mode: str | None = None,
        reference: bool | None = None,
    ) -> dict:
        """Make the files of `context` available; return the container.

        Arguments:
            context: Representation context to load.
            container: Existing container to update. Its identity, upload
                subfolder and other keys are kept.
            name: Name of a new container, defaults to the product name.
            namespace: Namespace of a new container.
            container_uuid: Identifier of a new container, e.g. of a node
                that is loaded into; a new one by default.
            version_mode: "latest" or "pinned". By default an updated
                container keeps "latest" only while it loads the latest
                version, see `resolve_version_mode`.
            reference: Reference the files by path instead of uploading
                them (see `make_files_available`). By default an updated
                container keeps doing what it did; a new one uploads.
        """
        previous_selection = (container or {}).get("selection") or {}
        if version_mode is None:
            version_mode = resolve_version_mode(
                context, previous_selection.get("version_mode")
            )
        if reference is None:
            reference = bool((container or {}).get("path_reference"))

        if name is None:
            name = context["product"]["name"]
        default_subfolder = f"{namespace}_{name}" if namespace else name
        subfolder = (
            self.upload_subfolder(container, default_subfolder)
            if container is not None
            else default_subfolder
        )
        files = self.make_files_available(
            context,
            self.get_upload_files(context),
            subfolder,
            reference=reference,
        )
        if not files["image_upload_info"] and not files["path_reference"]:
            msg = (
                "Unable to upload "
                f"{context['representation']['name']} to ComfyUI."
            )
            raise LoadError(msg)

        if container is None:
            return make_container(
                name=name,
                namespace=namespace,
                context=context,
                image_upload_info=files["image_upload_info"],
                path_reference=files["path_reference"],
                loader=self.__class__.__name__,
                container_uuid=container_uuid,
                version_mode=version_mode,
            )

        container = dict(container)
        container["representation"] = context["representation"]["id"]
        container["project_name"] = context["project"]["name"]
        container["image_upload_info"] = files["image_upload_info"]
        if files["path_reference"]:
            container["path_reference"] = files["path_reference"]
        else:
            container.pop("path_reference", None)
        container["selection"] = build_selection(context, version_mode)
        return container

    def load(
        self,
        context: dict,
        name: str | None = None,
        namespace: str | None = None,
        options: dict | None = None,
    ) -> None:
        """Load the representation and add a load node for it."""
        container = self.build_container(
            context,
            name=name,
            namespace=namespace,
            reference=bool((options or {}).get("reference_files")),
        )
        self.stub.add_containers(container)
        self.stub.create_load_node(container, self.load_type)

    def update(self, container: dict, context: dict) -> None:
        """Point the container at another version's files.

        Uploads them into the same input subfolder, or references them
        when the container already did.
        """
        container = self.build_container(context, container)
        self.stub.update_containers(container)

    def switch(self, container: dict, context: dict) -> None:
        """Switch the container to another representation."""
        self.update(container=container, context=context)

    def remove(self, container: dict) -> None:
        """Remove container from context and scene."""
        self.stub.remove_containers(container)
        self.stub.remove_load_nodes(container, self.load_type)
