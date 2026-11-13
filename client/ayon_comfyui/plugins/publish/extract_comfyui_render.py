"""Run the ComfyUI workflow for the instances that recook on publish."""

from __future__ import annotations

from typing import ClassVar

import pyblish.api
from ayon_core.pipeline.publish import KnownPublishError

from ayon_comfyui.api import comfy_publish
from ayon_comfyui.api.publish_lib import (
    COMFYUI_KEY,
    OUTPUT_FAMILIES,
    get_comfy_http,
    responsive_sleep,
)


class ExtractComfyUIRender(pyblish.api.ContextPlugin):
    """Queue the workflow on ComfyUI and wait for its outputs.

    AYON queues the prompt itself, under the prompt id chosen while
    collecting, and only runs the AYON save nodes being published (plus
    what they depend on). It then follows the run in ComfyUI's history, so
    the ComfyUI tab may be reloaded or closed meanwhile, and there is no
    time limit for long renders. To stop a render, cancel it in ComfyUI.

    The ComfyUI tab gets the run's progress and previews like any run
    it queued.
    """

    # After `SaveCurrentScene` saved the workfile.
    order = pyblish.api.ExtractorOrder - 0.45
    label = "Render ComfyUI Outputs"
    hosts: ClassVar[list[str]] = ["comfyui"]
    families: ClassVar[list[str]] = OUTPUT_FAMILIES

    #: Fail when a render takes longer than this many seconds (None: never).
    timeout: float | None = None

    def process(self, context: pyblish.api.Context) -> None:
        instances = [
            instance
            for instance in context
            if instance.data.get("publish", True)
            and instance.data.get("active", True)
            and (instance.data.get(COMFYUI_KEY) or {}).get("recooked")
        ]
        if not instances:
            self.log.debug("No instance needs a ComfyUI render.")
            return

        prompt_id = context.data["comfyuiPromptId"]
        api_prompt = context.data["comfyuiApiPrompt"]
        targets = [
            instance.data[COMFYUI_KEY]["outputNodeId"]
            for instance in instances
        ]
        http = get_comfy_http()
        self.log.info(
            "Queueing ComfyUI run %s for save node(s) %s.",
            prompt_id, ", ".join(targets),
        )
        try:
            comfy_publish.queue_prompt(
                http,
                api_prompt["prompt"],
                prompt_id=prompt_id,
                targets=targets,
                workflow=api_prompt.get("workflow"),
                client_id=api_prompt.get("client_id"),
            )
            comfy_publish.QUEUED_PROMPTS.add(prompt_id)
            entry = comfy_publish.wait_for_prompt(
                http,
                prompt_id,
                timeout=self.timeout,
                log_progress=self.log.info,
                sleep=responsive_sleep,
            )
        except comfy_publish.PublishError as exc:
            raise KnownPublishError(str(exc)) from exc

        for instance in instances:
            data = instance.data[COMFYUI_KEY]
            try:
                run = comfy_publish.run_from_history(
                    prompt_id,
                    entry,
                    data["outputNodeId"],
                    instance.data["instance_id"],
                )
            except comfy_publish.PublishError as exc:
                raise KnownPublishError(str(exc)) from exc
            data["outputs"] = run.files
            self.log.info(
                "'%s': %s file(s) rendered.",
                instance.data.get("productName"), len(run.files),
            )
