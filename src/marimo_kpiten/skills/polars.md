---
name: polars
description: How to write the polars code the sandbox accepts
---
## Writing the code
- Start from `d`, finish with `d_next = ...` ; one expression chain is best.
- It is `with_columns` and `select` (plural), never `with_column`. No lambda, no loop.
- Group by the column the user names ("by buyer" -> the buyer column, see the skills of the table) and say in the answer which column you used.
- Count rows : `d.group_by("state").agg(pl.len().alias("orders"))`
- Sum / mean : `pl.col("amount_untaxed").sum().alias("total")`, `.mean()`, `.max()`
- Filter : `d.filter(pl.col("state").is_in(["purchase", "done"]))` ; several conditions : `(a) & (b)`
- Top N : `.sort("total", descending=True).head(5)`
- By month : `d.group_by(pl.col("date_order").dt.truncate("1mo").alias("month"))` ; by year : `pl.col("date_order").dt.year().alias("year")`
- Distinct count : `pl.col("partner_id").n_unique()`
- Share of the total : `(pl.col("total") / pl.col("total").sum() * 100).round(1).alias("share_pct")`
- Round money to the unit : `.round(0)`
- Give the result readable column names with `.alias(...)`.

## Examples
Number of orders and total per state, biggest first :
d_next = d.group_by("state").agg(pl.len().alias("orders"), pl.col("amount_untaxed").sum().alias("total")).sort("total", descending=True)

Monthly total :
d_next = d.group_by(pl.col("date_order").dt.truncate("1mo").alias("month")).agg(pl.col("amount_untaxed").sum().alias("total")).sort("month")
