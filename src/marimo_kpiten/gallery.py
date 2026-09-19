"""What can be built as a KPI, drawn : small pictures under the choices of the explorer.

Each picture is a drawing (html and svg, no image file) of one kind of output or one way
to put a table in relief, with the choices it uses. The one the user picked is framed.
"""

import html

ACCENT = "#0a6ebd"
GOOD = "#00A04A"
HIGHLIGHT = "#ffe08a"
GRID = "#d8dee4"
WIDTH, HEIGHT = 190, 96


def _svg(body: str) -> str:
    return (
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">{body}</svg>'
    )


def card() -> str:
    return _svg(
        '<text x="12" y="20" font-size="11" fill="#57606a">Revenue</text>'
        '<text x="12" y="52" font-size="28" font-weight="700" fill="#24292f">345 054</text>'
        f'<text x="12" y="76" font-size="11" font-weight="600" fill="{GOOD}">'
        '▲ 12.3% <tspan fill="#57606a" font-weight="400">since last period</tspan></text>'
    )


def ranking() -> str:
    widths = [150, 118, 92, 60, 34]
    bars = "".join(
        f'<text x="4" y="{15 + i * 18}" font-size="9" fill="#57606a">{name}</text>'
        f'<rect x="34" y="{6 + i * 18}" width="{w}" height="11" rx="2" fill="{ACCENT}"/>'
        for i, (name, w) in enumerate(zip("ABCDE", widths))
    )
    return _svg(bars)


def trend() -> str:
    points = [(8, 70), (38, 52), (68, 60), (98, 34), (128, 42), (158, 20), (184, 26)]
    line = " ".join(f"{x},{y}" for x, y in points)
    area = f"{points[0][0]},88 {line} {points[-1][0]},88"
    return _svg(
        f'<line x1="6" y1="88" x2="186" y2="88" stroke="{GRID}"/>'
        f'<polygon points="{area}" fill="{ACCENT}" fill-opacity=".25"/>'
        f'<polyline points="{line}" fill="none" stroke="{ACCENT}" stroke-width="2"/>'
    )


def _grid(rows: list[list[str]], fills: dict, header: bool = True) -> str:
    """A small table drawn cell by cell ; `fills` maps (row, col) to a color."""
    cell_w, cell_h = 44, 17
    out = []
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            x, y = 4 + c * cell_w, 4 + r * cell_h
            fill = fills.get((r, c), "#f3f4f6" if header and r == 0 else "#ffffff")
            weight = 700 if (r, c) in fills or (header and r == 0) else 400
            align = "start" if c == 0 else "end"
            tx = x + 4 if c == 0 else x + cell_w - 4
            out.append(
                f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" fill="{fill}" '
                f'stroke="{GRID}"/><text x="{tx}" y="{y + 12}" font-size="9" '
                f'text-anchor="{align}" font-weight="{weight}" fill="#24292f">{html.escape(text)}</text>'
            )
    return "".join(out)


def table() -> str:
    rows = [
        ["Buyer", "Amount", "Share %"],
        ["Ann", "670", "67.0"],
        ["Bob", "300", "30.0"],
        ["Cid", "30", "3.0"],
    ]
    return _svg(_grid(rows, {(1, 1): HIGHLIGHT, (1, 2): HIGHLIGHT}))


def pivot() -> str:
    rows = [
        ["", "FR", "BR", "US"],
        ["Ann", "520", "150", "20"],
        ["Bob", "300", "80", "5"],
        ["Cid", "30", "0", "12"],
    ]
    heat = {
        (1, 1): "#f59f00",
        (1, 2): "#ffd980",
        (2, 1): "#f9bc4a",
        (2, 2): "#ffeebf",
        (1, 3): "#fff6dc",
    }
    return _svg(_grid(rows, heat))


def _relief(fills: dict) -> str:
    rows = [["", "Amount"], ["A", "500"], ["B", "300"], ["C", "150"], ["D", "50"]]
    return _svg(_grid(rows, fills))


# key -> (title, what it is, what to choose, the drawing)
OUTPUTS = {
    "card": (
        "Card",
        "One number, with its change since the previous period.",
        "measure, period",
        card,
    ),
    "ranking": (
        "Ranking",
        "The biggest groups first : the top N, with their share of the total.",
        "measure, group by, top N, share",
        ranking,
    ),
    "trend": (
        "Trend",
        "A measure per month, quarter or year.",
        "measure, date, grain",
        trend,
    ),
    "table": (
        "Table by group",
        "Every group, with its share and the cumulative share (Pareto).",
        "measure, group by, share, highlight",
        table,
    ),
    "pivot": (
        "Pivot table",
        "Two groupings crossed : rows and columns.",
        "measure, group by, pivot columns, highlight",
        pivot,
    ),
}
RELIEF = {
    "share": ("Share of the total ≥ X %", {(1, 1): HIGHLIGHT, (2, 1): HIGHLIGHT}),
    "top": ("The X largest", {(1, 1): HIGHLIGHT, (2, 1): HIGHLIGHT, (3, 1): HIGHLIGHT}),
    "above_average": ("Above the average", {(1, 1): HIGHLIGHT, (2, 1): HIGHLIGHT}),
    "heatmap": (
        "Heat map",
        {(1, 1): "#f59f00", (2, 1): "#f9bc4a", (3, 1): "#ffeebf", (4, 1): "#fff9e6"},
    ),
}


def _tile(title: str, note: str, uses: str, picture: str, selected: bool) -> str:
    border = f"2px solid {ACCENT}" if selected else "1px solid #d8dee4"
    tag = (
        f'<span style="float:right;font-size:11px;color:{ACCENT};font-weight:600">chosen</span>'
        if selected
        else ""
    )
    return (
        f'<div style="width:{WIDTH + 24}px;padding:8px 10px;border:{border};'
        'border-radius:8px;background:#fff">'
        f'<div style="font-weight:600;margin-bottom:4px">{html.escape(title)}{tag}</div>'
        f"{picture}"
        f'<div style="font-size:12px;color:#24292f;margin-top:4px">{html.escape(note)}</div>'
        f'<div style="font-size:11px;color:#57606a;margin-top:2px">Uses : {html.escape(uses)}</div>'
        "</div>"
    )


def gallery(selected_output: str = "", selected_relief: str = "") -> str:
    """The pictures of what the choices above can build, the chosen ones framed."""
    outputs = "".join(
        _tile(title, note, uses, draw(), key == selected_output)
        for key, (title, note, uses, draw) in OUTPUTS.items()
    )
    relief = "".join(
        _tile(title, "", "highlight", _relief(fills), key == selected_relief)
        for key, (title, fills) in RELIEF.items()
    )
    wrap = "display:flex;flex-wrap:wrap;gap:12px;margin:6px 0 14px 0"
    head = "font-weight:600;margin-top:10px"
    return (
        f'<div style="{head}">What you can build</div><div style="{wrap}">{outputs}</div>'
        f'<div style="{head}">Put a table in relief (Great Tables)</div>'
        f'<div style="{wrap}">{relief}</div>'
    )
