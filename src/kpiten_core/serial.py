import tomllib
from typing import Any

import tomli_w


def dumps(data: dict[str, Any]) -> str:
    """Serialize a kpi definition to TOML."""
    return tomli_w.dumps(data)


def loads(text: str) -> dict[str, Any]:
    """Load a kpi definition (TOML only)."""
    return tomllib.loads(text)


def validate(text: str) -> bool:
    """Raise tomllib.TOMLDecodeError if the definition is not valid TOML."""
    tomllib.loads(text)
    return True
