"""Streamlit app: paste/upload a decklist, view an enriched, color-coded, filterable table."""
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from st_aggrid import AgGrid, DataReturnMode, GridOptionsBuilder, GridUpdateMode, JsCode

from core.arena import ARENA_STYLE, build_arena
from core.chart import (
    COLOR_BG,
    COLOR_GROUP_ORDER,
    GRADIENT_STOPS,
    MULTICOLOR_BG,
    _color_group,
    build_winrate_dot_chart,
    compute_weighted_averages,
)
from core.export import build_report_html
from core.merge import build_dataframe, explode_copies
from core.parser import parse_decklist
from core.scryfall import fetch_cards
from core.seventeenlands import get_ratings_for_sets

st.set_page_config(page_title="MTG Card List Analyzer", layout="wide")

st.session_state.setdefault("not_played", set())
st.session_state.setdefault("grid_version", 0)


def _bump_version():
    st.session_state["grid_version"] += 1


def _set_not_played(uid: int, value: bool):
    npset = st.session_state["not_played"]
    if value:
        npset.add(uid)
    else:
        npset.discard(uid)
    _bump_version()


@st.cache_data(ttl=3600, show_spinner="Fetching card data...")
def run_pipeline(text: str, format: str, set_override: str):
    entries = parse_decklist(text)
    if not entries:
        return None, [], {}

    cards_by_key, not_found = fetch_cards(entries)
    distinct_sets = sorted({
        (set_override or card.set).upper() for card in cards_by_key.values()
    })
    ratings_by_set, _ = get_ratings_for_sets(distinct_sets, format=format)
    df = build_dataframe(entries, cards_by_key, ratings_by_set, set_override=set_override or None)
    images_by_name = {card.name: card.image_uri for card in cards_by_key.values() if card.image_uri}
    return df, not_found, images_by_name


AVERAGED_COLUMNS = ["cmc", "gih_wr", "oh_wr", "gd_wr", "alsa", "ata"]


def _row_style_js() -> str:
    return f"""
    function(params) {{
        if (params.node.rowPinned) {{
            return {{fontWeight: 'bold', borderTop: '2px solid #333'}};
        }}
        const COLOR_BG = {json.dumps(COLOR_BG)};
        const MULTICOLOR_BG = {json.dumps(MULTICOLOR_BG)};
        const c = params.data ? params.data.colors : null;
        if (!c) return {{}};
        const bg = (c.length > 1 && c !== 'C') ? MULTICOLOR_BG : (COLOR_BG[c] || '#ffffff');
        return {{backgroundColor: bg}};
    }}
    """


def _update_pinned_average_js() -> str:
    cols = json.dumps(AVERAGED_COLUMNS)
    return f"""
    function(params) {{
        const cols = {cols};
        const sums = {{}}, weights = {{}};
        cols.forEach(c => {{ sums[c] = 0; weights[c] = 0; }});
        let totalCount = 0;
        params.api.forEachNodeAfterFilter(function(node) {{
            const d = node.data;
            if (!d) return;
            totalCount += 1;
            cols.forEach(function(col) {{
                const v = d[col];
                if (v !== null && v !== undefined && !isNaN(v)) {{
                    sums[col] += v;
                    weights[col] += 1;
                }}
            }});
        }});
        const avgRow = {{name: 'Average', played: null}};
        cols.forEach(function(col) {{
            avgRow[col] = weights[col] > 0 ? Math.round((sums[col] / weights[col]) * 10) / 10 : null;
        }});
        params.api.setPinnedBottomRowData(totalCount > 0 ? [avgRow] : []);
    }}
    """


