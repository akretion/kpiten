from marimo_kpiten.services.env_reader import EnvReader
from pathlib import Path

env_ = EnvReader()
data_path = "../generated"


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

    notebook_state_dir = "notebook_state"
    default_state_dir = "state"

    @staticmethod
    def store_state(
        data: dict[str, str],
        module_name: str = None,
        state_type: str = "notebook",
    ):
        # TODO : REFACTOR
        Path(f"{data_path}").mkdir(exist_ok=True)
        match state_type:
            case "notebook":
                Path(f"{data_path}").mkdir(exist_ok=True)
                Path(f"{data_path}/{FileState.notebook_state_dir}/").mkdir(
                    exist_ok=True
                )
                Path(f"{data_path}/{FileState.notebook_state_dir}/{module_name}").mkdir(
                    exist_ok=True
                )

                for key, d in data.items():
                    with open(
                        f"{data_path}/{FileState.notebook_state_dir}/{module_name}/{key}.txt",
                        "w+",
                    ) as data_file:
                        data_file.write(d)
            case "state":
                Path(f"{data_path}").mkdir(exist_ok=True)
                Path(f"{data_path}/{FileState.default_state_dir}/").mkdir(exist_ok=True)

                for key, d in data.items():
                    with open(
                        f"{data_path}/{FileState.default_state_dir}/{key}.txt",
                        "w+",
                    ) as data_file:
                        data_file.write(d)
                pass
            case _:
                pass

    # TODO : Make one retrieve_state function.
    @staticmethod
    def retrieve_notebook_state(module_name: str):
        try:
            notebook_state_files = Path(
                f"{data_path}/{FileState.notebook_state_dir}/{module_name}"
            ).iterdir()
            retrieved = {}

            for f in notebook_state_files:
                retrieved[f.name.strip(".txt")] = f.read_text()

            return retrieved
        except Exception:
            return None

    @staticmethod
    def retrieve_state(state: str):
        try:
            state_files = Path(f"{data_path}/{FileState.default_state_dir}").iterdir()
            for f in state_files:
                if f.name.strip(".txt") == state:
                    return f.read_text()
            return None
        except Exception:
            return None
