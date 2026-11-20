"""Remote Launch Settings for the addon."""

from __future__ import annotations

from ayon_server.settings import BaseSettingsModel, SettingsField
from ayon_server.settings.validators import ensure_unique_names
from pydantic import validator


class ComfyRemoteSetting(BaseSettingsModel):
    """Comfy Remote Executable & Launch profiles settings."""

    name: str = SettingsField(default="", title="Entry Name")

    comfy_web_adress: str = SettingsField(
        default="http://127.0.0.1:8188",
        title="ComfyUI Web Address",
        description=(
            "Web address of ComfyUI. On localhost, ComfyUI runs on port "
            "8188, so the address would be 'http://127.0.0.1:8188'. For a "
            "shared server use something like 'https://comfyui.contoso.com' "
            "(a sub-path such as 'https://contoso.com/comfyui' works too). "
            "The AYON ComfyUI plugin must be installed on that ComfyUI, "
            "and a reverse proxy in front of it must pass websockets for "
            "'/ayon/ws' and '/api/ayon/ws', like it does for ComfyUI's "
            "own '/ws'."
        ),
    )

    open_browser_on_connect: bool = SettingsField(
        default=True,
        title="Open browser on connect?",
        description=(
            "Open the ComfyUI tab for this AYON session automatically. "
            "When disabled, AYON shows the link (and a pairing code) to "
            "open or paste manually."
        ),
    )


class ComfyRemoteSettings(BaseSettingsModel):
    """Group together settings."""

    # Port settings
    remote_setting_list: list[ComfyRemoteSetting] = SettingsField(
        default_factory=list, title="Remote configuration entry"
    )

    @validator("remote_setting_list")
    def validate_unique_names_remotesettings(cls, value):
        ensure_unique_names(value)
        return value
