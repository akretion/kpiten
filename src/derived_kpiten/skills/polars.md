---
name: polars
---
# How to write the code : polars

The user reads your code : a comment above each transformation says what it does, and
the code may be shown step by step (one step per method, its comment as its words).

## The form

- Python, polars only : start from `d` (a LazyFrame of the table the user chose), end
  with `d_next = ...`. One chain of methods in parentheses is best ; a named table
  before it (`orders = d.filter(...)`) when a step is used twice.
- One method per line, and above each one a comment `# ...` that says what it does, in
  plain words, **in the language of the question** (a question in French gets comments
  in French).
- The result : sorted, at most 1000 rows, with readable names (`.alias("Untaxed")`).

Example :

```python
d_next = (
    d
    # keep the confirmed orders of 2025
    .filter((pl.col("state") == "sale") & (pl.col("date_order") >= pl.date(2025, 1, 1)))
    # the month of each order
    .with_columns(pl.col("date_order").dt.to_string("%Y-%m").alias("month"))
    # the total by salesperson and month
    .group_by("user_id", "month").agg(pl.col("amount_untaxed").sum().alias("untaxed"))
    # the best months first
    .sort("untaxed", descending=True)
    .head(20)
)
```

## What the code may use

- No import, def, lambda, loop, try or with ; no file ; no `map_elements` or `apply`.
- `pl.col`, `pl.lit`, `pl.when().then().otherwise()`, `pl.len()`, `pl.date(2025, 1, 1)`,
  `pl.concat`, and the methods of a frame (`filter`, `with_columns`, `select`, `join`,
  `group_by(...).agg(...)`, `sort`, `head`, `unique`, `rename`, `drop`...) and of an
  expression (`sum`, `mean`, `count`, `n_unique`, `alias`, `round`, `cast`, `is_in`,
  `over`, `dt.year`, `dt.month`, `dt.truncate("1mo")`, `dt.to_string("%Y-%m")`,
  `str.contains`...). It is `with_columns` and `select` (plural), never `with_column`.
- A month : `pl.col("date_order").dt.truncate("1mo")`, or `.dt.to_string("%Y-%m")` for a
  label (there is no `strftime`).

## The tables and the columns

- `d` is the table the user chose ; the other tables are `tables["sale.order.line"]`.
- A many2one column `x` holds the name of the record (`user_id` : `Marie Stourne`) and
  `x_` (with an underscore) its id : join on the ids,
  `.join(tables["sale.order.line"], left_on="id", right_on="order_id_")`.
- A column whose name has a dot is written as is : `pl.col("partner_id.country_id")`.
- Amounts may be decimals : `.cast(pl.Float64)` before a ratio.

## The traps

- Joining the lines to their order repeats the order on each of its lines : an amount of
  the order (`amount_untaxed`) summed after the join is counted several times. Sum the
  amounts of the lines (`price_subtotal`), or group the lines before joining.
- `how="left"` keeps the rows without a match (their columns are null) ; the default
  inner join leaves them out : say which one you want in the comment.
