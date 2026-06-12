"""Settings for the addon."""

from __future__ import annotations

from typing import Any

from ayon_server.settings import BaseSettingsModel, SettingsField

from .local_settings import ComfyLocalSettings
from .remote_settings import ComfyRemoteSettings
from .creators import CreatorsModel, DEFAULT_CREATORS_SETTINGS


COMFY_DEFAULT_VALUES: dict[str, Any] = {
    "create": DEFAULT_CREATORS_SETTINGS,
    "local_settings": {"local_setting_list": []},
    "remote_settings": {"remote_setting_list": []},
}


class ComfyUISettings(BaseSettingsModel):
    """Settings for the addon."""

    local_settings: ComfyLocalSettings = SettingsField(
        default_factory=ComfyLocalSettings,
        title="ComfyUI local launch options",
    )

    remote_settings: ComfyRemoteSettings = SettingsField(
        default_factory=ComfyRemoteSettings,
        title="ComfyUI remote launch options",
    )

    create: CreatorsModel = SettingsField(
        default_factory=CreatorsModel, title="Creators"
    )
