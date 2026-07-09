# Spec — MTG Card List Analyzer (CLI + Streamlit)

## Goal
A small Python tool that takes a list of Magic: The Gathering card names as input and produces, for each card: colors, mana cost, type, rarity, and 17Lands limited win-rate statistics. Two entry points sharing the same core library:

1. **CLI**: reads a text file, writes a CSV (openable in Excel).
2. **Streamlit app**: paste/upload a list, view an interactive color-coded table, download the CSV.

## Project layout
```
mtg-analyzer/
  core/
    parser.py        # input list parsing
    scryfall.py      # card metadata client
    seventeenlands.py# win-rate client + cache
    merge.py         # join + dataframe building
  mtg_analyze.py     # CLI entry point
  app.py             # Streamlit entry point
  cache/             # JSON cache for 17Lands responses (gitignored)
  requirements.txt   # requests, pandas, streamlit
```

## 1. Input parsing (`parser.py`)
Accept one card per line, supporting these formats (auto-detected per line):
- Plain name: `Lightning Strike`
- Count + name: `4 Lightning Strike`
- Arena export: `4 Lightning Strike (DMU) 137`
- MTGO style: same as count + name

Rules:
- Ignore empty lines, lines starting with `//` or `#`, and section headers like `Deck`, `Sideboard`, `Commander`.
- Return a list of entries `{name, count, set_hint (optional), collector_number (optional)}`.
- Preserve duplicates as a `count` column, do not expand rows.

## 2. Scryfall client (`scryfall.py`)
- Endpoint: `POST https://api.scryfall.com/cards/collection` with batches of **at most 75 identifiers** per request.
- Identifier priority: if `set_hint` + `collector_number` are present use `{"set": ..., "collector_number": ...}`, otherwise `{"name": ...}`.
- Required headers (Scryfall policy): a descriptive `User-Agent` (e.g. `mtg-analyzer/0.1`) and `Accept: application/json`.
- Rate limiting: sleep **100 ms between requests**.
- Handle the `not_found` array in the response: collect these names and report them at the end (CLI: printed warning + `not_found.txt`; Streamlit: warning box). For names typed slightly wrong, optionally retry each not-found name once via `GET /cards/named?fuzzy=<name>`.
- Extract per card: `name`, `set` (code, uppercase), `collector_number`, `rarity`, `mana_cost`, `cmc`, `colors`, `color_identity`, `type_line`, `image_uris.normal` (for double-faced cards without top-level `image_uris`, use `card_faces[0].image_uris.normal`).
- Colors formatting: join WUBRG letters (`"WU"`), empty → `"C"` (colorless).

## 3. 17Lands client (`seventeenlands.py`)
- Endpoint: `GET https://www.17lands.com/card_ratings/data?expansion={SET}&format={FORMAT}&start_date=2019-01-01&end_date={today}` — returns a JSON array with one object per card in the set.
- `{SET}` is the (uppercase) set code of the card as returned by Scryfall; `{FORMAT}` defaults to `PremierDraft` (CLI flag / Streamlit selector to change it, e.g. `TradDraft`, `Sealed`).
- **One request per distinct set** appearing in the input list, not per card.
- **Cache**: store each response as `cache/{SET}_{FORMAT}.json` with a 24 h TTL; on cache hit, do not hit the network. Custom `User-Agent` here too, and be gentle (sequential requests, 1 s sleep between different sets). This is required by 17Lands usage guidelines.
- Extract per card: `ever_drawn_win_rate` (GIH WR — the headline metric), `opening_hand_win_rate`, `drawn_win_rate`, `avg_seen` (ALSA), `avg_pick` (ATA), `game_count`.
- Failure modes to handle gracefully (win-rate columns left empty, no crash):
  - set never drafted on Arena → endpoint returns empty list or error;
  - card present but with fewer than ~500 samples → win-rate fields are `null` (17Lands does not publish low-sample win rates);
  - card simply absent from the set data (e.g. basic lands).

## 4. Merge (`merge.py`)
- Join key: **lowercased card name**; for double-faced/split cards Scryfall names are `Front // Back` while 17Lands uses the front face only → match on the substring before `" // "`.
- If the same card name appears in multiple sets in the input, the `set_hint` disambiguates; otherwise use the printing Scryfall returned.
- Output columns (in order):
  `count, name, set, rarity, colors, color_identity, mana_cost, cmc, type_line, gih_wr, oh_wr, gd_wr, alsa, ata, game_count`
- Win rates as percentages with one decimal (e.g. `56.3`), empty string when unavailable.

## 5. CLI (`mtg_analyze.py`)
```
python mtg_analyze.py decklist.txt -o cards.csv [--format PremierDraft] [--set-override FIN] [--no-cache]
```
- `--set-override`: force all 17Lands lookups onto one set code (useful when Scryfall returns a different printing than the draft set).
- CSV written with `utf-8-sig` encoding so Excel opens accents correctly, comma separator.
- Print a small summary at the end: number of cards resolved, not found, sets queried, cache hits.

## 6. Streamlit app (`app.py`)
- Input: `st.text_area` to paste a list **or** `st.file_uploader` for a `.txt`; format selector (PremierDraft / TradDraft / Sealed); optional set-override text input; "Analyze" button.
- Output: `st.dataframe` of the merged table, sortable, with:
  - row/cell coloring by card color (pandas Styler: W = light yellow, U = light blue, B = gray, R = light red, G = light green, multicolor = gold, C = neutral);
  - GIH WR column with a background gradient (red→green);
  - filters in a sidebar: color(s), rarity, min games.
- `st.download_button` for the CSV.
- Nice-to-have (only if quick): clicking a row shows the card image (`image_uris.normal`); a small mana-curve bar chart (`cmc` histogram weighted by `count`).
- Reuse the same `core/` functions; Streamlit adds `@st.cache_data` on top of the file cache.

## 7. Non-goals (for now)
- No database, no authentication, no deck-building logic, no per-archetype win rates (17Lands `colors` query param exists but is out of scope for v1).

## Acceptance test
Paste this list and verify a sensible table (mixed formats, one double-faced card, one junk name that must land in "not found"):
```
4 Lightning Strike (DMU) 137
Virtue of Loyalty
2 Sheoldred, the Apocalypse
Invasion of Zendikar
Totally Fake Card Name
```