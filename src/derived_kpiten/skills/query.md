---
name: query
---
# How to write the query : the result

The user wants the result : a table to look at, filter and sort. Write the query that
gives it, short and efficient.

## The form

- ONE query, in the SQL of polars : a single SELECT when it reads well, a few CTE
  (`WITH a AS (...)`) when a step needs a name. No comment is needed.
- Efficient : filter as early as possible, keep only the columns the result needs, group
  before a join when the join repeats rows. Polars runs it lazily and optimizes it :
  do not add what it does itself (no hints, no temporary tables).
- The final SELECT : sorted, at most 1000 rows, its columns named in double quotes **in
  the language of the question** (`AS "CA HT"`, `AS "Vendeur"` for a question in French).

Example :

```sql
SELECT user_id AS "Salesperson", strftime(date_order, '%Y-%m') AS "Month",
       SUM(amount_untaxed) AS "Untaxed"
FROM d
WHERE state IN ('sale', 'done') AND date_order >= '2025-01-01'
GROUP BY 1, 2
ORDER BY 3 DESC
LIMIT 20
```
