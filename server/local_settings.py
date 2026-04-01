"""Local Launch Settings for the addon."""

from __future__ import annotations

from ayon_server.settings import BaseSettingsModel, SettingsField
from ayon_server.settings.validators import ensure_unique_names
from pydantic import validator

# comfyui:
#      base_path: path/to/comfyui/
#      # You can use is_default to mark that these folders should be listed
#      # first, and used as the default dirs for eg downloads
#      #is_default: true
#      checkpoints: models/checkpoints/
#      text_encoders: |
#           models/text_encoders/
#           models/clip/  # legacy location still supported
#      clip_vision: models/clip_vision/
#      configs: models/configs/
#      controlnet: models/controlnet/
#      diffusion_models: |
#                   models/diffusion_models
#                   models/unet
#      embeddings: models/embeddings/
#      loras: models/loras/
#      upscale_models: models/upscale_models/
#      vae: models/vae/
#      audio_encoders: models/audio_encoders/
#      model_patches: models/model_patches/

DIR_TYPES_ENUM = [
    {"label": "Automatic (Based on subdirectory name)", "value": "auto"},
    {
        "label": "Automatic (No validity checking, all subdirectories)",
        "value": "auto_nocheck",
    },
    {"label": "Custom Nodes", "value": "custom_nodes"},
    {"label": "Checkpoints", "value": "checkpoints"},
    {"label": "Diffusion Models", "value": "diffusion_models"},
    {"label": "Diffusers", "value": "diffusers"},
    {"label": "Classifiers", "value": "classifiers"},
    {"label": "LoRAs", "value": "loras"},
    {"label": "Style Models", "value": "style_models"},
    {"label": "GLIGEN", "value": "gligen"},
    {"label": "ControlNet", "value": "controlnet"},
    {"label": "Configs", "value": "configs"},
    {"label": "Approximate VAEs", "value": "vae_approx"},
    {"label": "VAEs", "value": "vae"},
    {"label": "Text Encoders", "value": "text_encoders"},
    {"label": "CLIP Vision", "value": "clip_vision"},
    {"label": "Upscale Models", "value": "upscale_models"},
    {"label": "Latent Upscale Models", "value": "latent_upscale_models"},
    {"label": "Hyper Network", "value": "hypernetworks"},
    {"label": "Photo Maker", "value": "photomaker"},
    {"label": "Model Patches", "value": "model_patches"},
    {"label": "Audio Encoders", "value": "audio_encoders"},
]


class LocalProfileDirMapping(BaseSettingsModel):
    """Stores directories for extra config generation."""

    name: str = SettingsField(
        "",
        title="Name",
        description=("Name used for alias during diagnostics."),
    )

    dir_type: str = SettingsField(
        default="auto",
        title="Folder type",
        enum_resolver=lambda: DIR_TYPES_ENUM,
        description=(
            "Specify what kind of directory is added. "
            "The directory type specifies what type of files ComfyUI "
            "expects to be present there. 'Automatic' looks in the "
            "subdirectory for valid ComfyUI directories using the expected "
            "names that ComfyUI/folderpaths.py can expect."
        ),
    )

    is_enabled: bool = SettingsField(
        default=True,
        title="Enabled:",
        description=(
            "Enable/Disable a config from being processed without removing it."
        ),
    )

    dirs_win: list[str] = SettingsField(
        default_factory=list,
        title="Custom directories windows",
        description="Add windows directories that ComfyUI may search through.",
    )
    dirs_lin: list[str] = SettingsField(
        default_factory=list,
        title="Custom directories linux",
        description="Add linux directories that ComfyUI may search through.",
    )
    dirs_osx: list[str] = SettingsField(
        default_factory=list,
        title="Custom directories MacOsx",
        description="Add MacOsx directories that ComfyUI may search through.",
    )


class LaunchArgsMappingModel(BaseSettingsModel):
    """Model for launch arguments."""

    _layout = "compact"
    # No default for key, must have value
    key: str = SettingsField(title="Key")
    value: str = SettingsField("", title="Value (can be empty)")


class ComfyLocalProfile(BaseSettingsModel):
    """Specifies launch arguments / extra dirs."""

    comfy_is_windows_portable: bool = SettingsField(
        default=True,
        title="Is windows path a 'portable windows' build?",
        description=(
            "On windows, if the designated folder is a windows portable build "
            "the plugin will look for python in python_embeded and add the "
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

    extra_dirs: list[LocalProfileDirMapping] = SettingsField(
        default_factory=list,
        title="Extra directories",
        description=(
            "Extra directories for ComfyUI to search through. "
            "These get added to the generated configuration YAML at start."
        ),
    )

    @validator("extra_dirs")
    def validate_unique_names_dirs(cls, value):
        ensure_unique_names(value)
        return value


class ComfyLocalSetting(BaseSettingsModel):
    """Comfy Local Executable & Launch profiles settings."""

    name: str = SettingsField("", title="Setting name")

    comfy_launch_port: int = SettingsField(
        default=8188,
        title="Port for ComfyUI (default = 8188)",
        description=(
            "Comfyui will be launched on http://127.0.0.1:port, "
            "with http://127.0.0.1:8188 being the default."
        ),
    )

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
            "If not on windows, use either a specified installation of python "
            "when 'Use alternate python' is enabled, or the default version "
            "that shows up on execution of 'python' in the console, to make "
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
    http_server_port: int = SettingsField(
        5454,
        title="Default port for website user interacts with.",
        description=(
            "This port is used to launch a wrapper website "
            "for ComfyUI. This websites hosts an <iframe> the "
            "'real' ComfyUI will be embedded in."
        ),
    )

    server_pulse_port: int = SettingsField(
        55055,
        title="Default port to pulse connection to backend",
        description="Websocket port to send heartbeat over, to make sure the backend process is still alive",
    )

    frontend_port: int = SettingsField(
        55056,
        title="Default port for frontend websocket RPC",
        description="Websocket port to communicate with local browser instance",
    )

    local_setting_list: list[ComfyLocalSetting] = SettingsField(
        default_factory=list, title="Local configuration entry"
    )

    @validator("local_setting_list")
    def validate_unique_names_localsettings(cls, value):
        ensure_unique_names(value)
        return value
