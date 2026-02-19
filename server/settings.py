"""Settings for the addon."""

from __future__ import annotations

from typing import Any

from ayon_server.settings import BaseSettingsModel, SettingsField

COMFY_DEFAULT_VALUES: dict[str, Any] = {
    "local_settings": {"local_setting_list": []}
}


class LaunchArgsMappingModel(BaseSettingsModel):
    """Model for launch arguments."""

    _layout = "compact"
    # No default for key, must have value
    key: str = SettingsField(title="Key")
    value: str = SettingsField("", title="Value (can be empty)")


class ComfyLocalProfile(BaseSettingsModel):
    """Specifies launch arguments / extra node dirs."""

    extra_custom_node_dirs_win: list[str] = SettingsField(
        default_factory=list,
        title="Custom node directories windows",
        description="Add windows directories that ComfyUI may search through.",
    )
    extra_custom_node_dirs_lin: list[str] = SettingsField(
        default_factory=list,
        title="Custom node directories linux",
        description="Add linux directories that ComfyUI may search through.",
    )
    extra_custom_node_dirs_osx: list[str] = SettingsField(
        default_factory=list,
        title="Custom node directories MacOsx",
        description="Add MacOsx directories that ComfyUI may search through.",
    )

    comfy_is_windows_portable: bool = SettingsField(
        default=True,
        title="Is windows path a 'portable windows' build?",
        description=(
            "On windows, if the designated folder is a windows portable build "
            "the plugin will look for python in python_embedded and add the "
            "--windows-portable flag to launch arguments.",
        ),
    )

    dev_omit_packaged_ayon_comfyui_plugin: bool = SettingsField(
        default=False, title="Omit included plugin (use for developing)"
    )

    launch_args_win: list[LaunchArgsMappingModel] = SettingsField(
        default_factory=list,
        title="Launch arguments for Windows",
        description="Extra launch arguments for Windows",
    )

    launch_args_lin: list[LaunchArgsMappingModel] = SettingsField(
        default_factory=list,
        title="Launch arguments for Linux",
        description="Extra launch arguments for Linux",
    )

    launch_args_osx: list[LaunchArgsMappingModel] = SettingsField(
        default_factory=list,
        title="Launch arguments for MacOsx",
        description="Extra launch arguments for MacOsx",
    )


class ComfyLocalSetting(BaseSettingsModel):
    """Comfy Local Executable & Launch profiles settings."""

    comfy_setting_name: str = SettingsField(default="")

    comfy_base_folder_win: str = SettingsField(
        "", title="ComfyUI folder on windows."
    )
    comfy_base_folder_lin: str = SettingsField(
        "", title="ComfyUI folder on Linux."
    )
    comfy_base_folder_osx: str = SettingsField(
        "", title="ComfyUI folder on MacOsx."
    )

    python_path_use_custom: bool = SettingsField(
        default=False,
        title="Use alternate python?",
        description=(
            "If using Comfy UI as is from the git repository, "
            "toggle this to use a different python executable."
        ),
    )

    python_use_managed_venv: bool = SettingsField(
        default=True,
        title="Use managed virtual environment with python",
        description=(
            "If not on windows, use a either"
            "a specified installation of python when "
            "'Use alternate python' is enabled, "
            "or the default version that shows up "
            "on execution of 'python' in the console, to make "
            "a virtual environment in the AYON folder that holds all "
            "dependencies."
        ),
    )

    python_path_win: str = SettingsField(
        "", title="Windows", description="Windows custom ComfyUI python path"
    )
    python_path_lin: str = SettingsField(
        "", title="Linux", description="Linux custom ComfyUI python path"
    )
    python_path_osx: str = SettingsField(
        "", title="MacOsx", description="MacOsx custom ComfyUI python path"
    )

    launch_profile: ComfyLocalProfile = SettingsField(
        default_factory=ComfyLocalProfile, title="Launch configuration"
    )


class ComfyLocalSettings(BaseSettingsModel):
    """Group together settings."""

    # Port settings
    server_pulse_port: str = SettingsField(
        "55055",
        title="Default port to pulse connection to backend",
        description="Websocket port to send heartbeat over, to make sure the backend process is still alive",
        regex=r"\b[1-9]\d+\b",
    )

    frontend_port: str = SettingsField(
        "55056",
        title="Default port for frontend RPC",
        description="Websocket port to communicate with local browser instance",
        regex=r"\b[1-9]\d+\b",
    )

    local_setting_list: list[ComfyLocalSetting] = SettingsField(
        default_factory=list, title="Local configuration entry"
    )


class ComfyUISettings(BaseSettingsModel):
    """Settings for the addon."""

    local_settings: ComfyLocalSettings = SettingsField(
        default_factory=ComfyLocalSettings,
        title="ComfyUI local Launch options",
    )
