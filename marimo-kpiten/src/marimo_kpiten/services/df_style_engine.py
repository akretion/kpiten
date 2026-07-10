import polars as pl
import tomllib
from great_tables import GT, loc, style as STYLE
from typing import Any


class DFStyleEngine:
    # writen from services/
    # TODO find a way to implement Great Tables into exec_kpiten_line
    styles_path = "../styles/dataframes/"

    @staticmethod
    def general(df: pl.DataFrame):
        with open(f"{DFStyleEngine.styles_path}/general.style.toml", "rb") as cfg:
            config = tomllib.load(cfg)
            great_df = GT(df)
            print(f"BufferedReaser : {cfg}")
            print(f"CONFIG : {config}")
            for style_per_loc in config["STYLE"].items():
                d = DFStyleEngine._parse_style(style_per_loc)
                great_df = great_df.tab_style(
                    style=d["style"], locations=d["locations"]
                )
            return great_df

    @staticmethod
    def _parse_style(style_per_loc: tuple[str, dict[str, str]]):
        location = DFStyleEngine._loc_resolve(style_per_loc[0])
        style = []
        if "color" in style_per_loc[1]:
            style.append(STYLE.text(style_per_loc[1]["color"]))
        if "fill" in style_per_loc[1]:
            style.append(STYLE.fill(style_per_loc[1]["fill"]))
        return {"style": style, "locations": location}

    @staticmethod
    def _loc_resolve(str_loc: str):
        match str_loc:
            case "header":
                return loc.header()
            case "title":
                return loc.title()
            case "body":
                return loc.body()
            case "row_groups":
                return loc.row_groups()
            case _:
                raise UnknownGTLocation(
                    f"location {str_loc} is either misspelled or unknown."
                )


class UnknownGTLocation(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f"{self.message}."
