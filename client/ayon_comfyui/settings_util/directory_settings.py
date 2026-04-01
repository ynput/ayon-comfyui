"""Directory processing utilities."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from .template_helper import template_wrap

VALID_DIRS = {
    "custom_nodes",
    "checkpoints",
    "diffusion_models",
    "diffusers",
    "classifiers",
    "loras",
    "style_models",
    "gligen",
    "controlnet",
    "configs",
    "vae_approx",
    "vae",
    "text_encoders",
    "clip_vision",
    "upscale_models",
    "latent_upscale_models",
    "hypernetworks",
    "photomaker",
    "model_patches",
    "audio_encoders",
    "unet",  # legacy for diffusion_models
    "clip",  # legacy for text_encoders
}


class ComfyUICustomDirectories:
    """Stores custom directories of a given type per OS."""

    def __init__(
        self,
        directory_settings: dict[str, Any],
        os_profile_key: str | None = None,
    ):
        """Initialize custom directories for generating config."""
        self._directory_settings = directory_settings
        self._os = os_profile_key
        if os_profile_key is None or os_profile_key not in {
            "win",
            "lin",
            "osx",
        }:
            os_map = {"win32": "win", "linux": "lin", "darwin": "osx"}
            self._os = os_map.get(sys.platform)

        self._dir_profile_name: str = directory_settings["name"]
        self._dir_type: str = directory_settings["dir_type"]
        self._is_auto: bool = "auto" in self._dir_type
        self._is_nocheck: bool = "nocheck" in self._dir_type

        self._enabled: bool = directory_settings.get("is_enabled", True)

    @property
    def is_enabled(self) -> bool:
        """Return whether Custom Directories entry is enabled."""
        return self._enabled

    @property
    def dir_profile_name(self) -> str:
        """Return name of this folder profile subsection."""
        return self._dir_profile_name

    @property
    def dir_type(self) -> str:
        """Return type of this folder profile subsection."""
        return self._dir_type

    @property
    def is_auto(self) -> bool:
        """Return whether profile is auto."""
        return self._is_auto

    @property
    def is_auto_nocheck(self) -> bool:
        """Return whether profile is auto."""
        return self._is_auto and self._is_nocheck

    @property
    def auto_dirs(self) -> list[str]:
        """Return top level auto search dirs."""
        if not self._is_auto:
            return []
        return self._os_specific_directories

    @property
    @template_wrap
    def _os_specific_directories(self) -> list[str]:
        """Return directory list for current held OS state."""
        return [
            Path(directory).as_posix()
            for directory in self._directory_settings[f"dirs_{self._os}"]
        ]

    def _traverse_auto(self) -> dict[str, str]:
        """Returns a dictionary with valid subdirectories."""
        collect_dict = defaultdict(list)
        valid_dirs = [
            dir_
            for dir_ in self._os_specific_directories
            if Path(dir_).exists() and Path(dir_).is_dir()
        ]

        for directory in valid_dirs:
            valid_subdirs = {
                subdir.name: subdir.as_posix()
                for subdir in Path(directory).iterdir()
                if subdir.is_dir() and subdir.name in VALID_DIRS
            }
            [
                collect_dict[key].append(value)
                for key, value in valid_subdirs.items()
            ]
        return collect_dict

    def _traverse_auto_novalidcheck(self) -> dict[str, str]:
        """Returns a dictionary with any subdirectories.

        Doesn't matter if valid.
        """
        collect_dict = defaultdict(list)
        valid_dirs = [
            dir_
            for dir_ in self._os_specific_directories
            if Path(dir_).exists() and Path(dir_).is_dir()
        ]

        for directory in valid_dirs:
            valid_subdirs = {
                subdir.name: subdir.as_posix()
                for subdir in Path(directory).iterdir()
                if subdir.is_dir()
            }
            [
                collect_dict[key].append(value)
                for key, value in valid_subdirs.items()
            ]
        return collect_dict

    @property
    def as_dict(self) -> dict[str, list[str]]:
        """Returns contents as dictionary."""
        if self.is_auto_nocheck:
            return self._traverse_auto_novalidcheck()
        if self._is_auto:
            return self._traverse_auto()
        return {self._dir_type: self._os_specific_directories}

    @property
    def is_valid(self) -> bool:
        """Return true if all directories exist, and are direcories."""
        dirlist = []
        [dirlist.extend(dirs) for dirs in self.as_dict.values()]
        if not dirlist:
            return False
        return not any(
            not Path(dir_).exists() or not Path(dir_).is_dir()
            for dir_ in dirlist
        )

    @staticmethod
    def collect_as_dict(custom_dirs: list[ComfyUICustomDirectories]) -> dict:
        """Return dict with valid keys and paths gathered."""
        collect_dict = defaultdict(list)
        # Gather all
        for custom_dir in custom_dirs:
            [
                collect_dict[key].extend(value)
                for key, value in custom_dir.as_dict.items()
            ]
        return collect_dict

    @staticmethod
    def generate_yaml(custom_dirs: list[ComfyUICustomDirectories]) -> str:
        """Return indented yaml component for custom directory lists."""
        tab = " " * 4
        yaml: str = ""
        collect_dict = ComfyUICustomDirectories.collect_as_dict(
            custom_dirs=custom_dirs
        )

        # Construct yaml
        for key in collect_dict:
            entry = f"{tab}{key}: |\n"
            entry += (
                "\n".join(f"{tab * 2}{value}" for value in collect_dict[key])
                + "\n"
            )
            yaml += entry
        return yaml

    @staticmethod
    def diagnose_missing_dirs(
        custom_dirs: list[ComfyUICustomDirectories],
    ) -> list[str]:
        r"""Return list of directories that do not exist.

        Also reports if list is not 'valid', e.g. is file (extensionless)

        Formatted as:

        [dir profile name] | [folder type] :
        - [folder 1] does not exist / valid
        - [folder 2] does not exist / valid

        """
        diagnostics = []
        for custom_dir in custom_dirs:
            if not custom_dir.is_valid:
                if not custom_dir.is_auto:
                    diagnostics.append(
                        f"{custom_dir.dir_profile_name} |"
                        f" {custom_dir.dir_type} :"
                    )
                    non_valid = [
                        dir_
                        for dir_ in custom_dir.as_dict[custom_dir.dir_type]
                        if not Path(dir_).exists() or not Path(dir_).is_dir()
                    ]
                    diagnostics.extend(
                        [
                            f"- {dir_} does not exist / isn't valid."
                            for dir_ in non_valid
                        ]
                    )
                else:
                    diagnostics.append(
                        f"{custom_dir.dir_profile_name} |"
                        f" {custom_dir.dir_type} :"
                    )
                    auto_dirs = custom_dir.auto_dirs
                    non_valid_auto = [
                        dir_
                        for dir_ in auto_dirs
                        if not Path(dir_).exists() or not Path(dir_).is_dir()
                    ]
                    diagnostics.extend(
                        [
                            f"{custom_dir.dir_profile_name} | "
                            f"{non_valid} does not exist / isn't valid."
                            for non_valid in non_valid_auto
                        ]
                    )

                    for key, dirs in custom_dir.as_dict.items():
                        non_valid = [
                            dir_
                            for dir_ in dirs
                            if not Path(dir_).exists()
                            or not Path(dir_).is_dir()
                        ]
                        diagnostics.extend(
                            [
                                f"- {key} | {dir_} does not exist / "
                                "isn't valid."
                                for dir_ in non_valid
                            ]
                        )
        return diagnostics

    @staticmethod
    def create_default_customnodes_profile() -> ComfyUICustomDirectories:
        """Return Custom Directory entry with AYON comfyui plugin."""
        import ayon_comfyui as comfy_plugin

        comfy_plugin_path = (
            Path(comfy_plugin.__file__).parent / "_comfyui_plugin"
        )
        os_map = {"win32": "win", "linux": "lin", "darwin": "osx"}
        os_key = os_map.get(sys.platform)

        data = {
            "name": "AYON ComfyUI Default Plugin",
            "dir_type": "custom_nodes",
            "dirs_win": [],
            "dirs_lin": [],
            "dirs_osx": [],
        }

        data[f"dirs_{os_key}"] = [comfy_plugin_path]

        return ComfyUICustomDirectories(directory_settings=data)
