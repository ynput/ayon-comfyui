"""Collect which ComfyUI run publishes each AYON save node instance."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import pyblish.api
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import KnownPublishError

from ayon_comfyui.api import comfy_publish
from ayon_comfyui.api.bridge_client import BridgeError
from ayon_comfyui.api.publish_lib import (
    COMFYUI_KEY,
    OUTPUT_FAMILIES,
    get_comfy_http,
)

if TYPE_CHECKING:
    from ayon_comfyui.api.pipeline import ComfyUIHost


class CollectComfyUIPrompt(pyblish.api.ContextPlugin):
    """Get the active workflow as an API prompt from the ComfyUI tab.

    The ComfyUI frontend converts the graph itself, exactly like when the
    artist runs it. A prompt id is chosen up front, so everything about the
    run that will produce the outputs is known while collecting.
    """

    order = pyblish.api.CollectorOrder + 0.1
    label = "Collect ComfyUI Prompt"
    hosts: ClassVar[list[str]] = ["comfyui"]
    families: ClassVar[list[str]] = OUTPUT_FAMILIES

    def process(self, context: pyblish.api.Context) -> None:
        host: ComfyUIHost = registered_host()
        try:
            api_prompt = host.stub.get_api_prompt()
            tab_prompt_ids = host.stub.get_queued_prompt_ids()
        except (BridgeError, RuntimeError) as exc:
            msg = (
                "Unable to get the workflow from the ComfyUI tab, which is "
                f"needed to publish its outputs: {exc}"
            )
            raise KnownPublishError(msg) from exc

        context.data["comfyuiApiPrompt"] = api_prompt
        context.data["comfyuiPromptId"] = comfy_publish.new_prompt_id()
        context.data["comfyuiTabPromptIds"] = tab_prompt_ids
        self.log.debug(
            "Prompt with %s nodes, tab queued %s prompts.",
            len(api_prompt["prompt"]),
            len(tab_prompt_ids),
        )


class CollectComfyUIOutputs(pyblish.api.InstancePlugin):
    """Decide which ComfyUI run makes the outputs of an AYON save node.

    - "Recook on publish" on (the node's toggle): the outputs will be made
      by running the current workflow, limited to the save nodes being
      published (see `ExtractComfyUIRender`).
    - Off: the newest finished run of this save node that this AYON session
      or its ComfyUI tab queued is published as-is.

    Sets `instance.data["comfyui"]` with `promptId`, `prompt`, `workflow`,
    `outputNodeId`, `recooked`, and for earlier runs already `outputs`.
    """

    order = pyblish.api.CollectorOrder + 0.2
    label = "Collect ComfyUI Outputs"
    hosts: ClassVar[list[str]] = ["comfyui"]
    families: ClassVar[list[str]] = OUTPUT_FAMILIES

    def process(self, instance: pyblish.api.Instance) -> None:
        context = instance.context
        api_prompt: dict = context.data["comfyuiApiPrompt"]
        instance_id = instance.data.get("instance_id")
        product_name = instance.data.get("productName")

        try:
            save_nodes = context.data.get("comfyuiSaveNodes")
            if save_nodes is None:
                save_nodes = comfy_publish.find_save_nodes(
                    api_prompt["prompt"]
                )
                context.data["comfyuiSaveNodes"] = save_nodes
        except comfy_publish.PublishError as exc:
            raise KnownPublishError(str(exc)) from exc

        node = save_nodes.get(instance_id)
        if node is None:
            msg = (
                f"The AYON save node of '{product_name}' isn't part of the "
                "active ComfyUI workflow, or it is bypassed or muted. Enable "
                "it, or disable this instance in the Publisher."
            )
            raise KnownPublishError(msg)

        if node.recook:
            data = {
                "promptId": context.data["comfyuiPromptId"],
                "prompt": api_prompt["prompt"],
                "workflow": api_prompt.get("workflow"),
                "outputNodeId": node.node_id,
                "recooked": True,
                "outputs": [],
            }
            self.log.info(
                "'%s' will be rendered from the current workflow (node %s).",
                product_name, node.node_id,
            )
        else:
            data = self._earlier_run(instance, instance_id, product_name)

        instance.data[COMFYUI_KEY] = data
        if instance.data.get("productType") in {"image", "render"}:
            instance.data["review"] = True
            families = instance.data.setdefault("families", [])
            if "review" not in families:
                families.append("review")

    def _earlier_run(
        self,
        instance: pyblish.api.Instance,
        instance_id: str,
        product_name: str,
    ) -> dict:
        context = instance.context
        try:
            run = comfy_publish.find_latest_run(
                get_comfy_http(),
                instance_id,
                comfy_publish.QUEUED_PROMPTS.newest_first(),
                context.data.get("comfyuiTabPromptIds") or [],
            )
        except comfy_publish.PublishError as exc:
            raise KnownPublishError(str(exc)) from exc
        if run is None:
            msg = (
                f"There is no finished ComfyUI run of the AYON save node of "
                f"'{product_name}' to publish. Run the workflow in this "
                "AYON session's ComfyUI tab first, or enable 'Recook on "
                "publish' on the node."
            )
            raise KnownPublishError(msg)
        self.log.info(
            "Publishing '%s' from the earlier ComfyUI run %s (node %s).",
            product_name, run.prompt_id, run.node_id,
        )
        return {
            "promptId": run.prompt_id,
            "prompt": run.prompt,
            "workflow": run.workflow,
            "outputNodeId": run.node_id,
            "recooked": False,
            "outputs": run.files,
        }
