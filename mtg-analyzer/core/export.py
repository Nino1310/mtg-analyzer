"""Standalone HTML report: a single self-contained file, viewable without a server.

The report freezes whatever the app is currently showing (filters, Not Played state,
selected color lanes) into a page anyone can open in a browser. Card images and the
Bokeh runtime are loaded from their CDNs, so the viewer needs to be online.
"""
import datetime as _dt
import html
import json
from typing import Dict, List, Optional

import pandas as pd
from bokeh.embed import components
from bokeh.resources import CDN

from .arena import arena_css, build_arena
from .chart import COLOR_BG, GRADIENT_STOPS, MULTICOLOR_BG, _color_group

TABLE_COLUMNS = [
    ("name", "Card"), ("set", "Set"), ("rarity", "Rarity"), ("colors", "Colors"),
    ("mana_cost", "Cost"), ("cmc", "MV"), ("type_line", "Type"),
    ("gih_wr", "GIH WR"), ("oh_wr", "OH WR"), ("gd_wr", "GD WR"),
    ("alsa", "ALSA"), ("ata", "ATA"), ("game_count", "Games"),
]
NUMERIC_COLUMNS = {"cmc", "gih_wr", "oh_wr", "gd_wr", "alsa", "ata", "game_count"}
AVERAGED_COLUMNS = ["cmc", "gih_wr", "oh_wr", "gd_wr", "alsa", "ata"]
INT_COLUMNS = {"game_count"}


def _gradient_rgb(value: float) -> str:
    """Interpolate GRADIENT_STOPS at value/100, mirroring the AgGrid cell style."""
    t = max(0.0, min(1.0, value / 100.0))
    lo, hi = GRADIENT_STOPS[0], GRADIENT_STOPS[-1]
    for a, b in zip(GRADIENT_STOPS, GRADIENT_STOPS[1:]):
        if a[0] <= t <= b[0]:
            lo, hi = a, b
            break
    span = (hi[0] - lo[0]) or 1
    f = (t - lo[0]) / span
    r, g, b = (round(lo[1][i] + f * (hi[1][i] - lo[1][i])) for i in range(3))
    return f"rgb({r},{g},{b})"


def _row_bg(colors: str) -> str:
    c = str(colors)
    if len(c) > 1 and c != "C":
        return MULTICOLOR_BG
    return COLOR_BG.get(c, "#ffffff")


def _fmt(col: str, value) -> str:
    if value is None or pd.isna(value):
        return ""
    if col in INT_COLUMNS:
        return f"{int(value)}"
    if col in NUMERIC_COLUMNS:
        return f"{float(value):g}" if col == "cmc" else f"{float(value):.1f}"
    return str(value)


def _cell(col: str, value) -> str:
    text = html.escape(_fmt(col, value))
    if col not in NUMERIC_COLUMNS:
        return f"<td>{text}</td>"
    raw = "" if pd.isna(value) else repr(float(value))
    style = ""
    if col == "gih_wr" and not pd.isna(value):
        style = f' style="background:{_gradient_rgb(float(value))}"'
    return f'<td class="num" data-v="{raw}"{style}>{text}</td>'


def _table_html(df: pd.DataFrame) -> str:
    heads = ['<th class="sortable" data-col="played">Played</th>']
    for col, label in TABLE_COLUMNS:
        cls = "sortable num" if col in NUMERIC_COLUMNS else "sortable"
        heads.append(f'<th class="{cls}" data-col="{col}">{html.escape(label)}</th>')

    rows = []
    for _, r in df.iterrows():
        played = bool(r["played"]) if "played" in df.columns else True
        cells = [f'<td class="num" data-v="{1 if played else 0}">{"✔" if played else "—"}</td>']
        cells += [_cell(col, r[col]) for col, _ in TABLE_COLUMNS if col in df.columns]
        cls = "" if played else ' class="np"'
        rows.append(f'<tr{cls} style="background:{_row_bg(r["colors"])}">{"".join(cells)}</tr>')

    foot_cells = ['<td class="num">Average</td>']
    for col, _ in TABLE_COLUMNS:
        avg_col = f' data-avg="{col}"' if col in AVERAGED_COLUMNS else ""
        cls = ' class="num"' if col in NUMERIC_COLUMNS else ""
        foot_cells.append(f"<td{cls}{avg_col}></td>")

    return (
        '<table id="cards"><thead><tr>' + "".join(heads) + "</tr></thead>"
        + '<tbody>' + "".join(rows) + "</tbody>"
        + '<tfoot><tr>' + "".join(foot_cells) + "</tr></tfoot></table>"
    )


