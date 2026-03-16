"""Remote Launch Settings for the addon."""

from __future__ import annotations

from ayon_server.settings import BaseSettingsModel, SettingsField


class ComfyRemoteSetting(BaseSettingsModel):
    """Comfy Remote Executable & Launch profiles settings."""

    comfy_setting_name: str = SettingsField(default="", title="Entry Name")

    server_pulse_port: int = SettingsField(
        55055,
        title="Default port to pulse connection to backend",
        description=(
            "Websocket port to send heartbeat over, "
            "to make sure the backend process is still alive. "
            "This port must be configured to be the same on the "
            "server you are connecting to."
        ),
    )

    frontend_port: int = SettingsField(
        55056,
        title="Default port for frontend RPC",
        description="Websocket port to communicate with local browser instance",
    )

    http_server_port: int = SettingsField(
        5454,
        title="Default port for website user interacts with.",
        description=(
            "This port is used to launch a wrapper website "
            "for ComfyUI. This websites hosts an <iframe> the "
            "'real' ComfyUI will be embedded in."
        ),
    )

    comfy_web_adress: str = SettingsField(
        default="http://localhost:8188",
        title="ComfyUI Web Address",
        description=(
            "Web adress of the frontend. On localhost, "
            "ComfyUI runs on port 8188, so the adress would be "
            "'http://localhost:8188'. If comfyui is on the web, "
            "use something like 'https://comfyui.contoso.com'."
        ),
    )

    open_browser_on_connect: bool = SettingsField(
        default=True, title="Open browser on connect?"
    )


class ComfyRemoteSettings(BaseSettingsModel):
    """Group together settings."""

    # Port settings
    remote_setting_list: list[ComfyRemoteSetting] = SettingsField(
        default_factory=list, title="Remote configuration entry"
    )
