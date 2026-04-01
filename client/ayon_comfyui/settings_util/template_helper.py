"""Helper functions for templating strings."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from ayon_api import get_folder_by_path, get_project, get_task_by_name
from ayon_core.lib import StringTemplate, get_ayon_username
from ayon_core.pipeline import (
    Anatomy,
    get_current_folder_path,
    get_current_host_name,
    get_current_project_name,
    get_current_task_name,
)
from ayon_core.pipeline.template_data import get_template_data
from ayon_core.settings import get_project_settings


def construct_template_data() -> dict[str, Any]:
    """Return this contexts' current template data."""
    project_name = get_current_project_name()
    project_entity = get_project(project_name)

    folder_path = get_current_folder_path()
    folder_entity = get_folder_by_path(project_name, folder_path)

    task_name = get_current_task_name()
    task_entity = get_task_by_name(
        project_name, folder_entity["id"], task_name
    )

    settings = get_project_settings(project_name=project_name)

    username = get_ayon_username()

    roots = Anatomy(
        project_name=project_name, project_entity=project_entity
    ).roots

    return (
        get_template_data(
            project_entity=project_entity,
            folder_entity=folder_entity,
            task_entity=task_entity,
            host_name=get_current_host_name(),
            settings=settings,
            username=username,
        )
        | roots
    )


def apply_template(template_strings: str | list[str]) -> list[str] | str:
    """Apply template to single or multiple strings at once.

    Returns:
        Templated strings as list or single string.
    """
    template_data = construct_template_data()
    if isinstance(template_strings, str):
        return str(StringTemplate(template_strings).format(template_data))

    return [
        str(StringTemplate(template).format(template_data))
        for template in template_strings
    ]


def template_wrap(func: Callable) -> Callable:
    """Wrapper that automatically formats function output.

    Returns:
        Callable with applied templated output.
    """

    @wraps(func)
    def inner(*args: list, **kwargs: dict) -> list[str] | str:
        """Return templated result if appliccable."""
        result = func(*args, **kwargs)
        if isinstance(result, str) or (
            isinstance(result, list)
            and all(isinstance(el, str) for el in result)
        ):
            return apply_template(result)
        return result

    return inner
