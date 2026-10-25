"""Arena-style deck view: card thumbnails laid out by mana value, creatures on top."""
import html
from typing import Dict, List, Tuple

import pandas as pd

from .chart import CMC_BUCKETS, _cmc_bucket, _color_group

# "@@" is replaced by a scope selector so the same rules work standalone (inside the
# Streamlit iframe) or nested in the exported report page.
_ARENA_RULES = """
  @@.region-title{font-weight:700;font-size:14px;margin:6px 0 2px;}
  @@.grid{display:flex;gap:6px;align-items:flex-start;}
  @@.col{flex:1;min-width:0;text-align:center;}
  @@.col-h{font-weight:600;font-size:12px;margin-bottom:2px;color:#888;}
  @@.card{position:relative;display:inline-block;line-height:0;margin:2px 0;width:72px;}
  @@.card img.t{width:72px;display:block;border-radius:3px;cursor:pointer;}
  @@.card img.z{display:none;position:fixed;top:6%;left:50%;transform:translateX(-50%);
      width:300px;z-index:99999;box-shadow:0 0 16px rgba(0,0,0,.6);border-radius:10px;}
  @@.card:hover img.z{display:block;}
  @@.noimg{font-size:9px;line-height:1.1;padding:3px;border:1px solid #bbb;border-radius:3px;
      width:72px;display:inline-block;word-break:break-word;}
  @@.divider{border:none;border-top:2px solid #888;margin:8px 0;}
"""


def arena_css(scope: str = "") -> str:
    """CSS block for the deck view. Pass a scope selector to nest it in a larger page."""
    if scope:
        reset = f"{scope} *{{box-sizing:border-box;}}"
        prefix = f"{scope} "
    else:
        reset = "*{box-sizing:border-box;}body{margin:0;font-family:sans-serif;color:inherit;}"
        prefix = ""
    return f"<style>{reset}{_ARENA_RULES.replace('@@', prefix)}</style>"


ARENA_STYLE = arena_css()

CARD_H = 106  # px per stacked thumbnail (72px * ~1.4 + margin)


def is_creature(type_line) -> bool:
    return "Creature" in str(type_line).split("//")[0]


def _region_html(region_df: pd.DataFrame, buckets: List[str], images_by_name: Dict[str, str]) -> str:
    cols = []
    for b in buckets:
        cards = region_df[region_df["cmc_bucket"] == b]
        inner = []
        for _, r in cards.iterrows():
            nm = html.escape(str(r["name"]), quote=True)
            url = images_by_name.get(r["name"])
            if url:
                u = html.escape(str(url), quote=True)
                inner.append(f'<div class="card"><img class="t" src="{u}" alt="{nm}">'
                             f'<img class="z" src="{u}"></div>')
            else:
                inner.append(f'<div class="noimg">{nm}</div>')
        cols.append(f'<div class="col"><div class="col-h">{b}</div>{"".join(inner)}</div>')
    return f'<div class="grid">{"".join(cols)}</div>'


def build_arena(
    working: pd.DataFrame, visible_groups: List[str], images_by_name: Dict[str, str]
) -> Tuple[str, int]:
    """Return (body HTML, natural pixel height). Body is empty when nothing is playable."""
    w = working.copy()
    if not w.empty:
        w["color_group"] = w["colors"].map(_color_group)
        w = w[w["color_group"].isin(visible_groups)]
        w["cmc_bucket"] = w["cmc"].map(_cmc_bucket)
        w = w[w["cmc_bucket"].notna()]

    buckets = [b for b in CMC_BUCKETS if not w.empty and (w["cmc_bucket"] == b).any()]
    if not buckets:
        return "", 0

    is_cr = w["type_line"].map(is_creature)
    creatures, others = w[is_cr], w[~is_cr]

    def _max_stack(region: pd.DataFrame) -> int:
        if region.empty:
            return 0
        return int(region.groupby("cmc_bucket").size().max())

    body = (
        '<div class="region-title">Creatures</div>'
        + _region_html(creatures, buckets, images_by_name)
        + '<hr class="divider">'
        + '<div class="region-title">Non-creatures</div>'
        + _region_html(others, buckets, images_by_name)
    )
    height = 60 + _max_stack(creatures) * CARD_H + 40 + _max_stack(others) * CARD_H + 20
    return body, height
