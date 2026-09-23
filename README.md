# kpiten-perspective

A KpiTen plugin (pluggy hooks of `kpiten_core.hookspecs`) : a `data` tile whose
definition holds a line `-- perspective: {...}` (SQL) or `# perspective: {...}`
(polars) is drawn by [Perspective](https://perspective.finos.org) : the rows of the
tile (the ones the user may read) are a pivot the user groups, splits, filters and
charts in the browser. The json is the config of the viewer (`plugin`, `group_by`,
`split_by`, `columns`, `aggregates`, `sort`...).

Without this plugin, the same tile is an ordinary table.

    uv pip install -e src/kpiten-perspective   # in the venv the dashboards run in
