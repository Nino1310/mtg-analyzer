"""Win-rate distribution chart: one dot per card, grouped by mana value x color."""
import html
from typing import Dict, List, Optional, Sequence

import pandas as pd
from bokeh.models import ColumnDataSource, FixedTicker, HoverTool, Label, LabelSet, Range1d, Span
from bokeh.plotting import figure

COLOR_GROUP_ORDER = ["W", "U", "B", "R", "G", "Multicolor", "Colorless"]
CMC_BUCKETS = ["0", "1", "2", "3", "4", "5", "6+"]

PALETTE = {
    "W": "#8A6D00",
    "U": "#1B6FB0",
    "B": "#7A3E80",
    "R": "#C21E4A",
    "G": "#1E7A34",
    "Multicolor": "#B8590F",
    "Colorless": "#8C8C8C",
}

# Table row backgrounds: one per mono-color, plus a shared multicolor tint.
COLOR_BG = {
    "W": "#fdf6c9", "U": "#cfe8fb", "B": "#d8d8d8",
    "R": "#fbd2c9", "G": "#d3f0c9", "C": "#f0f0f0",
}
MULTICOLOR_BG = "#f0d97a"

# RdYlGn sampled at 11 stops, as (fraction, [r,g,b]); drives the GIH WR heatmap.
GRADIENT_STOPS = [
    [0.0, [165, 0, 38]], [0.1, [214, 47, 39]], [0.2, [244, 109, 67]],
    [0.3, [253, 173, 96]], [0.4, [254, 224, 139]], [0.5, [254, 255, 190]],
    [0.6, [217, 239, 139]], [0.7, [165, 216, 106]], [0.8, [102, 189, 99]],
    [0.9, [25, 151, 80]], [1.0, [0, 104, 55]],
]

ROW_CAP = 5
MAX_ROWS = 3
BIN_CAP = ROW_CAP * MAX_ROWS
LANE_WIDTH = 1.0
GROUP_GAP = 1.0
LANE_MARGIN = 0.05
CMC_GROUP_WIDTH = len(COLOR_GROUP_ORDER) * LANE_WIDTH
CMC_GROUP_STRIDE = CMC_GROUP_WIDTH + GROUP_GAP
MIN_BOX_HEIGHT = 2.0
AXIS_PAD = 3.0


def _color_group(colors: str) -> str:
    if colors == "C":
        return "Colorless"
    if len(colors) > 1:
        return "Multicolor"
    return colors


def _cmc_bucket(cmc: float) -> Optional[str]:
    if pd.isna(cmc):
        return None
    n = int(min(cmc, 6))
    return "6+" if cmc >= 6 else str(n)


def _slot_left(cmc_bucket: str, color_group: str) -> float:
    i = CMC_BUCKETS.index(cmc_bucket)
    j = COLOR_GROUP_ORDER.index(color_group)
    return i * CMC_GROUP_STRIDE + j * LANE_WIDTH


def _wavg(sub: pd.DataFrame) -> Optional[float]:
    if len(sub) == 0:
        return None
    return sub["gih_wr"].mean()


def compute_weighted_averages(
    df: pd.DataFrame, visible_color_groups: Sequence[str]
) -> Dict[str, object]:
    """Overall and per-color-group mean GIH win rate (one row per card copy)."""
    data = df.dropna(subset=["gih_wr"]).copy()
    if data.empty:
        return {"overall": None, "by_color": {}}
    data["color_group"] = data["colors"].map(_color_group)
    data = data[data["color_group"].isin(visible_color_groups)]
    if data.empty:
        return {"overall": None, "by_color": {}}
    overall = _wavg(data)
    by_color = {
        group: _wavg(sub) for group, sub in data.groupby("color_group")
    }
    return {"overall": overall, "by_color": by_color}


