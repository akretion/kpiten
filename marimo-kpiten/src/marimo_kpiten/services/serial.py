import json
import tomllib

import tomli_w


def dumps(data) -> str:
    return tomli_w.dumps(data)


def loads(text: str):
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return json.loads(text)