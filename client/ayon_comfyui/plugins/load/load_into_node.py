"""Load into the ComfyUI node that opened the AYON Loader."""

from __future__ import annotations

from typing import ClassVar

from ayon_core.pipeline.load import LoadError

from ayon_comfyui.api.pickers import (
    get_load_target,
    loaders_by_node_type,
    take_load_target,
)
from ayon_comfyui.api.plugin import ComfyUILoader


class LoadIntoComfyUINode(ComfyUILoader):
    """Load into the node whose "Open AYON Loader..." button was clicked.

    Only offered while a node waits for it, and only for representations
    that node can load. The node keeps the loaded version pinned.
    """

    product_types: ClassVar[set[str]] = {"*"}
    representations: ClassVar[set[str]] = {"*"}
    extensions: ClassVar[set[str]] = {"*"}
    label = "Load into waiting ComfyUI node"
    icon = "arrow-right"
    color = "#56a8f5"
    order = -20

    # Not the loader of a node type itself.
    load_type = None

    @classmethod
    def is_compatible_loader(cls, context: dict) -> bool:
        """Offer this action only while a node waits for this context."""
        target = get_load_target()
        if target is None:
            return False
        loader = loaders_by_node_type().get(target["node_type"])
        return loader is not None and loader.is_compatible_loader(context)

    def load(
        self,
        context: dict,
        name: str | None = None,  # noqa: ARG002
        namespace: str | None = None,  # noqa: ARG002
        options: dict | None = None,  # noqa: ARG002
    ) -> None:
        """Load the representation into the waiting node."""
        target = take_load_target()
        if target is None:
            msg = (
                "No ComfyUI node is waiting for a representation anymore. "
                "Use 'Open AYON Loader...' on the node again."
            )
            raise LoadError(msg)
        loader_cls = loaders_by_node_type().get(target["node_type"])
        if loader_cls is None or not loader_cls.is_compatible_loader(context):
            msg = f"An {target['node_type']} node can't load this."
            raise LoadError(msg)
        container = loader_cls(context).build_container(
            context,
            name=context["product"]["name"],
            namespace=context["folder"]["name"],
            container_uuid=target["container_uuid"],
            version_mode="pinned",
        )
        self.stub.picker_applied(target["token"], container=container)
