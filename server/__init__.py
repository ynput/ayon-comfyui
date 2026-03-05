"""Server package settings."""

from typing import Type

from ayon_server.addons import BaseServerAddon

from .settings import COMFY_DEFAULT_VALUES, ComfyUISettings


class ComfyUIAddon(BaseServerAddon):
    """Add-on class for the server."""

    settings_model: Type[ComfyUISettings] = ComfyUISettings

    async def get_default_settings(self) -> ComfyUISettings:
        """Return default settings."""
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**COMFY_DEFAULT_VALUES)
