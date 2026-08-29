from typing import Any

from marimo_kpiten.services.file_state import FileState


def current_user_id():
    """Id of the user logged in the marimo session."""
    return FileState.retrieve_state("user_id")


def load_lines(config_model, table: str) -> list[dict[str, Any]]:
    """Return the kpiten.config.line records for a table."""
    lines = []
    for l_id in config_model.search(
        [("config_id", "=", config_model.get_conf_id(table))]
    ):
        line = config_model.browse(l_id)
        lines.append(
            {
                "id": l_id,
                "config_id": line.config_id.id,
                "content": line.definition,
                "name": line.name,
                "kind": line.kind,
            }
        )
    return lines


def create_line(
    config_model, model: str, definition: str, kind: str, name=None, user_id=None
) -> bool:
    return config_model.create_conf_line(
        model, definition, kind, name, user_id or current_user_id()
    )


def delete_line(config_model, line_id: int) -> None:
    config_model.browse(line_id).unlink()