def _gih_wr_cellstyle_js() -> str:
    return f"""
    function(params) {{
        const stops = {json.dumps(GRADIENT_STOPS)};
        const v = params.value;
        if (v === null || v === undefined || isNaN(v)) return {{}};
        const t = Math.max(0, Math.min(1, v / 100));
        let lo = stops[0], hi = stops[stops.length-1];
        for (let i = 0; i < stops.length - 1; i++) {{
            if (t >= stops[i][0] && t <= stops[i+1][0]) {{ lo = stops[i]; hi = stops[i+1]; break; }}
        }}
        const f = (t - lo[0]) / ((hi[0] - lo[0]) || 1);
        const r = Math.round(lo[1][0] + f*(hi[1][0]-lo[1][0]));
        const g = Math.round(lo[1][1] + f*(hi[1][1]-lo[1][1]));
        const b = Math.round(lo[1][2] + f*(hi[1][2]-lo[1][2]));
        return {{backgroundColor: `rgb(${{r}},${{g}},${{b}})`}};
    }}
    """


def build_grid_options(df: pd.DataFrame) -> dict:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(resizable=True, sortable=True, filter=True, floatingFilter=True)
    gb.configure_column(
        "played", header_name="Played", editable=True,
        cellRenderer="agCheckboxCellRenderer", cellEditor="agCheckboxCellEditor",
        filter="agSetColumnFilter", width=90, pinned="left",
    )
    gb.configure_column("uid", hide=True)
    gb.configure_column("colors", filter="agSetColumnFilter")
    gb.configure_column("rarity", filter="agSetColumnFilter")
    gb.configure_column("cmc", filter="agNumberColumnFilter")
    gb.configure_column("gih_wr", filter="agNumberColumnFilter", cellStyle=JsCode(_gih_wr_cellstyle_js()))
    gb.configure_column("game_count", filter="agNumberColumnFilter")
    update_pinned_average = JsCode(_update_pinned_average_js())
    gb.configure_grid_options(
        getRowStyle=JsCode(_row_style_js()),
        autoSizeStrategy={"type": "fitGridWidth"},
        singleClickEdit=True,
        onGridReady=update_pinned_average,
        onFilterChanged=update_pinned_average,
    )
    return gb.build()


def render_arena(working, filtered, visible_groups, images_by_name, all_uids):
    st.subheader("Deck view")
    st.caption("Hover a card to see it full-size. Toggle Not Played via the **Played** "
               "checkbox in the table above, or the list below.")

    b1, b2, _ = st.columns([1, 1, 4])
    if b1.button("Mark all played"):
        st.session_state["not_played"] = set()
        _bump_version()
        st.rerun()
    if b2.button("Mark all Not Played"):
        st.session_state["not_played"] = set(all_uids)
        _bump_version()
        st.rerun()

    body, content_h = build_arena(working, visible_groups, images_by_name)
    if body:
        iframe_h = min(max(content_h, 260), 900)
        components.html(ARENA_STYLE + body, height=iframe_h, scrolling=True)
    else:
        st.info("No played cards in the selected colors.")

    if not filtered.empty:
        np_rows = filtered[~filtered["played"]].copy()
        np_rows["color_group"] = np_rows["colors"].map(_color_group)
        np_rows = np_rows[np_rows["color_group"].isin(visible_groups)]
    else:
        np_rows = filtered
    with st.expander(f"Not Played ({0 if np_rows.empty else len(np_rows)})"):
        for _, row in np_rows.iterrows():
            uid = int(row["uid"])
            c1, c2 = st.columns([3, 1])
            c1.write(f"{row['name']} — {row['cmc']:.0f} MV — {row['colors']}")
            if c2.button("Re-add", key=f"re_{uid}"):
                _set_not_played(uid, False)
                st.rerun()


st.title("MTG Card List Analyzer")

with st.sidebar:
    st.header("Input")
    uploaded = st.file_uploader("Upload a .txt decklist", type=["txt"])
    text_input = st.text_area("Or paste a decklist", height=200)
    format_choice = st.selectbox("Format", ["PremierDraft", "TradDraft", "Sealed"])
    set_override = st.text_input("Set override (optional)", "")
    analyze = st.button("Analyze")

