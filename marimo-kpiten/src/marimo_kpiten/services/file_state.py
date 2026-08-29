from pathlib import Path

from marimo_kpiten.common import DATA_PATH


class FileState:
    """
    By choice, data will be stored in simple files that bare the name of what they store
    e.g, currently selected table in build.py should be stored in build/table_name.txt, and the
    contents of build/table_name.txt would only be the selected table name.
    While it does multiply the amount of files created, it also diminishes rewrites,
    as the software won't have to rewrite an entire file to change one value that
    changes often.
    The next step could very well be to transition to SQLite databases
    """

    default_state_dir = "state"

    @staticmethod
    def store_state(data: dict[str, str]):
        Path(f"{DATA_PATH}/{FileState.default_state_dir}/").mkdir(
            parents=True, exist_ok=True
        )
        for key, d in data.items():
            with open(
                f"{DATA_PATH}/{FileState.default_state_dir}/{key}.txt",
                "w+",
            ) as data_file:
                data_file.write(d)

    @staticmethod
    def retrieve_state(state: str):
        try:
            state_files = Path(f"{DATA_PATH}/{FileState.default_state_dir}").iterdir()
            for f in state_files:
                if f.name.strip(".txt") == state:
                    return f.read_text()
            return None
        except Exception:
            return None