def _tiles_html(averages: Dict[str, object], visible_groups: List[str]) -> str:
    by_color = averages.get("by_color") or {}
    tiles = [("Overall", averages.get("overall"))]
    tiles += [(g, by_color[g]) for g in visible_groups if g in by_color]
    cells = []
    for label, val in tiles:
        shown = f"{val:.1f}%" if val is not None else "—"
        cells.append(
            f'<div class="tile"><div class="tile-l">{html.escape(label)}</div>'
            f'<div class="tile-v">{shown}</div></div>'
        )
    return f'<div class="tiles">{"".join(cells)}</div>'


def _not_played_html(filtered: pd.DataFrame, visible_groups: List[str]) -> str:
    if filtered.empty or "played" not in filtered.columns:
        return ""
    rows = filtered[~filtered["played"]].copy()
    if rows.empty:
        return ""
    rows["color_group"] = rows["colors"].map(_color_group)
    rows = rows[rows["color_group"].isin(visible_groups)]
    if rows.empty:
        return ""
    items = [
        f"<li>{html.escape(str(r['name']))} — {_fmt('cmc', r['cmc'])} MV — "
        f"{html.escape(str(r['colors']))}</li>"
        for _, r in rows.iterrows()
    ]
    return (
        f'<h2>Not played ({len(rows)})</h2><ul class="np-list">{"".join(items)}</ul>'
    )


_PAGE_CSS = """
<style>
  :root{color-scheme:light;}
  body{margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",
       Roboto,sans-serif;background:#fff;color:#111;}
  h1{font-size:26px;margin:0 0 4px;}
  h2{font-size:19px;margin:28px 0 8px;}
  .meta{color:#666;font-size:13px;margin-bottom:18px;}
  .tiles{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0 20px;}
  .tile{border:1px solid #e2e2e2;border-radius:8px;padding:8px 14px;min-width:96px;}
  .tile-l{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#777;}
  .tile-v{font-size:21px;font-weight:600;}
  .controls{margin:8px 0;}
  .controls input{padding:6px 10px;border:1px solid #ccc;border-radius:6px;
       font-size:14px;width:260px;max-width:100%;}
  .controls .hint{color:#888;font-size:12px;margin-left:10px;}
  .table-wrap{overflow-x:auto;border:1px solid #e2e2e2;border-radius:8px;}
  table{border-collapse:collapse;width:100%;font-size:13px;}
  th,td{padding:5px 9px;border-bottom:1px solid #e7e7e7;text-align:left;
       white-space:nowrap;}
  th{position:sticky;top:0;background:#f4f4f4;font-weight:600;z-index:2;}
  th.sortable{cursor:pointer;user-select:none;}
  th.sortable:hover{background:#e9e9e9;}
  th.sorted-asc::after{content:" ▲";font-size:10px;}
  th.sorted-desc::after{content:" ▼";font-size:10px;}
  td.num,th.num{text-align:right;}
  tr.np{opacity:.45;}
  tfoot td{font-weight:700;background:#fafafa;border-top:2px solid #333;
       position:sticky;bottom:0;}
  .np-list{columns:3;font-size:13px;color:#555;}
  .arena{margin-top:8px;}
  footer{margin-top:32px;color:#999;font-size:12px;}
  @media (max-width:700px){.np-list{columns:1;}body{padding:14px;}}
</style>
"""

