"""Streamlit app: paste/upload a decklist, view an enriched, color-coded table."""
import streamlit as st

from core.merge import build_dataframe
from core.parser import parse_decklist
from core.scryfall import fetch_cards
from core.seventeenlands import get_ratings_for_sets

COLOR_BG = {
    "W": "#fdf6c9", "U": "#cfe8fb", "B": "#d8d8d8",
    "R": "#fbd2c9", "G": "#d3f0c9", "C": "#f0f0f0",
}
MULTICOLOR_BG = "#f0d97a"

st.set_page_config(page_title="MTG Card List Analyzer", layout="wide")


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


def row_style(row):
    c = row["colors"]
    if len(c) > 1 and c != "C":
        bg = MULTICOLOR_BG
    else:
        bg = COLOR_BG.get(c, "#ffffff")
    return [f"background-color: {bg}"] * len(row)


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

df = st.session_state.get("df")
not_found = st.session_state.get("not_found", [])
images_by_name = st.session_state.get("images_by_name", {})

if df is not None:
    if not_found:
        st.warning("Not found: " + ", ".join(not_found))

    st.sidebar.header("Filters")
    colors_available = sorted(df["colors"].dropna().unique()) if not df.empty else []
    rarities_available = sorted(df["rarity"].dropna().unique()) if not df.empty else []
    color_filter = st.sidebar.multiselect("Colors", colors_available)
    rarity_filter = st.sidebar.multiselect("Rarity", rarities_available)
    min_games = st.sidebar.number_input("Min games", min_value=0, value=0)

    filtered = df.copy()
    if color_filter:
        filtered = filtered[filtered["colors"].isin(color_filter)]
    if rarity_filter:
        filtered = filtered[filtered["rarity"].isin(rarity_filter)]
    if min_games:
        filtered = filtered[filtered["game_count"].fillna(0) >= min_games]

    if filtered.empty:
        st.info("No cards match the current filters.")
    else:
        styled = filtered.style.apply(row_style, axis=1)
        styled = styled.background_gradient(subset=["gih_wr"], cmap="RdYlGn", vmin=0, vmax=100)
        st.dataframe(styled, use_container_width=True)

        card_names = filtered["name"].tolist()
        selected = st.selectbox("View card image", ["(none)"] + card_names)
        if selected != "(none)" and images_by_name.get(selected):
            st.image(images_by_name[selected], width=250)

        curve = filtered.groupby("cmc")["count"].sum()
        st.subheader("Mana curve")
        st.bar_chart(curve)

    st.download_button(
        "Download CSV",
        data=filtered.to_csv(index=False, na_rep="").encode("utf-8-sig"),
        file_name="cards.csv",
        mime="text/csv",
    )
