---
name: sql
---
# The SQL of the query

## The tables and the columns

- `d` is the table the user chose. The other tables are named in double quotes :
  `"sale.order.line"`. Read no other table, no file.
- A column whose name has a dot is written in double quotes : `"partner_id.country_id"`.
- A many2one column `x` holds the name of the record (`user_id` : `Marie Stourne`) and
  `x_` (with an underscore) its id : join on the ids, `l.order_id_ = o.id`.
- Amounts may be decimals : `CAST(x AS DOUBLE)` before a ratio.

## The SQL of polars (not Postgres)

- Works : WHERE, GROUP BY, HAVING, JOIN (INNER, LEFT), UNION ALL, CASE WHEN, COALESCE,
  NULLIF, ROUND, COUNT(DISTINCT x), `SUM(x) FILTER (WHERE ...)`, subqueries, window
  functions (`ROW_NUMBER()`, `RANK()`, `LAG(x)`, `SUM(x) OVER (PARTITION BY ... ORDER BY
  ...)`), QUALIFY, EXTRACT(YEAR FROM d), ILIKE.
- A month : `strftime(date_order, '%Y-%m')` (there is no DATE_TRUNC).
- Days between two dates : `CAST(b AS INTEGER) - CAST(a AS INTEGER)` (no DATE_DIFF, no
  EXTRACT on a duration).
- No CURRENT_DATE, no INTERVAL : write the dates, `date_order >= '2025-01-01'`, from the
  date of today given below.

## The traps

- Joining the lines to their order repeats the order on each of its lines : an amount of
  the order (`amount_untaxed`) summed after the join is counted several times. Sum the
  amounts of the lines (`price_subtotal`), or group the lines before joining.
- A LEFT JOIN keeps the rows without a match (their columns are NULL) ; an INNER JOIN
  leaves them out : say which one you want in the comment.
