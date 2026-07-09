import polars as pl
import polars.selectors as cs
import tomllib

class TransformEngine:
    def __init__(self, df1_d: dict[str, Any], df2_d: dict[str, Any], path: str):
        """
        df1_data: {'model': 'name', 'df': pl.DataFrame}
        df2_data: {'model': 'name', 'df': pl.DataFrame}
        ruleset_path: an OS path pointing to a TOML file.
        """
        self.df1_data = df1_d
        self.df2_data = df2_d
        self.ruleset_path = path

    def run(self):
        config_dict = tomllib.load(path)
        if not self._is_ruleset_compatible():
            pass
            
    def _pre_union_operations(self):
        pass
    def _post_union_operations(self):
        pass
    
    def _is_ruleset_compatible(self)->bool:
        pass


class IncompatibleRuleset(Exception):
    """Raised when [META] section mismatches parameters
    given to TransformEngine.run"""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f"{self.message}.\n{self._tips()}"

    def _tips(self):
        return """
        Here are possible causes for this error :\n
        - the models in the [META] section doesn't match the parameters w/ which you initialized the class
        - the path is incorrect.
        - there is one model out of two that isn't in the parameters.
        """"