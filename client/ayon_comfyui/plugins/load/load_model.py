"""Load 3d model definition."""

from __future__ import annotations

import os
from typing import ClassVar

import clique
from ayon_comfyui.api.pipeline import containerise
from ayon_comfyui.api.plugin import ComfyUILoader
from ayon_comfyui.api.rpc_stub import LoadType


class ModelLoader(ComfyUILoader):
    """Load model.

    TODO(@sas): Only supports exports for singular models,
    expand so that sequences of objs/glbs can be properly loaded,
    but maybe, we have to make multiple Loader nodes as any File3D type
    isn't batchable.
    """

    product_types: ClassVar[set[str]] = {"model"}
    # Published representations are named by their extension, without dot.
    representations: ClassVar[set[str]] = {"*"}
    extensions: ClassVar[set[str]] = {
        "gltf",
        "glb",
        "obj",
        "fbx",
        "stl",
        "spz",
        "splat",
        "ply",
        "ksplat",
    }
    label = "Load model into current graph."
    icon = "robot"
    order = -10.2

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
        filepaths = self.filepath_from_context(context=context)
        self.log.debug(filepaths)
        folder = f"{namespace}_{name}" if namespace else name

        files = self.make_files_available(
            context, [filepaths], folder,
            reference=bool((options or {}).get("reference_files")),
        )
        # containerizing also adds to context.
        container: dict = containerise(
            name=name,
            namespace=namespace,
            context=context,
            loader=self.__class__.__name__,
            **files,
        )

        # Create the video loader node with the data on it.
        self.stub.create_load_node(container, LoadType.MODEL3D)

    def remove(self, container: dict) -> None:
        """Remove container from context and scene."""
        self.stub.remove_containers(container)
        self.stub.remove_load_nodes(container, LoadType.MODEL3D)

    def update(self, container: dict, context: dict) -> None:
        """Point the container at another version's files.

        Uploads them into the same input subfolder, or references them
        when the container already did.
        """
        filepaths = [self.filepath_from_context(context=context)]
        self.update_files(container, context, filepaths)
        self.stub.update_containers(container)

    def switch(self, container: dict, context: dict) -> None:
        """Provide interface for switching calls."""
        self.update(container=container, context=context)

    # Maybe deprecate. should be singular.
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
