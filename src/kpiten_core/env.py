import os

import dotenv

dotenv.load_dotenv()


def get(env_var, default=None):
    return os.environ.get(env_var, default)


data_path = get("DATA_PATH", "data_dir")
decimal_truncate = int(get("DECIMAL_TRUNCATE", "5"))

# Odoo database the parquet scoping targets (set by the UI apps on db switch)
current_db = None
