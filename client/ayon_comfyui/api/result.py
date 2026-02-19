"""Wrap up a function result neatly without throwing."""

from __future__ import annotations

from functools import partial, wraps
from inspect import isclass
from typing import TYPE_CHECKING, Any, Type

if TYPE_CHECKING:
    from collections.abc import Callable


class Result:
    """Exception container class."""

    def __init__(
        self,
        value: Any | BaseException | Type[BaseException],  # noqa: ANN401
    ) -> None:
        """Capture value and mark result as either ok or err."""
        self._is_err = False
        self._is_ok = False
        self._value = None

        if isclass(value) and issubclass(value, BaseException):
            self._is_err = True
            self._value = value()  # instance class
        elif isinstance(value, BaseException):
            self._is_err = True
            self._value = value
        else:
            self._is_ok = True
            self._value = value

    def unwrap(self) -> Any:  # noqa: ANN401
        """Returns value if is_ok, else raise error."""
        if self._is_err:
            raise self._value
        return self._value

    def unwrap_with_default(self, default: Any = None) -> Any:  # noqa: ANN401
        """Returns value if is_ok, else return default."""
        if self._is_err:
            return default
        return self._value

    @property
    def is_ok(self) -> bool:
        """Returns whether contained value is not an error."""
        return self._is_ok

    @property
    def is_err(self) -> bool:
        """Returns whether contained value is an error."""
        return self._is_err

    @property
    def error(self) -> BaseException | None:
        """Returns exception."""
        if self.is_err:
            return self._value
        return None

    @property
    def value(self) -> Any | None:  # noqa: ANN401
        """Returns exception."""
        if self.is_ok:
            return self._value
        return None


def capture_as_result(func: Callable) -> Callable[[], Result]:
    """Decorator for function as Result type."""  # noqa: DOC201

    @wraps(func)
    def _inner_function(*args: list, **kwargs: dict) -> Result:
        try:
            ret = func(*args, **kwargs)
            return Result(ret)
        except BaseException as e:  # noqa : BLE001
            return Result(e)

    return _inner_function


def safe_partial(
    func: Callable, *args: list, **kwargs: dict
) -> Callable[[], Result]:
    """Returns a functools.partial wrapped in capture as result."""

    @wraps(func)
    @capture_as_result
    def safe_func(*_args: list, **_kwargs: dict) -> Any:  # noqa : ANN401
        return func(*_args, **_kwargs)

    return partial(safe_func, *args, **kwargs)
