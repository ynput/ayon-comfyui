"""Abstract away and store project settings for ease of use."""

from __future__ import annotations

import sys
from typing import Any, ClassVar, TypeVar
from urllib.parse import ParseResult, urlparse

from ayon_core.settings import get_project_settings, get_studio_settings

from ayon_comfyui.api.connection_util import (
    poll_site_availability_timeout,
    poll_site_headers,
)

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
        def comfy_port(self) -> str:
            """Gets port where comfyui is supposed to run."""
            return self._profile_dict.get("comfy_launch_port")

        @property
        def comfy_local_url(self) -> str:
            """Gets complete http adress comfy runs on."""
            return f"http://127.0.0.1:{self.comfy_port}"

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

        self._port_server: int = self._settings["server_pulse_port"]
        self._port_web: int = self._settings["frontend_port"]
        self._port_http_static: int = self._settings["http_server_port"]
        self._parse_settings()

    def _parse_settings(self) -> None:
        """Parse out settings into objects."""
        for setting in self._settings.get("local_setting_list"):
            profile = ComfyLocalSettings.ComfyLocalProfile(setting)
            self._profiles[profile.name] = profile

    @property
    def port_webui(self) -> int:
        """Return webui connection port."""
        return self._port_web

    @property
    def port_backend(self) -> int:
        """Return backend connection port."""
        return self._port_server

    @property
    def port_static_frontend(self) -> int:
        """Return static frontend port (hosts <iframe> with ComfyUI)."""
        return self._port_http_static

    @property
    def address_frontend(self) -> str:
        """Return static frontend adress."""
        return f"http://localhost:{self.port_static_frontend}"

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
        """Commit this & config to ComfyCommittedSettings.

        ```
        settings = ComfyLocalSettings("project_name")
        settings.commit("profile name")
        # ... later, maybe in another thread
        settings, profile = ComfyLocalSettings.pull_committed_settings()
        ```
        """
        if isinstance(config, str):
            config = self.get(config)

        ComfyCommittedSettings.commit(self, config)

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
        return ComfyCommittedSettings.pull()


