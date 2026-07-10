"""Join parsed decklist entries with Scryfall metadata and 17Lands win rates."""
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .parser import DeckEntry
from .scryfall import CardInfo, _entry_key
from .seventeenlands import WinRateStats

COLUMNS = [
    "count", "name", "set", "rarity", "colors", "color_identity",
    "mana_cost", "cmc", "type_line",
    "gih_wr", "oh_wr", "gd_wr", "alsa", "ata", "game_count",
]


def _pct(x: Optional[float]) -> float:
    return round(x * 100, 1) if x is not None else np.nan


def _round1(x: Optional[float]) -> float:
    return round(x, 1) if x is not None else np.nan


def _front_face(name: str) -> str:
    return name.split(" // ")[0].strip().lower()


def build_dataframe(
    entries: List[DeckEntry],
    cards_by_key: Dict[Tuple, CardInfo],
    ratings_by_set: Dict[str, Dict[str, WinRateStats]],
    set_override: Optional[str] = None,
) -> pd.DataFrame:
    rows = []
    for entry in entries:
        key = _entry_key(entry)
        card = cards_by_key.get(key)
        if card is None:
            continue

        lookup_set = (set_override or card.set).upper()
        stats = ratings_by_set.get(lookup_set, {}).get(_front_face(card.name))

        rows.append({
            "count": entry.count,
            "name": card.name,
            "set": card.set,
            "rarity": card.rarity,
            "colors": card.colors,
            "color_identity": card.color_identity,
            "mana_cost": card.mana_cost,
            "cmc": card.cmc,
            "type_line": card.type_line,
            "gih_wr": _pct(stats.gih_wr) if stats else np.nan,
            "oh_wr": _pct(stats.oh_wr) if stats else np.nan,
            "gd_wr": _pct(stats.gd_wr) if stats else np.nan,
            "alsa": _round1(stats.alsa) if stats else np.nan,
            "ata": _round1(stats.ata) if stats else np.nan,
            "game_count": stats.game_count if stats and stats.game_count is not None else np.nan,
        })

    return pd.DataFrame(rows, columns=COLUMNS)


def explode_copies(df: pd.DataFrame) -> pd.DataFrame:
    """One row per copy: repeat each row `count` times, drop `count`, add a uid column."""
    if df.empty:
        out = df.drop(columns=["count"], errors="ignore").copy()
        out.insert(0, "uid", pd.Series([], dtype=int))
        return out
    out = (
        df.loc[df.index.repeat(df["count"].astype(int))]
        .drop(columns=["count"])
        .reset_index(drop=True)
    )
    out.insert(0, "uid", range(len(out)))
    return out