def build_winrate_dot_chart(
    df: pd.DataFrame,
    visible_color_groups: Sequence[str],
    images_by_name: Dict[str, str],
) -> Optional[figure]:
    data = df.dropna(subset=["gih_wr", "cmc"]).copy()
    if data.empty:
        return None

    data["color_group"] = data["colors"].map(_color_group)
    data = data[data["color_group"].isin(visible_color_groups)]
    if data.empty:
        return None

    data["cmc_bucket"] = data["cmc"].map(_cmc_bucket)
    data = data[data["cmc_bucket"].notna()]
    if data.empty:
        return None

    data["bin"] = data["gih_wr"].astype(int)
    data["idx_in_bin"] = data.groupby(["cmc_bucket", "color_group", "bin"]).cumcount()

    lane_stats = (
        data.groupby(["cmc_bucket", "color_group"])["gih_wr"]
        .agg(["min", "max"])
        .reset_index()
    )
    lanes_rows = []
    for _, row in lane_stats.iterrows():
        left = _slot_left(row["cmc_bucket"], row["color_group"])
        lo, hi = row["min"], row["max"]
        center = (lo + hi) / 2
        half = max((hi - lo) / 2, MIN_BOX_HEIGHT / 2)
        lanes_rows.append({
            "left": left + LANE_MARGIN,
            "right": left + LANE_WIDTH - LANE_MARGIN,
            "bottom": center - half,
            "top": center + half,
            "fill_color": PALETTE[row["color_group"]],
        })
    lanes_source = ColumnDataSource(pd.DataFrame(lanes_rows))

    avg_stats = (
        data.groupby(["cmc_bucket", "color_group"])["gih_wr"]
        .mean()
        .reset_index(name="avg")
    )
    avg_rows = []
    for _, row in avg_stats.iterrows():
        left = _slot_left(row["cmc_bucket"], row["color_group"])
        avg_rows.append({
            "x0": left + LANE_MARGIN, "x1": left + LANE_WIDTH - LANE_MARGIN,
            "y0": row["avg"], "y1": row["avg"],
        })
    avg_source = ColumnDataSource(pd.DataFrame(avg_rows))

    dots = data[data["idx_in_bin"] < BIN_CAP].copy()
    dots["row_in_bin"] = dots["idx_in_bin"] // ROW_CAP
    dots["col_in_bin"] = dots["idx_in_bin"] % ROW_CAP
    dots["slot_left"] = [
        _slot_left(b, g) for b, g in zip(dots["cmc_bucket"], dots["color_group"])
    ]
    dots["x"] = dots["slot_left"] + (dots["col_in_bin"] + 0.5) * (LANE_WIDTH / ROW_CAP)
    dots["y"] = dots["bin"] + (dots["row_in_bin"] + 0.5) / MAX_ROWS
    dots["image_url"] = dots["name"].map(images_by_name).fillna("")
    dots["name"] = dots["name"].map(lambda n: html.escape(str(n)))

    overflow_counts = data.groupby(["cmc_bucket", "color_group", "bin"]).size()
    overflow_rows = []
    for (cmc_bucket, color_group, bin_val), count in overflow_counts.items():
        if count > BIN_CAP:
            left = _slot_left(cmc_bucket, color_group)
            overflow_rows.append({
                "x": left + LANE_WIDTH / 2,
                "y": bin_val + 1.05,
                "label": f"+{count - BIN_CAP}",
            })

    y_min = max(0.0, data["gih_wr"].min() - AXIS_PAD)
    y_max = min(100.0, data["gih_wr"].max() + AXIS_PAD)

    p = figure(
        height=500,
        sizing_mode="stretch_width",
        tools="reset,save",
        toolbar_location="above",
        y_range=Range1d(y_min, y_max),
        x_range=Range1d(-GROUP_GAP / 2, len(CMC_BUCKETS) * CMC_GROUP_STRIDE - GROUP_GAP / 2),
    )
    p.xaxis.axis_label = "Mana value (CMC)"
    p.yaxis.axis_label = "GIH win rate (%)"
    p.xgrid.grid_line_color = None

    tick_positions = [i * CMC_GROUP_STRIDE + CMC_GROUP_WIDTH / 2 for i in range(len(CMC_BUCKETS))]
    p.xaxis.ticker = FixedTicker(ticks=tick_positions)
    p.xaxis.major_label_overrides = dict(zip(tick_positions, CMC_BUCKETS))

    p.quad(left="left", right="right", bottom="bottom", top="top",
           fill_alpha=0.15, line_color=None, fill_color="fill_color", source=lanes_source)

    p.segment(x0="x0", y0="y0", x1="x1", y1="y1", source=avg_source,
              line_color="#666666", line_dash="solid", line_width=2)

    averages = compute_weighted_averages(data, visible_color_groups)
    for group, avg in averages["by_color"].items():
        if avg is None:
            continue
        p.add_layout(Span(location=avg, dimension="width",
                          line_color=PALETTE[group], line_width=1.5, line_dash="dotted"))
    overall = averages["overall"]
    if overall is not None:
        p.add_layout(Span(location=overall, dimension="width",
                          line_color="#111111", line_width=3))
        p.add_layout(Label(
            x=5, y=overall, x_units="screen", y_offset=2,
            text=f"overall {overall:.1f}%", text_font_size="10px",
            text_font_style="bold", text_color="#111111",
            background_fill_color="#ffffff", background_fill_alpha=0.7,
        ))

    hover_renderers = []
    for group in COLOR_GROUP_ORDER:
        if group not in visible_color_groups:
            continue
        group_dots = dots[dots["color_group"] == group]
        if group_dots.empty:
            continue
        source = ColumnDataSource(group_dots[["x", "y", "image_url", "name", "gih_wr"]])
        renderer = p.circle(
            x="x", y="y", source=source, size=9,
            color=PALETTE[group], line_color="white", line_width=0.5,
            legend_label=group,
        )
        hover_renderers.append(renderer)

    if hover_renderers:
        hover = HoverTool(
            renderers=hover_renderers,
            tooltips="""
            <div style="max-width:220px; padding:6px;">
                <div style="font-weight:600; font-size:13px; margin-bottom:4px;">@name</div>
                <div style="font-size:12px; color:#444; margin-bottom:4px;">GIH WR: @gih_wr{0.0}%</div>
                <img src="@image_url" alt="@name"
                     style="width:150px; height:auto; display:block; border-radius:4px;"
                     onerror="this.style.display='none';">
            </div>
            """,
        )
        p.add_tools(hover)

    if overflow_rows:
        overflow_source = ColumnDataSource(pd.DataFrame(overflow_rows))
        p.add_layout(LabelSet(
            x="x", y="y", text="label", source=overflow_source,
            text_font_size="10px", text_align="center", text_baseline="middle",
        ))

    p.legend.location = "top_left"
    p.legend.orientation = "horizontal"
    p.legend.label_text_font_size = "9px"
    p.legend.background_fill_alpha = 0.7

    return p
