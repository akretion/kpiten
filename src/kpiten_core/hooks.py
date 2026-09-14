"""Hook registry for client-specific tile logic.

Client projects register dataframe-prep hooks (per table) to keep the
generic lib free of business rules.
"""

from typing import Callable

_DF_HOOKS: dict[str, Callable] = {}


def register_df(table: str) -> Callable:
    """Decorator registering a dataframe prep hook for `table`."""

    def decorator(fn: Callable) -> Callable:
        _DF_HOOKS[table] = fn
        return fn

    return decorator


def apply_df(table: str, df, *args, **kwargs):
    """Apply the registered dataframe hook for `table`, else return `df`."""
    hook = _DF_HOOKS.get(table)
    return hook(df, *args, **kwargs) if hook else df
