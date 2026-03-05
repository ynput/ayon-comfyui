"""Remote Launch Settings for the addon."""

from __future__ import annotations

from ayon_server.settings import BaseSettingsModel, SettingsField


class ComfyRemoteSetting(BaseSettingsModel):
    """Comfy Local Executable & Launch profiles settings."""

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


class MkcertSettings(BaseSettingsModel):
    """Settings for mkcert, a tool for generating CA and keys for locahost."""

    win_mkcert_path: str = SettingsField("", title="mkcert windows location")

    lin_mkcert_path: str = SettingsField("", title="mkcert linux location")

    osx_mkcert_path: str = SettingsField("", title="mkcert macosx location")

    uninstall_after_session: bool = SettingsField(
        default=False,
        title="Uninstall mkcert CA on exit?",
        description=(
            "If you feel anxious about having a non-standard CA "
            "in the stores, we can remove it after. "
            "This is annoying, because there will be a "
            "pop-up each time, but it might soothe the "
            "heart of your IT-person. I would recommend reading "
            "up on mkcert and reviewing the code in other plugins "
            "that open servers in order to calm down."
        ),
    )


class ComfyRemoteSettings(BaseSettingsModel):
    """Group together settings."""

    # Port settings
    remote_setting_list: list[ComfyRemoteSetting] = SettingsField(
        default_factory=list, title="Remote configuration entry"
    )

    mkcert: MkcertSettings = SettingsField(
        default_factory=MkcertSettings,
        title="Location of mkcert executable",
        description=(
            "For https connections, "
            "proper SSL requires a local CA and keys. "
            "This is done with mkcert (see README of plugin)."
        ),
    )
