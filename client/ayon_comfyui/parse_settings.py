r"""Deals with project settings.

from ayon_core.settings import get_project_settings, get_studio_settings
from pprint import pprint

settings = get_studio_settings()
pprint(settings["comfyui"])
--------------------
{'local_settings': {'frontend_port': '55056',
                    'local_setting_list': [{'comfy_base_folder_lin': '',
                                            'comfy_base_folder_osx': '',
                                            'comfy_base_folder_win': 'C:\\Users\\sas.vangulik\\Documents\\ComfyUI_windows_portable',
                                            'comfy_setting_name': 'windows '
                                                                  'standalone '
                                                                  'fast fp16 '
                                                                  'accumulation',
                                            'launch_profile': {'extra_custom_node_dirs_lin': [],
                                                               'extra_custom_node_dirs_osx': [],
                                                               'extra_custom_node_dirs_win': ['C:\\Users\\sas.vangulik\\Documents\\comfy_nodes_ayon'],
                                                               'launch_args_lin': [],
                                                               'launch_args_osx': [],
                                                               'launch_args_win': [{'key': '--windows-standalone-build',
                                                                                    'value': ''},
                                                                                   {'key': '--fast',
                                                                                    'value': 'fp16_accumulation'}]},
                                            'python_path_lin': '',
                                            'python_path_osx': '',
                                            'python_path_use_custom': False,
                                            'python_path_win': '',
                                            'dev_omit_packaged_ayon_comfyui_plugin': False,
                                            'comfy_is_windows_portable': True,
                                            }],
                    'server_pulse_port': '55055'}}
"""

from __future__ import annotations

import sys
from typing import Any, ClassVar, TypeVar

from ayon_core.settings import get_project_settings, get_studio_settings

DEFAULT_T = TypeVar("DEFAULT_T")


