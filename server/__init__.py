"""Server package settings."""

from typing import TYPE_CHECKING, List, Optional, Type

from ayon_server.addons import BaseServerAddon
from ayon_server.actions import SimpleActionManifest

if TYPE_CHECKING:
    from ayon_server.actions import (
        ExecuteResponseModel,
        ActionExecutor,
    )


from .settings import COMFY_DEFAULT_VALUES, ComfyUISettings


class ComfyUIAddon(BaseServerAddon):
    """Add-on class for the server."""

    settings_model: Type[ComfyUISettings] = ComfyUISettings

    async def get_default_settings(self) -> ComfyUISettings:
        """Return default settings."""
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**COMFY_DEFAULT_VALUES)

    async def get_simple_actions(
        self,
        project_name: Optional[str] = None,
        variant: str = "production",
    ) -> List["SimpleActionManifest"]:
        return [
            SimpleActionManifest(
                order=1,
                identifier="comfyui.launch",
                label="Launch ComfyUI",
                category="Applications",
                entity_type="task",
                allow_multiselection=False,
                icon={
                    "type": "material-symbols",
                    "name": "robot",
                    "color": "#A200FF",
                },
            ),
            SimpleActionManifest(
                order=1,
                identifier="comfyui.launch",
                label="Launch ComfyUI",
                category="Applications",
                entity_type="workfile",
                allow_multiselection=False,
                icon={
                    "type": "material-symbols",
                    "name": "robot",
                    "color": "#FFAB66",
                },
            ),
        ]

    async def execute_action(
        self, executor: "ActionExecutor"
    ) -> "ExecuteResponseModel":
        if executor.identifier != "comfyui.launch":
            return await executor.get_simple_response(
                message=(
                    "Failed to launch ComfyUI. "
                    "Unknown action identifier."
                ),
                success=False,
            )

        if executor.context.entity_type not in ["task", "workfile"]:
            return await executor.get_simple_response(
                message=(
                    "Failed to launch ComfyUI. "
                    "This action can only be executed on tasks or workfiles."
                ),
                success=False,
            )

        if len(executor.context.entity_ids) > 1:
            return await executor.get_simple_response(
                message=(
                    "Failed to launch ComfyUI. "
                    "This action cannot be executed on multiple entities."
                ),
                success=False,
            )

        # i think this is already handled automatically
        # bundle_args: List[str] = []
        # if executor.variant not in ("production", "staging"):
        #     bundle_args = ["--bundle", executor.variant]

        args = [
            "addon", "comfyui", "run-server",
            "--project-name", executor.context.project_name,
            "--entity-id", executor.context.entity_ids[0],
        ]
        # args.extend(bundle_args) # keep this out for now

        return await executor.get_launcher_response(
            args=args
        )
