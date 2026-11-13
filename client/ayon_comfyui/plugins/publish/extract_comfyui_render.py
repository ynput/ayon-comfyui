"""Run the ComfyUI workflow for the instances that recook on publish."""

from __future__ import annotations

import re
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
    RenderCancelled,
    RenderWait,
)

if TYPE_CHECKING:
    from ayon_comfyui.api.pipeline import ComfyUIHost

# Errors of API nodes that didn't get the artist's Comfy.org login.
AUTH_ERROR_HINTS = re.compile(
    r"\b(unauthori[sz]ed|401|api[ _-]?key|log ?in|sign ?in)\b",
    re.IGNORECASE,
)


class ExtractComfyUIRender(pyblish.api.ContextPlugin):
    """Queue the workflow on ComfyUI and wait for its outputs.

    The workflow is the one collected when publishing started (see
    `CollectComfyUIWorkflow`), which is also what the published workfile
    holds. AYON queues it itself under the prompt id chosen while
    collecting and only runs the AYON save nodes being published (plus what
    they depend on). It then follows the run in ComfyUI's history, so
    meanwhile the artist may keep working, switch tabs, or reload or close
    the ComfyUI tab, and there is no time limit for long renders. To stop a
    render, cancel it in the progress window or in ComfyUI's queue.

    The ComfyUI tab gets the run's progress and previews like any run
    it queued.
    """

    # After `SaveCurrentScene` saved the workfile (not that it matters: both
    # use the collected workflow).
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

        api_prompt: dict = context.data["comfyuiApiPrompt"]
        extra_data = self._queue_extra_data()
        try:
            save_nodes = comfy_publish.find_save_nodes(api_prompt["prompt"])
        except comfy_publish.PublishError as exc:
            raise KnownPublishError(str(exc)) from exc

        prompt_id = context.data["comfyuiPromptId"]
        targets = []
        for instance in instances:
            data = instance.data[COMFYUI_KEY]
            node = save_nodes.get(instance.data["instance_id"])
            if node is None:
                msg = (
                    "The AYON save node of "
                    f"'{instance.data.get('productName')}' isn't part of "
                    "the collected workflow."
                )
                raise KnownPublishError(msg)
            # What actually runs, for later plugins to describe the run.
            data.update(
                prompt=api_prompt["prompt"],
                workflow=api_prompt.get("workflow"),
                outputNodeId=node.node_id,
            )
            targets.append(node.node_id)

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
                extra_data=extra_data,
            )
        except comfy_publish.PublishError as exc:
            raise KnownPublishError(str(exc)) from exc
        comfy_publish.QUEUED_PROMPTS.add(
            prompt_id, comfy_publish.workflow_identity(api_prompt)
        )

        finished = False
        try:
            products = ", ".join(
                str(instance.data.get("productName")) for instance in instances
            )
            # The wait keeps processing Qt events: show the progress with a
            # way to cancel. What the artist does meanwhile (e.g. "Save
            # Workfile" in the tab) runs right away: this publish doesn't
            # depend on the tab anymore.
            with RenderWait(
                f"ComfyUI is rendering {products} for publishing.\n"
                "Cancel here, or in ComfyUI's queue, to stop it."
            ) as waiter:

                def log_progress(message: str) -> None:
                    self.log.info(message)
                    waiter.progress(message)

                entry = comfy_publish.wait_for_prompt(
                    http,
                    prompt_id,
                    timeout=self.timeout,
                    log_progress=log_progress,
                    sleep=waiter.sleep,
                )
            finished = True
        except RenderCancelled as exc:
            raise KnownPublishError(str(exc)) from exc
        except comfy_publish.PublishError as exc:
            msg = str(exc)
            if AUTH_ERROR_HINTS.search(msg):
                msg += (
                    "\n\nIf this is a Comfy.org API node: AYON reuses the "
                    "Comfy.org login of the last run started in the ComfyUI "
                    "tab (a login expires after an hour). Run the workflow "
                    "once in the tab and publish again, or publish without "
                    "'Recook on publish'."
                )
            raise KnownPublishError(msg) from exc
        finally:
            if not finished and comfy_publish.cancel_prompt(http, prompt_id):
                # Don't leave our run on a shared queue when we gave up.
                self.log.info("Cancelled ComfyUI run %s.", prompt_id)

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

    def _queue_extra_data(self) -> dict:
        """What the tab adds when it queues a prompt itself.

        Taken now rather than when collecting: it holds the artist's
        Comfy.org login for API nodes, which expires, and is never stored.
        """
        host: ComfyUIHost = registered_host()
        try:
            return host.stub.get_queue_extra_data()
        except (BridgeError, RuntimeError) as exc:
            # E.g. the tab was closed: only API nodes need it.
            self.log.warning(
                "Queueing without the ComfyUI tab's Comfy.org login and "
                "preview setting: %s", exc,
            )
            return {}
