import logging
import polars as pl
import tomllib
from great_tables import GT, loc, style as STYLE
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DFStyleEngine:
    # TODO find a way to implement Great Tables into exec_kpiten_line
    styles_path = Path(__file__).resolve().parents[2] / "styles" / "dataframes"

    @staticmethod
    def general(df: pl.DataFrame):
        with open(f"{DFStyleEngine.styles_path}/general.style.toml", "rb") as cfg:
            config = tomllib.load(cfg)
            great_df = GT(df)
            logger.debug("BufferedReaser : %s", cfg)
            logger.debug("CONFIG : %s", config)
            for loc_name, loc_config in config["STYLE"].items():
                d = DFStyleEngine._parse_style(loc_name, loc_config)
                great_df = great_df.tab_style(
                    style=d["style"], locations=d["locations"]
                )
        return great_df

    @staticmethod
    def _parse_style(loc_name: str, loc_config: dict[str, Any]):
        location = DFStyleEngine._loc_resolve(loc_name)
        props = loc_config["style"]
        style = []
        if "color" in props:
            style.append(STYLE.text(color=props["color"]))
        if "fill" in props:
            style.append(STYLE.fill(color=props["fill"]))
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
