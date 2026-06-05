import dotenv
import os

dotenv.load_dotenv()


class EnvReader:
    @staticmethod
    def get(env_var):
        return os.environ.get(env_var)
