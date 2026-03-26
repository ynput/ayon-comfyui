"""Various utilities."""

from __future__ import annotations

import asyncio
import inspect
from functools import wraps
from typing import Any, Callable, Coroutine


# REALLY EVIL
def demangle_method(
    cls_or_instance: Any,  # noqa: ANN401
    function_name: str,
    *,
    use_mro: bool = False,
) -> Callable | None:
    """Return function object by name, demangled.

    Evil way to grab a method preceded by 2 underscores.

    Example:
    ```
    class A:
        def __func(self, arg):
            ...

    class A_A(A):
        def func(self, arg):
            return demangle_method(self,"__func")(self, arg)
    ```
    """
    # Assert if class
    try:
        issubclass(cls_or_instance, object)
    except TypeError:
        cls_or_instance = cls_or_instance.__class__

    bases: tuple = (
        cls_or_instance.__mro__ if use_mro else cls_or_instance.__bases__
    )

    for b_cls in bases:
        name = b_cls.__qualname__
        demangle = f"_{name}{function_name}"
        if demangle in dir(b_cls):
            func = getattr(b_cls, demangle)
            if callable(func):
                return func
            break
    return None


# PRETTY EVIL STILL
def cache_result(func: Callable) -> Callable:
    """Cache result of function to recall on reuse.

    A better version of the stateful lambda decorator. (@lambda _: _())

    Uses a generated class w/ unique name to store state,
    modifying the generated class defintion so state persists.

    Returns:
        Result on first use, cached state on second.
    """
    cls_dict = {"_cache": None, "_set": False}
    storage_t = type("cache_" + func.__qualname__, (), cls_dict)

    @wraps(func)
    def _cache_func(*args, **kwargs):  # noqa: ANN202, ANN002, ANN003
        if not storage_t._set:  # noqa: SLF001
            result = func(*args, **kwargs)
            storage_t._cache = result  # noqa: SLF001
            storage_t._set = True  # noqa: SLF001
            return result
        return storage_t._cache  # noqa: SLF001

    return _cache_func


# Not too evil.
def extract_default_kwargs(func: Callable) -> dict[str, Any]:
    """Returns a dict with default arguments to a function."""
    params = inspect.signature(func).parameters
    kwargs = {}
    for param in params.values():
        if param.default == inspect.Parameter.empty:
            continue
        kwargs[param.name] = param.default

    return kwargs


def syncify(coro: Coroutine) -> Callable:
    """Transform async function into a synchronous function.

    Returns:
        Blocking version of async function.
    """

    @wraps(coro)
    def _inner_(*args: list[Any], **kwargs: dict[str, Any]) -> Any:  # noqa: ANN401
        _loop_ = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop_)
        return _loop_.run_until_complete(coro(*args, **kwargs))

    return _inner_
