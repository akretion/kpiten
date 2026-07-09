import polars as pl
import polars.selectors as cs
import tomllib
from typing import Any


class TransformEngine:
    def __init__(self, df1_d: dict[str, Any], df2_d: dict[str, Any], path: str):
        """
        df1_data: {'model': 'name', 'df': pl.DataFrame}
        df2_data: {'model': 'name', 'df': pl.DataFrame}
        ruleset_path: an OS path pointing to a TOML file.
        """
        self.df1_data = df1_d
        self.df2_data = df2_d
        self.config: None | dict[str, Any] = None
        self.config_path = path
        with open(path, "rb") as toml_fp:
            self.config = tomllib.load(toml_fp)
        self._config_none_check()

    def run(self):
        self._ruleset_compat_check(self.config["META"])

        self._pre_union_operations()
        self._post_union_operations()

    def _pre_union_operations(self):
        self._run_filters()
        self._run_renames()

    def _post_union_operations(self):
        pass

    def _run_filters(self):
        try:  # there may be no filter at all defined on models
            idx = 0
            existing_model_filters = []
            if mod1 := self.config.get(self._snake_cased(self.df1_data["model"])):
                existing_model_filters.append(mod1)
            if mod2 := self.config.get(self._snake_cased(self.df2_data["model"])):
                existing_model_filters.append(mod2)

            for md in existing_model_filters:
                idx = idx + 1
                model_filtering = md["FILTERING"]
                print(f"model filtering : {model_filtering}")
                filter_rules = []
                for column_rule in model_filtering.items():
                    match column_rule[1]:
                        case "IS NOT NULL":
                            filter_rules.append(pl.col(column_rule[0]).is_not_null())
                            break
                        case "IS NULL":
                            filter_rules.append(pl.col(column_rule[0]).is_null())
                            break
                        case _:
                            # Nothing is done, to avoid tampering data
                            print(
                                f"[WARN TransformEngine on {self.df1_data["model"]}] unknown rule '{column_rule[1]}'"
                            )
                            break
                if idx == 1:
                    self.df1_data["df"] = self.df1_data["df"].filter(filter_rules)
                else:
                    self.df2_data["df"] = self.df2_data["df"].filter(filter_rules)

        except KeyError as KE:
            print(f"Silent KeyError : {KE}")

    def _run_renames(self):
        try:  # there may be no renames at all defined on models
            idx = 0
            existing_model_renames = []
            if mod1 := self.config.get(self._snake_cased(self.df1_data["model"])):
                existing_model_renames.append(mod1)
            if mod2 := self.config.get(self._snake_cased(self.df2_data["model"])):
                existing_model_renames.append(mod2)

            for md in existing_model_renames:
                idx = idx + 1
                model_renaming = md["RENAMING"]
                for renaming_rules in model_renaming.items():
                    column_name = renaming_rules[0]
                    for rule in renaming_rules[1].items():
                        _WHEN_NULL = None
                        _OTHERWISE = None
                        if rule[0] == "_WHEN_NULL":
                            _WHEN_NULL = rule[1]
                        elif rule[0] == "_OTHERWISE":
                            _OTHERWISE = rule[1]
                        when_value_name = rule[0]
                        then_value_name = rule[1]
                        if idx == 1:
                            self.df1_data["df"] = self.df1_data["df"].with_columns(
                                pl.when(pl.col(column_name) == when_value_name)
                                .then(pl.lit(then_value_name))
                                .when(pl.col(column_name).is_null())
                                .then(
                                    pl.lit(_WHEN_NULL)
                                    if _WHEN_NULL
                                    else pl.col(column_name)
                                )
                                .otherwise(  # TODO : integrate _OTHERWISE
                                    pl.lit(_OTHERWISE)
                                    if _OTHERWISE
                                    else pl.col(column_name)
                                )
                                .alias(column_name)
                            )
                        else:
                            self.df2_data["df"] = self.df2_data["df"].with_columns(
                                pl.when(pl.col(column_name) == when_value_name)
                                .then(pl.lit(then_value_name))
                                .when(pl.col(column_name).is_null())
                                .then(_WHEN_NULL or pl.col(column_name))
                                .otherwise(  # TODO : integrate _OTHERWISE
                                    _OTHERWISE or pl.col(column_name)
                                )
                                .alias(column_name)
                            )
        except KeyError as KE:
            print(f"Silent KeyError : {KE}")

    def _ruleset_compat_check(self, META_NODE) -> bool:
        if (self.df1_data["model"] not in META_NODE["models"]) or (
            self.df2_data["model"] not in META_NODE["models"]
        ):
            raise IncompatibleRulesetException(
                "One or more of the models passed as parameters"
                + "are incompatible with the given config"
            )

    def _config_none_check(self):
        if self.config == None:
            raise UnknownConfigLoadError(
                "Error could not be loaded. Pipeline interrupted."
            )

    def _snake_cased(self, model: str):
        return model.replace(".", "_")


class IncompatibleRulesetException(Exception):
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
        """


class UnknownConfigLoadError(Exception):
    """Raised if for an unknown reason, the config wasn't loaded without __init__
    crashing in the process.
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f"{self.message}."
