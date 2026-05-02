"""Load image definition."""

from __future__ import annotations

import os
from typing import ClassVar

import clique
from ayon_comfyui.api.pipeline import containerise
from ayon_comfyui.api.plugin import ComfyUILoader
from ayon_comfyui.api.upload_util import upload_input_images


class ImageLoader(ComfyUILoader):
    """Load images."""

    product_types: ClassVar[set[str]] = {"image", "render"}
    representations: ClassVar[set[str]] = {"*"}
    label = "Load image(s) into current graph."
    icon = "image"
    order = -10

    def load(
        self,
        context: dict,
        name: str | None = None,
        namespace: str | None = None,
        options: dict | None = None,
    ) -> None:
        """Load asset via database.

        Arguments:
            context (dict): Full parenthood of representation to load
            name (str, optional): Use pre-defined name
            namespace (str, optional): Use pre-defined namespace
            options (dict, optional): Additional settings dictionary
        """
        # Retrieve filepath
        filepaths = self.expand_files_if_sequence(context)
        self.log.debug(filepaths)
        folder = f"{namespace}_{name}" if namespace else name
        # Upload image to ComfyUI.
        # TODO(@sas): Maybe fire this off in a thread,
        #             and infer the upload info.
        image_upload_info = upload_input_images(
            filepaths, self.comfy_url, subfolder=folder
        )

        # containerizing also adds to context.
        container: dict = containerise(
            name=name,
            namespace=namespace,
            context=context,
            image_upload_info=image_upload_info,
            loader=self.__class__.__name__,
        )

        # Create the image loader node with the data on it.
        self.stub.create_load_node(container)

    def remove(self, container: dict) -> None:
        """Remove container from context and scene."""
        self.stub.remove_containers(container)
        self.stub.remove_load_nodes(container)

    def update(self, container: dict, context: dict) -> None:
        """Update container with new uploded file."""
        # Retrieve filepaths
        # filepath = self.filepath_from_context(context=context)
        filepaths = self.expand_files_if_sequence(context)
        # Upload image to ComfyUI.
        # TODO(@sas): Maybe fire this off in a thread,
        #             and infer the upload info.

        old_subfolder = next(iter(container["image_upload_info"]))["subfolder"]

        image_upload_info = upload_input_images(
            filepaths, self.comfy_url, subfolder=old_subfolder
        )

        container["representation"] = context["representation"]["id"]
        container["image_upload_info"] = image_upload_info

        self.stub.update_containers(container)

    def switch(self, container: dict, context: dict) -> None:
        """Provide interface for switching calls."""
        self.update(container=container, context=context)

    def expand_files_if_sequence(self, context: dict) -> list[str]:
        """Return all images in sequence if appliccable."""
        filepath = self.filepath_from_context(context=context)
        basename = os.path.basename(filepath)
        filedir = os.path.dirname(filepath)
        files = [f for f in os.listdir(filedir) if not os.path.isdir(f)]

        collections, _ = clique.assemble(files)
        collections: list[clique.Collection]
        for collection in collections:
            if collection.match(basename):
                return [os.path.join(filedir, f) for f in collection]
        return [filepath]
