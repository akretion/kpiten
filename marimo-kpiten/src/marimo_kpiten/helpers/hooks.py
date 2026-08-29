"""Hook registry for client-specific KPI logic.

Client projects register dataframe-prep hooks (per table) and union builders
(per base model) to keep the generic lib free of business rules.
"""

from typing import Callable

_DF_HOOKS: dict[str, Callable] = {}
_UNION_HOOKS: dict[str, Callable] = {}


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


def register_union(model: str) -> Callable:
    """Decorator registering a union builder for a base `model`."""

    def decorator(fn: Callable) -> Callable:
        _UNION_HOOKS[model] = fn
        return fn

    return decorator


def apply_union(model: str):
    """Return the union builder registered for `model`, if any."""
    return _UNION_HOOKS.get(model)
