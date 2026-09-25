"""What an AI model is told of a table : summed up, and with pseudonyms.

The model gets the columns, figures on them (range, mean, period, most frequent
values) and a few rows, with the people and the products renamed : `Customer 12`,
`Salesperson 2`, `Product 4`, `Category 3`, `contact7@example.com`. Phones, streets,
VAT numbers, tokens and free text are not sent. Countries, teams, currencies, dates
and amounts stay : they make the sense of an analysis.

The pseudonyms stay on the server, stable for the life of an `Anonymizer` (a
session) : `reveal` puts the real values back in what the model answers (its text,
its code, which then runs on the real rows), `hide` takes them out of what is sent
(the question, an error, the code of a KPI to refine).

The levels, set per database in `kt.config` :
- `schema`  : the name and type of the columns, nothing else ;
- `summary` : figures and a few rows, with pseudonyms (the default) ;
- `clear`   : the same without pseudonyms (a local model, nothing leaves the machine).
"""

import re

import polars as pl

from . import env
from .store import DFStorage

LEVELS = ("schema", "summary", "clear")
SCAN_ROWS = 200_000  # rows looked at for the figures
SAMPLE_ROWS = 10  # rows sent
MAX_VALUES = 12  # a text column with more values is not listed
TOP_VALUES = 5  # most frequent values shown of a column with many
VALUE_CHARS = 40
MAX_KNOWN = 50_000  # values learnt per column to hide them from a text

# kinds of columns
KEEP = "keep"  # sent as is (numbers, dates, states, teams, countries...)
TEXT = "text"  # a free text : its values only when it has few
DROP = "drop"  # never sent (phone, street, token, html...)
ID = "id"  # database ids : type only
EMAIL = "email"
CATEGORY = "category"  # `All / Saleable / Office Furniture`, renamed piece by piece

DROP_TYPES = {"text", "html", "json", "binary"}
SECRET = re.compile(
    r"^(phone|mobile|street2?|zip|vat|iban|acc_number|bank_account\w*|ref|partner_ref"
    r"|client_order_ref|signed_by|signature|password|\w*token\w*)$"
)
EMAIL_NAME = re.compile(r"^\w*email\w*$")
PRODUCT_MODELS = ("product.product", "product.template")


def _people(table: str) -> tuple[str, str]:
    """The words for the partners and the users of a table."""
    if table.startswith("purchase."):
        return "Supplier", "Buyer"
    if table.startswith(("sale.", "crm.", "pos.")):
        return "Customer", "Salesperson"
    return "Partner", "User"