if analyze:
    decklist_text = uploaded.read().decode("utf-8") if uploaded else text_input
    if not decklist_text.strip():
        st.warning("Paste or upload a decklist first.")
    else:
        df, not_found, images_by_name = run_pipeline(decklist_text, format_choice, set_override.strip())
        st.session_state["df"] = df
        st.session_state["not_found"] = not_found
        st.session_state["images_by_name"] = images_by_name
        st.session_state["not_played"] = set()
        _bump_version()

df_raw = st.session_state.get("df")
not_found = st.session_state.get("not_found", [])
images_by_name = st.session_state.get("images_by_name", {})
df = explode_copies(df_raw) if df_raw is not None else None

if df is not None:
    if not_found:
        st.warning("Not found: " + ", ".join(not_found))

    not_played = st.session_state["not_played"]
    all_uids = set(df["uid"])

    if df.empty:
        st.info("No cards to show.")
        filtered = df
    else:
        grid_df = df.copy()
        grid_df.insert(0, "played", ~grid_df["uid"].isin(not_played))
        grid_response = AgGrid(
            grid_df,
            gridOptions=build_grid_options(grid_df),
            height=520,
            theme="streamlit",
            update_mode=GridUpdateMode.MODEL_CHANGED,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            allow_unsafe_jscode=True,
            enable_enterprise_modules=True,
            key=f"cards_grid_{st.session_state['grid_version']}",
        )
        filtered = grid_response.data
        if filtered is None or filtered.empty:
            filtered = pd.DataFrame(columns=grid_df.columns)
        else:
            filtered = filtered.copy()
            filtered["played"] = filtered["played"].astype(bool)

        # Reconcile NP from grid edits; only rows currently visible in the grid
        # are updated, so filtered-out rows retain their prior NP status.
        if not filtered.empty:
            played_uids = set(filtered.loc[filtered["played"], "uid"])
            np_uids = set(filtered.loc[~filtered["played"], "uid"])
            not_played = (not_played - played_uids) | np_uids
            st.session_state["not_played"] = not_played
        st.caption(f"{len(filtered)} row(s) shown · {len(not_played)} not played")

    if filtered.empty:
        st.info("No cards match the current filters.")
    else:
        working = filtered[filtered["played"]]

        st.subheader("Win rate by mana value and color")
        visible_groups = st.multiselect("Color lanes", COLOR_GROUP_ORDER, default=COLOR_GROUP_ORDER)

        averages = compute_weighted_averages(working, visible_groups)
        tiles = [("Overall", averages["overall"])]
        tiles += [(g, averages["by_color"][g]) for g in visible_groups if g in averages["by_color"]]
        tile_cols = st.columns(len(tiles))
        for tcol, (label, val) in zip(tile_cols, tiles):
            tcol.metric(label, f"{val:.1f}%" if val is not None else "—")

        chart = build_winrate_dot_chart(working, visible_groups, images_by_name)
        if chart is not None:
            st.bokeh_chart(chart, use_container_width=True)
        else:
            st.info("No win-rate data available for the current selection.")

        render_arena(working, filtered, visible_groups, images_by_name, all_uids)

        st.subheader("Share")
        st.caption("Builds a standalone HTML file of the current view — table, chart and "
                   "deck view. Anyone can open it in a browser; card images and the chart "
                   "library load from the internet. Rebuild after changing filters.")
        if st.button("Build HTML report"):
            # A fresh figure: the one above already belongs to Streamlit's Bokeh document.
            st.session_state["report_html"] = build_report_html(
                filtered=filtered,
                working=working,
                averages=averages,
                visible_groups=visible_groups,
                images_by_name=images_by_name,
                chart=build_winrate_dot_chart(working, visible_groups, images_by_name),
                meta={
                    "Format": format_choice,
                    "Set": set_override.strip().upper() or "as printed",
                },
            )
        if st.session_state.get("report_html"):
            st.download_button(
                "Download HTML report",
                data=st.session_state["report_html"].encode("utf-8"),
                file_name="mtg_report.html",
                mime="text/html",
            )

    st.download_button(
        "Download CSV",
        data=filtered.to_csv(index=False, na_rep="").encode("utf-8-sig"),
        file_name="cards.csv",
        mime="text/csv",
    )
