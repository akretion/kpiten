import dotenv
import os

dotenv.load_dotenv()


class EnvReader:
    def get(self, env_var):
        return os.environ.get(env_var)