class ComfyRemoteSettings:
    """Contains global settings for remote connections."""

    class ComfyRemoteProfile:
        """Parses a single config to then pass on."""

        def __init__(self, profile_dict: dict[str, str]) -> None:
            """Initialize config helper class."""
            self._name = profile_dict.get("comfy_setting_name")
            self._profile_dict: dict[str, str] = profile_dict

            self._is_valid = None
            self._cached_validation = {"errors": [], "logs": []}

        def validate_profile(
            self, *, rerun: bool = False
        ) -> dict[str, list[str]]:
            """Validate this profile and report back.

            Only run on demand, since this tries connecting to sites.

            Returns:
                A dict with errors and (benign) logs:
                {
                    "errors" : [...],
                    "logs"   : [...],
                }
            """
            if self._is_valid is not None and not rerun:
                return self._cached_validation

            errors = []
            logs = []

            if not self.name:
                errors.append(
                    f"{self.name} | Remote: ill formed name for profile"
                    " (must have contents)"
                )

            is_available = poll_site_availability_timeout(
                self.comfy_url, timeout=1
            )

            static_origin = f"http://localhost:{self.port_static_frontend}"

            if is_available:
                logs.append(
                    f"{self.name} | Remote: site {self.comfy_url}"
                    " is reachable!"
                )
                headers = poll_site_headers(self.comfy_url)
                if "X-Frame-Options" in headers:
                    errors.append(
                        f"{self.name} | Remote: X-Frame-Options header set!"
                        " This likely causes ComfyUI not to embed properly."
                    )

                    xframeopts = headers.get("X-Frame-Options")
                    possible_working_xframeopts = f"ALLOW-FROM {static_origin}"
                    if xframeopts != possible_working_xframeopts:
                        errors.append(
                            f"{self.name} | Remote: X-Frame -Options header: "
                            f"'{xframeopts}' will not work."
                        )
                    else:
                        logs.append(
                            f"{self.name} | Remote: there is a small chance "
                            f"X-Frame-Options: {possible_working_xframeopts} "
                            "could still allow the plugin to function."
                        )

                if "Content-Security-Policy" in headers:
                    csp = headers.get("Content-Security-Policy")
                    ideal_csps = {
                        "frame-ancestors *",
                        f"frame-ancestors {static_origin}",
                    }

                    if csp in ideal_csps:
                        logs.append(
                            f"{self.name} | Remote: Content-Security-Policy "
                            f"header present, but value '{csp}' should work."
                        )
                    else:
                        errors.append(
                            f"{self.name} | Remote: Content-Security-Policy "
                            f"header present, with a value of {csp}. "
                            "This makes embedding likely impossible."
                        )
            else:
                errors.append(
                    f"{self.name} | Remote: site {self.comfy_url} is "
                    "unreachable. Couldn't connect."
                )

            self._is_valid = not bool(errors)
            self._cached_validation = {"errors": errors, "logs": logs}

            return self._cached_validation

        @property
        def name(self) -> str:
            """Return profile name."""
            return self._name

        @property
        def port_webui(self) -> int:
            """Return webui connection port."""
            return self._profile_dict.get("frontend_port")

        @property
        def port_backend(self) -> int:
            """Return backend connection port."""
            return self._profile_dict.get("server_pulse_port")

        @property
        def port_static_frontend(self) -> int:
            """Return port to static frontend."""
            return self._profile_dict.get("http_server_port")

        @property
        def address_frontend(self) -> str:
            """Return static frontend adress."""
            return f"http://localhost:{self.port_static_frontend}"

        @property
        def comfy_url(self) -> str:
            """Return URL to embed in browser."""
            return self._profile_dict.get("comfy_web_adress")

        # TODO(@sas): Look into deprecation, since origin checking
        #             is likely unnessecary.
        @property
        def comfy_origin(self) -> str:
            """Return URL expected to be in Origin header."""
            parsed = urlparse(self.comfy_url)
            return f"{parsed.scheme}://{parsed.netloc}"

        @property
        def is_https(self) -> bool:
            """Return whether url is https."""
            parsed = urlparse(self.comfy_url)
            return parsed.scheme == "https"

        @property
        def netloc_webui(self) -> str:
            """Return netloc of webui."""
            url = urlparse(self.comfy_url)._replace(netloc="localhost")
            url = ComfyRemoteSettings.url_specify_port(url, self.port_webui)
            return urlparse(url).netloc

        @property
        def netloc_backend(self) -> str:
            """Return netloc of webui."""
            url_comfy = urlparse(self.comfy_url)
            print(url_comfy, self.port_backend)
            url = ComfyRemoteSettings.url_specify_port(
                url_comfy, self.port_backend
            )
            print(url)
            return urlparse(url).netloc

        @property
        def open_browser(self) -> bool:
            """Whether to open browser."""
            return self._profile_dict.get("open_browser_on_connect")

        @property
        def is_valid(self) -> bool:
            """Returns whether profile is bad."""
            return not bool(self.validate_profile().get("errors"))

    def __init__(self, project_name: str | None):
        """Initialize settings for local launch."""
        self._settings = {}
        self._profiles: dict[str, ComfyRemoteSettings.ComfyRemoteProfile] = {}
        if project_name and project_name is not None:
            self._settings = (
                get_project_settings(project_name)
                .get("comfyui")
                .get("remote_settings")
            )
        else:
            self._settings = (
                get_studio_settings().get("comfyui").get("remote_settings")
            )
        self._parse_settings()

    def _parse_settings(self) -> None:
        """Parse out settings into objects."""
        for setting in self._settings.get("remote_setting_list"):
            profile = ComfyRemoteSettings.ComfyRemoteProfile(setting)
            self._profiles[profile.name] = profile

    @staticmethod
    def url_specify_port(parsed_url: ParseResult, port: int) -> str:
        """Change the port on an URL and return it.

        Returns:
            Updated url.
        """
        netloc = parsed_url.netloc
        if ":" in netloc:
            netloc = f"{netloc.split(':')[0]}:{port}"
        else:
            netloc += f":{port}"
        return parsed_url._replace(netloc=netloc).geturl()

    @property
    def profiles(self) -> list[str]:
        """Return a list of profile names."""
        return list(self._profiles.keys())

    def __getitem__(self, key: str) -> ComfyRemoteProfile | None:
        """Return a profile associated with a name."""
        return self._profiles.get(key)

    def get(
        self, key: str, default: DEFAULT_T | None = None
    ) -> ComfyRemoteProfile | DEFAULT_T | None:
        """Return a profile associated with a name, else default.

        Default is None by default.
        """
        return self._profiles.get(key, default)

    def commit(
        self,
        config: ComfyRemoteSettings.ComfyRemoteProfile | str,
    ) -> None:
        """Commit this & config to ComfyCommittedSettings.

        ```
        settings = ComfyRemoteSettings("project_name")
        settings.commit("profile name")
        # ... later, maybe in another thread
        settings, profile = ComfyRemoteSettings.pull_committed_settings()
        ```
        """
        if isinstance(config, str):
            config = self.get(config)

        ComfyCommittedSettings.commit(self, config)

    @classmethod
    def pull_committed_settings(
        cls,
    ) -> tuple[ComfyRemoteSettings, ComfyRemoteSettings.ComfyRemoteProfile]:
        """Return committed settings.

        ```
        settings = ComfyRemoteSettings("project_name")
        settings.commit("profile name")
        # ... later, maybe in another thread
        settings, profile = ComfyRemoteSettings.pull_committed_settings()
        ```
        """
        return ComfyCommittedSettings.pull()


# TODO (@Sas): Decide on whether this should be a private class
class ComfyCommittedSettings:
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

    _settings: ClassVar[ComfyLocalSettings | ComfyRemoteSettings] = None
    _config: ClassVar[
        ComfyLocalSettings.ComfyLocalProfile | ComfyRemoteSettings
    ] = None

    @classmethod
    def commit(
        cls,
        settings: ComfyLocalSettings | ComfyRemoteSettings,
        config: ComfyLocalSettings.ComfyLocalProfile
        | ComfyRemoteSettings.ComfyRemoteProfile,
    ) -> None:
        """Commit settings and configuration to memory."""
        if cls._settings is not None or cls._config is not None:
            # Maybe raise an error but I am not a fan...
            return
        if isinstance(
            settings, (ComfyLocalSettings, ComfyRemoteSettings)
        ) and isinstance(
            config,
            (
                ComfyLocalSettings.ComfyLocalProfile,
                ComfyRemoteSettings.ComfyRemoteProfile,
            ),
        ):
            cls._settings = settings
            cls._config = config

    @classmethod
    def pull(
        cls,
    ) -> (
        tuple[ComfyLocalSettings, ComfyLocalSettings.ComfyLocalProfile]
        | tuple[ComfyRemoteSettings, ComfyRemoteSettings.ComfyRemoteProfile]
    ):
        """Returns class level stored settings and configuration.

        ```
        settings, profile = LocalComfyCommittedSettings.pull()
        ```
        """
        if cls._settings is not None and cls._config is not None:
            return (cls._settings, cls._config)
        return None
