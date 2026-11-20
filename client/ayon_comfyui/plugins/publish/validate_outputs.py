from __future__ import annotations

import inspect

import pyblish.api
from ayon_core.pipeline.publish import PublishValidationError


class ValidateOutputs(pyblish.api.InstancePlugin):
    """Validate that the product's node has an output to publish.

    A node only has outputs after the workflow ran in ComfyUI.
    """

    order = pyblish.api.ValidatorOrder
    label = "Validate Outputs"
    hosts = ["comfyui"]
    families = ["image", "render", "model"]

    def process(self, instance: pyblish.api.Instance) -> None:
        if instance.data.get("representations"):
            return

        product_name = instance.data["productName"]
        msg = (
            f"'{product_name}' has no output to publish. Run the workflow "
            "in ComfyUI, then publish again."
        )
        raise PublishValidationError(
            msg,
            title="No output to publish",
            description=self.get_description(),
        )

    @staticmethod
    def get_description() -> str:
        return inspect.cleandoc("""
            ### No output to publish

            The node of this product has no output yet. A node only has
            outputs after the workflow ran in ComfyUI.

            Press **Run** in ComfyUI, wait for the workflow to finish and
            then publish again.
        """)