class Anonymizer:
    """The pseudonyms of one table for one session. With `hide=False` (the `clear`
    level) the values are sent as they are ; secrets and free text are still left out.
    """

    def __init__(
        self,
        table: str = "",
        fields: dict | None = None,
        hide: bool = True,
        shared: "Anonymizer | None" = None,
    ):
        """`shared` : another table of the same conversation (a panel), whose
        pseudonyms this one uses and extends : `Customer 12` is the same customer in
        every table."""
        self.table = table
        self.fields = fields or {}
        self.hide_values = hide
        partner, user = _people(table)
        self.prefixes = {
            "res.partner": partner,
            "res.users": user,
            **{model: "Product" for model in PRODUCT_MODELS},
        }
        # (prefix, real) -> pseudonym ; pseudonym -> real ; pseudonyms per prefix
        self._pseudo: dict[tuple[str, str], str] = shared._pseudo if shared else {}
        self._real: dict[str, str] = shared._real if shared else {}
        self._counts: dict[str, int] = shared._counts if shared else {}
        self._hide_re = None  # built again when values were learnt
        self._hide_size = 0

    # ---- the kind of a column
    def kind(self, column: str, dtype) -> str:
        """KEEP, TEXT, DROP, ID, EMAIL, CATEGORY, or the prefix of its pseudonyms."""
        if column == "id":
            return ID
        base, _, rest = column.partition(".")
        last = column.rsplit(".", 1)[-1]
        if SECRET.match(last):
            return DROP
        if EMAIL_NAME.match(last):
            return EMAIL
        is_int = dtype.is_integer()
        if base.endswith("_") and base[:-1] in self.fields and is_int:
            return ID  # `partner_id_` : the id of `partner_id`
        if rest:  # a path through a many2one : `product_id.categ_id.complete_name`
            if is_int and (last.endswith("_id") or last == "id"):
                return ID
            if dtype == pl.String:
                if "categ_id" in column:
                    return CATEGORY
                if last == "default_code":
                    return "Ref"
                return TEXT
            return KEEP
        field = self.fields.get(column)
        if not field:  # a column computed by kpiten (amounts in the company currency)
            return TEXT if dtype == pl.String else KEEP
        ftype = field.get("type")
        if ftype in DROP_TYPES:
            return DROP
        if ftype == "many2one":
            rel = field.get("rel")
            if rel == "product.category":
                return CATEGORY
            return self.prefixes.get(rel, KEEP)
        if dtype == pl.String and ftype not in ("selection",):
            return TEXT
        return KEEP

    def kinds(self, schema) -> dict[str, str]:
        return {c: self.kind(c, t) for c, t in schema.items()}

    @staticmethod
    def renamed(kind: str) -> bool:
        return kind not in (KEEP, TEXT, DROP, ID)

    # ---- pseudonyms
    def pseudonym(self, prefix: str, value: str) -> str:
        key = (prefix, value)
        if key not in self._pseudo:
            n = self._counts[prefix] = self._counts.get(prefix, 0) + 1
            name = f"contact{n}@example.com" if prefix == EMAIL else f"{prefix} {n}"
            self._pseudo[key] = name
            self._real[name] = value
        return self._pseudo[key]

    def hide_value(self, kind: str, value):
        """What the model sees of a value of a column of this kind."""
        if value is None or not self.hide_values or not self.renamed(kind):
            return value
        value = str(value)
        if kind == CATEGORY:
            return " / ".join(
                self.pseudonym("Category", part.strip()) for part in value.split(" / ")
            )
        return self.pseudonym(kind, value)

    def learn(self, frame: pl.LazyFrame, kinds: dict[str, str]) -> None:
        """Give a pseudonym to every value of the renamed columns, the most frequent
        first : a name the user types, or that an error quotes, is then hidden too."""
        if not self.hide_values:
            return
        for column, kind in kinds.items():
            if not self.renamed(kind):
                continue
            values = (
                frame.select(pl.col(column).cast(pl.String))
                .head(SCAN_ROWS)
                .drop_nulls()
                .group_by(column)
                .len()
                .sort(["len", column], descending=[True, False])
                .head(MAX_KNOWN)
                .collect()[column]
            )
            for value in values:
                self.hide_value(kind, value)

    def hide(self, text: str) -> str:
        """The text with the real values the session knows replaced by their pseudonyms."""
        if not self.hide_values or not self._pseudo or not text:
            return text
        if self._hide_re is None or self._hide_size != len(self._pseudo):
            self._hide_size = len(self._pseudo)
            reals = sorted(
                {real for (_p, real) in self._pseudo if len(real) >= 3},
                key=len,
                reverse=True,
            )
            if not reals:
                return text
            self._by_real = {
                real: pseudo for (_p, real), pseudo in self._pseudo.items()
            }
            self._hide_re = re.compile(
                r"(?<!\w)(" + "|".join(re.escape(r) for r in reals) + r")(?!\w)"
            )
        return self._hide_re.sub(lambda m: self._by_real[m.group(1)], text)

    def reveal(self, text: str | None) -> str | None:
        """The text with the pseudonyms replaced by the real values."""
        if not text or not self._real:
            return text
        prefixes = sorted({p for (p, _r) in self._pseudo if p != EMAIL}, key=len)
        pattern = r"\bcontact\d+@example\.com\b"
        if prefixes:
            pattern += r"|\b(?:" + "|".join(map(re.escape, prefixes)) + r") \d+\b"
        return re.sub(pattern, lambda m: self._real.get(m.group(0), m.group(0)), text)

    def hide_frame(self, df: pl.DataFrame, kinds: dict[str, str]) -> pl.DataFrame:
        """The rows as the model sees them : renamed, secrets and ids left out."""
        columns = [c for c in df.columns if kinds.get(c) not in (DROP, ID)]
        return df.select(
            [
                (
                    pl.Series(
                        c,
                        [self.hide_value(kinds[c], v) for v in df[c].to_list()],
                        dtype=pl.String,
                    )
                    if self.renamed(kinds[c]) and self.hide_values
                    else df[c]
                )
                for c in columns
            ]
        )