class ComfyLocalSettings:
    """Contains local settings."""

    class ComfyLocalProfile:
        """Parses a single config to then pass on.

        Automatically takes platform into account.
        """

        def __init__(self, profile_dict: dict[str, str]) -> None:
            """Initialize config helper class."""
            self._name = profile_dict.get("comfy_setting_name")
            os_map = {"win32": "win", "linux": "lin", "darwin": "osx"}
            self._os = os_map.get(sys.platform, "lin")

            self._profile_dict: dict[str, str] = profile_dict

        def _get_platform_profile_setting(
            self, base_key: str
        ) -> str | dict | None:
            """Used in properties to fetch the right value for current OS.

            Returns:
            Value expected from key
            """
            return self._profile_dict.get(f"{base_key}_{self._os}")

        def _get_platform_profile_setting_path(
            self, base_key: str
        ) -> str | None:
            """Used in properties to fetch the right value for current OS.

            Returns:
            Value expected from key, as a normalized path.
            """
            value = self._get_platform_profile_setting(base_key)
            if not isinstance(value, str):
                return None
            if self._os == "win":
                value.replace("\\", "/")
            return value

        def _get_launch_profile_setting(
            self, base_key: str
        ) -> str | dict | None:
            """Used in properties to fetch the right value for current OS.

            Returns:
            Value expected from key
            """
            launch_profile: dict[str, str] = self._profile_dict.get(
                "launch_profile"
            )
            return launch_profile.get(f"{base_key}_{self._os}")

        def _get_launch_profile_setting_path(
            self, base_key: str
        ) -> str | None:
            """Used in properties to fetch the right value for current OS.

            Returns:
            Value expected from key, as a normalized path.
            """
            value = self._get_launch_profile_setting(base_key)
            if not isinstance(value, (str, list)):
                return None
            if self._os == "win":
                if isinstance(value, list):
                    value = [val.replace("\\", "/") for val in value]
                elif isinstance(value, str):
                    value.replace("\\", "/")
            return value

        def _get_launch_profile_args(self) -> list[str]:
            """Concatenate launch args.

            Takes care of windows standalone build flag based on settigns.

            Returns:
                Launch arguments as a list.
            """
            args = []
            for arg in self._get_launch_profile_setting("launch_args"):
                args.extend([arg.get("key"), arg.get("value")])
            launch_args = [arg for arg in args if arg]
            if self._os in {"lin", "osx"} or not self.is_windows_portable:
                launch_args = [
                    arg
                    for arg in launch_args
                    if arg != "--windows-standalone-build"
                ]
            elif self._os == "win" and self.is_windows_portable:
                launch_args = [
                    arg
                    for arg in launch_args
                    if arg != "--windows-standalone-build"
                ]
                # make sure that --windows-standalone-build is always first
                launch_args.insert(0, "--windows-standalone-build")
            return launch_args

        @property
        def name(self) -> str:
            """Returns configuration name."""
            return self._name

        @property
        def base_folder(self) -> str:
            """Gets base folder where ComfyUI is stored."""
            return self._get_platform_profile_setting_path("comfy_base_folder")

        @property
        def using_custom_python(self) -> bool:
            """Return whether custom python path is used."""
            return self._profile_dict.get("python_path_use_custom")

        @property
        def using_managed_venv(self) -> bool:
            """Return whether to use managed venv with python."""
            return self._profile_dict.get("python_use_managed_venv")

        @property
        def custom_python_path(self) -> str | None:
            """Return path to python if a custom."""
            if self.using_custom_python:
                return self._get_platform_profile_setting_path("python_path")
            return None

        @property
        def extra_node_dirs(self) -> list[str]:
            """Return paths to extra nodes."""
            return self._get_launch_profile_setting_path(
                "extra_custom_node_dirs"
            )

        @property
        def launch_args(self) -> list[str]:
            """Return launch arguments for profile.

            Filters out windows portable flag for inappropriate platforms
            """
            return self._get_launch_profile_args()

        @property
        def is_windows_portable(self) -> bool:
            """Return if profile for windows is a windows portable build."""
            launch_kwargs: dict[str, Any] = self._profile_dict.get(
                "launch_profile"
            )
            return launch_kwargs.get("comfy_is_windows_portable")

        @property
        def omit_packaged_plugin(self) -> bool:
            """Return if profile should omit the packaged Comfyui plugin.

            This means that a valid ayon comfyui plugin location
            has to exist in the launch args.
            """
            launch_kwargs: dict[str, Any] = self._profile_dict.get(
                "launch_profile"
            )
            return launch_kwargs.get("dev_omit_packaged_ayon_comfyui_plugin")

        def _validate_profile_for_os(
            self, os_name: str
        ) -> dict[str, list[str]]:
            """Validate this profile and report back.

            Specify os_name to spoof percieved OS for setting retrieval.

            Returns:
                A dict with errors and logs:
                {
                    "errors" : [...],
                    "logs"   : [...],
                }
            """
            # conform
            if os_name in {"win", "win32"}:
                os_name = "win"
            elif os_name in {"lin", "linux"}:
                os_name = "lin"
            elif os_name in {"osx", "darwin"}:
                os_name = "osx"

            old_os = self._os
            self._os = os_name

            # Run tests
            errors = []
            logs = []
            if not self.name:
                errors.append(
                    f"{self.name} | {os_name}: ill formed name for profile"
                    " (must have contents)"
                )
            if not self.base_folder:
                errors.append(
                    f"{self.name} | {os_name}: is missing base folder"
                )
            if not self.custom_python_path and self.using_custom_python:
                errors.append(
                    f"{self.name} | {os_name}: is missing custom "
                    "python path with 'use custom python' specified"
                )
            if not self.extra_node_dirs and self.omit_packaged_plugin:
                logs.append(
                    f"{self.name} | {os_name}: is missing extra node"
                    " directory in dev mode. Ayon plugin may be missing."
                )
            if not self.launch_args:
                logs.append(f"{self.name} | {os_name}: no launch arguments.")

            # restore old os
            self._os = old_os

            return {"errors": errors, "logs": logs}

        def validate_profile(self) -> dict[str, list[str]]:
            """Validate this profile and report back.

            Returns:
                A dict with errors and (benign) logs:
                {
                    "errors" : [...],
                    "logs"   : [...],
                }
            """
            return self._validate_profile_for_os(self._os)

        @property
        def is_valid(self) -> bool:
            """Returns whether profile is bad for current OS."""
            return not bool(self.validate_profile().get("errors"))

        @staticmethod
        def _map_internal_os_name(_os: str) -> str:
            os_name_map = {"win": "Windows", "lin": "Linux", "osx": "MacOSX"}
            return os_name_map.get(_os)

        @property
        def current_os(self) -> str:
            """Return profile OS.

            Possible results:
            Windows, Linux, MacOSX
            """
            return self._map_internal_os_name(self._os)

    def __init__(self, project_name: str | None = None):
        """Initialize settings for local launch."""
        self._settings = {}
        self._profiles: dict[str, ComfyLocalSettings.ComfyLocalProfile] = {}
        if project_name and project_name is not None:
            self._settings = (
                get_project_settings(project_name)
                .get("comfyui")
                .get("local_settings")
            )
        else:
            self._settings = (
                get_studio_settings().get("comfyui").get("local_settings")
            )

        self._port_server = self._settings["server_pulse_port"]
        self._port_web = self._settings["frontend_port"]
        self._parse_settings()

    def _parse_settings(self) -> None:
        """Parse out settings into objects."""
        for setting in self._settings.get("local_setting_list"):
            profile = ComfyLocalSettings.ComfyLocalProfile(setting)
            self._profiles[profile.name] = profile

    @property
    def port_webui(self) -> str:
        """Return string representation of webui connection port."""
        return self._port_web

    @property
    def port_backend(self) -> str:
        """Return string representation of backend connection port."""
        return self._port_server

    @property
    def profiles(self) -> list[str]:
        """Return a list of profile names."""
        return list(self._profiles.keys())

    def __getitem__(self, key: str) -> ComfyLocalProfile | None:
        """Return a profile associated with a name."""
        return self._profiles.get(key)

    def get(
        self, key: str, default: DEFAULT_T | None = None
    ) -> ComfyLocalProfile | DEFAULT_T | None:
        """Return a profile associated with a name, else default.

        Default is None by default.
        """
        return self._profiles.get(key, default)

    def commit(
        self,
        config: ComfyLocalSettings.ComfyLocalProfile | str,
    ) -> None:
        """Commit this & config to LocalComfyCommittedSettings.

        ```
        settings = ComfyLocalSettings("project_name")
        settings.commit("profile name")
        # ... later, maybe in another thread
        settings, profile = ComfyLocalSettings.pull_committed_settings()
        ```
        """
        if isinstance(config, str):
            config = self.get(config)

        LocalComfyCommittedSettings.commit(self, config)

    @classmethod
    def pull_committed_settings(
        cls,
    ) -> tuple[ComfyLocalSettings, ComfyLocalSettings.ComfyLocalProfile]:
        """Return committed settings.

        ```
        settings = ComfyLocalSettings("project_name")
        settings.commit("profile name")
        # ... later, maybe in another thread
        settings, profile = ComfyLocalSettings.pull_committed_settings()
        ```
        """
        return LocalComfyCommittedSettings.pull()


