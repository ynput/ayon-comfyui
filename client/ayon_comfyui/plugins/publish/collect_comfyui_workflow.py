"""Collect the ComfyUI workflow that is published, as it is right now."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import pyblish.api
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.publish import KnownPublishError

from ayon_comfyui.api.bridge_client import BridgeError
from ayon_comfyui.api.publish_lib import (
    WORKFLOWS_FEATURE,
    missing_plugin_feature,
    split_api_prompt,
)

if TYPE_CHECKING:
    from ayon_comfyui.api.pipeline import ComfyUIHost


class CollectComfyUIWorkflow(pyblish.api.ContextPlugin):
    """Collect the ComfyUI workflow (tab) to publish, and pin it.

    That's the workflow whose instances the Publisher shows (or the active
    one). It must be the active tab now; its graph and API prompt are taken
    once, and the rest of the publish works from those and acts on that
    tab by its AYON key (`context.data["comfyuiWorkflow"]`, see
    `RPCStub.target_workflow`). So the artist can keep working, switch
    tabs or open other workfiles while it publishes: the saved and
    published workfile and a recooked render are what was collected.

    Sets `comfyuiWorkflow` (`{workflow_key, workflow_label}`) and
    `comfyuiApiPrompt` (the prompt, the UI workflow, its identity and
    workfile path; without the tab's credentials).
    """

    order = pyblish.api.CollectorOrder - 0.51
    label = "Collect ComfyUI Workflow"
    hosts: ClassVar[list[str]] = ["comfyui"]

    def process(self, context: pyblish.api.Context) -> None:
        outdated = missing_plugin_feature(WORKFLOWS_FEATURE)
        if outdated:
            raise KnownPublishError(outdated)
        host: ComfyUIHost = registered_host()
        pinned = host.stub.publisher_workflow
        try:
            with host.stub.target_workflow(pinned):
                api_prompt, _extra = split_api_prompt(
                    host.stub.get_api_prompt(snapshot=True)
                )
        except BridgeError as exc:
            raise KnownPublishError(self._explain(exc, pinned)) from exc
        except RuntimeError as exc:
            msg = f"Unable to get the workflow from the ComfyUI tab: {exc}"
            raise KnownPublishError(msg) from exc

        target = None
        if api_prompt.get("workflow_key"):
            target = {
                "workflow_key": api_prompt["workflow_key"],
                "workflow_label": api_prompt.get("workflow_label"),
            }
        context.data["comfyuiWorkflow"] = target
        context.data["comfyuiApiPrompt"] = api_prompt
        self.log.info(
            "Publishing ComfyUI workflow '%s'.",
            api_prompt.get("workflow_label")
            or api_prompt.get("workflow_path"),
        )

    @staticmethod
    def _explain(exc: BridgeError, pinned: dict | None) -> str:
        label = (pinned or {}).get("workflow_label") or "?"
        if exc.code == "workflow_inactive":
            return (
                "AYON publishes the ComfyUI workflow whose instances the "
                f"Publisher shows: '{label}'. {exc} Or refresh the Publisher "
                "to publish the active workflow instead."
            )
        if exc.code == "workflow_closed":
            return (
                f"The ComfyUI workflow '{label}' whose instances the "
                "Publisher shows was closed. Refresh the Publisher."
            )
        return f"Unable to get the workflow from the ComfyUI tab: {exc}"