def for_table(
    backend, table: str, hide: bool = True, shared: Anonymizer | None = None
) -> Anonymizer:
    """The anonymizer of a table of the store of `backend`'s database (the fields
    metadata the sync wrote : type and related model of each field) ; `shared` : the
    one of another table of the same conversation, whose pseudonyms it shares."""
    with env.db_scope(backend.db):
        meta = DFStorage.read_meta(table)
    fields = {k: v for k, v in meta.items() if isinstance(v, dict) and "type" in v}
    return Anonymizer(table, fields, hide, shared)


def _number(value) -> str:
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def _short(value) -> str:
    text = str(value)
    return text if len(text) <= VALUE_CHARS else text[: VALUE_CHARS - 1] + "…"


def summary(
    frame: pl.LazyFrame,
    anon: Anonymizer,
    level: str = "summary",
    sample_rows: int = SAMPLE_ROWS,
) -> str:
    """What the model is told of the table, for a level of `LEVELS` ; `sample_rows` :
    the rows shown (0 : none, the columns and their values only)."""
    schema = frame.collect_schema()
    if level not in ("summary", "clear"):
        return "\n".join(f"- {c} : {t}" for c, t in schema.items())
    kinds = anon.kinds(schema)
    anon.learn(frame, kinds)
    head = frame.head(SCAN_ROWS)
    sent = [c for c in schema if kinds[c] not in (DROP, ID)]
    numbers = [c for c in sent if schema[c].is_numeric()]
    dates = [c for c in sent if schema[c].is_temporal()]
    texts = [c for c in sent if schema[c] == pl.String]
    stats = head.select(
        [pl.len().alias("rows")]
        + [pl.col(c).drop_nulls().n_unique().alias(f"n:{c}") for c in texts]
        + [pl.col(c).min().alias(f"min:{c}") for c in numbers + dates]
        + [pl.col(c).max().alias(f"max:{c}") for c in numbers + dates]
        + [pl.col(c).cast(pl.Float64).mean().alias(f"mean:{c}") for c in numbers]
    ).collect()
    stat = stats.row(0, named=True)

    def top(column, n):
        values = (
            head.select(pl.col(column))
            .drop_nulls()
            .group_by(column)
            .len()
            .sort(["len", column], descending=[True, False])
            .head(n)
            .collect()[column]
        )
        return [_short(anon.hide_value(kinds[column], v)) for v in values]

    lines = []
    few = set()
    for column, dtype in schema.items():
        kind = kinds[column]
        line = f"- {column} : {dtype}"
        if kind == DROP:
            line += " ; not sent"
        elif kind == ID:
            line += " ; ids"
        elif column in numbers and stat[f"min:{column}"] is not None:
            line += (
                f" ; from {_number(stat[f'min:{column}'])}"
                f" to {_number(stat[f'max:{column}'])},"
                f" mean {stat[f'mean:{column}']:.4g}"
            )
        elif column in dates and stat[f"min:{column}"] is not None:
            line += f" ; from {stat[f'min:{column}']} to {stat[f'max:{column}']}"
        elif column in texts:
            n = stat[f"n:{column}"]
            if 0 < n <= MAX_VALUES:
                few.add(column)
                values = sorted(top(column, MAX_VALUES))
                line += " ; values : " + ", ".join(repr(v) for v in values)
            elif n and kind != TEXT:
                line += f" ; {n} values, the most frequent : " + ", ".join(
                    repr(v) for v in top(column, TOP_VALUES)
                )
            elif n:
                line += f" ; {n} values, not sent"
        lines.append(line)
    rows = [
        c
        for c in sent
        if c not in texts or c in few or kinds[c] != TEXT  # no free text
    ]
    sample = head.select(rows).head(sample_rows).collect()
    sample = anon.hide_frame(sample.with_columns(pl.col(pl.Float64).round(2)), kinds)
    sample = sample.select(
        [c for c in sample.columns if sample[c].null_count() < sample.height]
    )
    text = f"{stat['rows']} rows (the first {SCAN_ROWS} looked at).\n" + "\n".join(
        lines
    )
    if sample.width:
        text += f"\n\nA few rows (csv) :\n{sample.write_csv()}"
    if anon.hide_values and any(anon.renamed(k) for k in kinds.values()):
        text += (
            "\nThe people, products and categories are pseudonyms (`Customer 12`, "
            "`Product 4`, `contact3@example.com`). Write them as they are in the code : "
            "they are replaced by the real values before it runs."
        )
    return text