# TODO (@Sas): Decide on whether this should be a private class
class LocalComfyCommittedSettings:
    """Contains a committed pair of Local settings and chosen config.

    This object is for holding state but may not be changed once set.
    Use of this can be omitted by interfacing with
    ```
    settings = ComfyLocalSettings("project_name")
    settings.commit("profile name")
    # ... later, maybe in another thread
    settings, profile = ComfyLocalSettings.pull_committed_settings()
    ```
    """

    _settings: ClassVar[ComfyLocalSettings] = None
    _config: ClassVar[ComfyLocalSettings.ComfyLocalProfile] = None

    @classmethod
    def commit(
        cls,
        settings: ComfyLocalSettings,
        config: ComfyLocalSettings.ComfyLocalProfile,
    ) -> None:
        """Commit settings and configuration to memory."""
        if cls._settings is not None or cls._config is not None:
            # Maybe raise an error but I am not a fan...
            return
        if isinstance(settings, ComfyLocalSettings) and isinstance(
            config, ComfyLocalSettings.ComfyLocalProfile
        ):
            cls._settings = settings
            cls._config = config

    @classmethod
    def pull(
        cls,
    ) -> tuple[ComfyLocalSettings, ComfyLocalSettings.ComfyLocalProfile]:
        """Returns class level stored settings and configuration.

        ```
        settings, profile = LocalComfyCommittedSettings.pull()
        ```
        """
        if cls._settings is not None and cls._config is not None:
            return (cls._settings, cls._config)
        return None
