---
name: steps
---
# How to write the query : in steps

The user reads your query step by step : each step is run on their rows and shown with
its words, the rows before and after it, the columns it adds. Write it for that reader.

## The form

- ONE query, in the SQL of polars, as a chain of CTE : `WITH a AS (...), b AS (...)`,
  then a final `SELECT`.
- One CTE per operation : filter, compute a column, join, group, rank. Do not pack a
  filter, a join and a grouping in the same CTE.
- Above each CTE and above the final SELECT, a comment `-- Step n : ...` that says what the
  step does, in plain words (no SQL words in it), **in the language of the question** : a
  question in French gets comments in French (`-- Step 1 : garder les commandes
  confirmées`).
- CTE names in snake_case that say what the table holds : `confirmed_orders`,
  `by_salesperson`, never `t1`, `cte2`, `tmp`.
- The final SELECT : sorted, at most 1000 rows, its columns named in double quotes **in
  the language of the question** (`AS "CA HT"`, `AS "Vendeur"` for a question in French).

Example :

```sql
WITH
-- Step 1 : keep the confirmed orders
confirmed AS (SELECT * FROM d WHERE state IN ('sale', 'done')),
-- Step 2 : the month of each order
with_month AS (SELECT *, strftime(date_order, '%Y-%m') AS month FROM confirmed),
-- Step 3 : the total by salesperson and month
by_salesperson AS (
    SELECT user_id, month, SUM(amount_untaxed) AS untaxed
    FROM with_month
    GROUP BY user_id, month
)
-- Step 4 : the best months first
SELECT user_id AS "Salesperson", month AS "Month", untaxed AS "Untaxed"
FROM by_salesperson
ORDER BY untaxed DESC
LIMIT 20
```