_PAGE_JS = """
<script>
(function () {
  var table = document.getElementById('cards');
  if (!table) return;
  var tbody = table.tBodies[0];
  var rows = Array.prototype.slice.call(tbody.rows);
  var avgCells = Array.prototype.slice.call(table.querySelectorAll('tfoot td[data-avg]'));
  var headers = Array.prototype.slice.call(table.tHead.rows[0].cells);
  var sortState = {col: -1, dir: 1};

  function visibleRows() {
    return rows.filter(function (r) { return r.style.display !== 'none'; });
  }

  function refreshAverages() {
    var shown = visibleRows();
    avgCells.forEach(function (cell) {
      var idx = headers.findIndex(function (h) { return h.dataset.col === cell.dataset.avg; });
      if (idx < 0) return;
      var sum = 0, n = 0;
      shown.forEach(function (r) {
        var v = parseFloat(r.cells[idx].dataset.v);
        if (!isNaN(v)) { sum += v; n += 1; }
      });
      cell.textContent = n ? (Math.round((sum / n) * 10) / 10).toFixed(1) : '';
    });
    var counter = document.getElementById('rowcount');
    if (counter) counter.textContent = shown.length + ' of ' + rows.length + ' row(s)';
  }

  headers.forEach(function (th, idx) {
    if (!th.classList.contains('sortable')) return;
    th.addEventListener('click', function () {
      sortState.dir = sortState.col === idx ? -sortState.dir : 1;
      sortState.col = idx;
      headers.forEach(function (h) { h.classList.remove('sorted-asc', 'sorted-desc'); });
      th.classList.add(sortState.dir === 1 ? 'sorted-asc' : 'sorted-desc');
      var numeric = th.classList.contains('num');
      rows.sort(function (a, b) {
        var x = a.cells[idx], y = b.cells[idx];
        if (numeric) {
          var nx = parseFloat(x.dataset.v), ny = parseFloat(y.dataset.v);
          if (isNaN(nx) && isNaN(ny)) return 0;
          if (isNaN(nx)) return 1;
          if (isNaN(ny)) return -1;
          return (nx - ny) * sortState.dir;
        }
        return x.textContent.localeCompare(y.textContent) * sortState.dir;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
    });
  });

  var search = document.getElementById('search');
  if (search) {
    search.addEventListener('input', function () {
      var q = search.value.toLowerCase();
      rows.forEach(function (r) {
        r.style.display = r.textContent.toLowerCase().indexOf(q) === -1 ? 'none' : '';
      });
      refreshAverages();
    });
  }

  refreshAverages();
})();
</script>
"""


def build_report_html(
    filtered: pd.DataFrame,
    working: pd.DataFrame,
    averages: Dict[str, object],
    visible_groups: List[str],
    images_by_name: Dict[str, str],
    chart=None,
    title: str = "MTG Card List Analyzer",
    meta: Optional[Dict[str, str]] = None,
) -> str:
    """Render the current view as one standalone HTML document."""
    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    meta_bits = [f"{html.escape(k)}: {html.escape(str(v))}" for k, v in (meta or {}).items() if v]
    meta_bits.append(f"generated {generated}")
    meta_line = " · ".join(meta_bits)

    chart_script, chart_div = ("", "")
    bokeh_head = ""
    if chart is not None:
        chart_script, chart_div = components(chart)
        bokeh_head = "\n".join(
            f'<script src="{u}" crossorigin="anonymous"></script>' for u in CDN.js_files
        )

    arena_body, _ = build_arena(working, visible_groups, images_by_name)
    arena_section = (
        f'<h2>Deck view</h2><div class="arena">{arena_body}</div>' if arena_body else ""
    )
    chart_section = (
        f'<h2>Win rate by mana value and color</h2>{chart_div}' if chart_div else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
{_PAGE_CSS}
{arena_css('.arena')}
{bokeh_head}
</head>
<body>
<h1>{html.escape(title)}</h1>
<div class="meta">{meta_line}</div>
{_tiles_html(averages, visible_groups)}
{chart_section}
<h2>Cards</h2>
<div class="controls">
  <input id="search" type="search" placeholder="Filter cards…" autocomplete="off">
  <span class="hint" id="rowcount"></span>
</div>
<div class="table-wrap">{_table_html(filtered)}</div>
{arena_section}
{_not_played_html(filtered, visible_groups)}
<footer>Static export — card images and chart library load from the internet.</footer>
{_PAGE_JS}
{chart_script}
</body>
</html>
"""
