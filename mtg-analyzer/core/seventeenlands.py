"""17Lands limited win-rate client with a JSON file cache."""
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional, Tuple

import requests

RATINGS_URL = "https://www.17lands.com/api/card_data"
USER_AGENT = "mtg-analyzer/0.1"
CACHE_TTL = timedelta(hours=24)
BETWEEN_SET_SLEEP_SECONDS = 1


@dataclass
class WinRateStats:
    gih_wr: Optional[float]
    oh_wr: Optional[float]
    gd_wr: Optional[float]
    alsa: Optional[float]
    ata: Optional[float]
    game_count: Optional[int]


def _cache_path(cache_dir: str, set_code: str, format: str) -> str:
    return os.path.join(cache_dir, f"{set_code.upper()}_{format}.json")


def _read_cache(path: str) -> Optional[list]:
    try:
        with open(path) as f:
            cached = json.load(f)
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        if datetime.now(timezone.utc) - fetched_at < CACHE_TTL:
            return cached["data"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        pass
    return None


def _write_cache(path: str, data: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(), "data": data}
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def _index_by_name(raw_list: list) -> Dict[str, WinRateStats]:
    result = {}
    for item in raw_list:
        name = (item.get("name") or "").strip().lower()
        if not name:
            continue
        result[name] = WinRateStats(
            gih_wr=item.get("ever_drawn_win_rate"),
            oh_wr=item.get("opening_hand_win_rate"),
            gd_wr=item.get("drawn_win_rate"),
            alsa=item.get("avg_seen"),
            ata=item.get("avg_pick"),
            game_count=item.get("game_count"),
        )
    return result


def fetch_set_ratings(
    set_code: str,
    format: str = "PremierDraft",
    use_cache: bool = True,
    cache_dir: str = "cache",
) -> Tuple[Dict[str, WinRateStats], bool]:
    set_code = set_code.upper()
    path = _cache_path(cache_dir, set_code, format)

    if use_cache:
        cached_data = _read_cache(path)
        if cached_data is not None:
            return _index_by_name(cached_data), True

    try:
        resp = requests.get(
            RATINGS_URL,
            params={"expansion": set_code, "event_type": format},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = json.loads(resp.text)
        data = payload.get("data", [])
        if not isinstance(data, list):
            data = []
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        print(f"warning: 17Lands request failed for {set_code}/{format}: {exc}", file=sys.stderr)
        return {}, False

    _write_cache(path, data)
    return _index_by_name(data), False


def get_ratings_for_sets(
    set_codes: Iterable[str],
    format: str = "PremierDraft",
    use_cache: bool = True,
    cache_dir: str = "cache",
) -> Tuple[Dict[str, Dict[str, WinRateStats]], Dict[str, bool]]:
    ratings_by_set = {}
    cache_hit_by_set = {}

    codes = list(dict.fromkeys(c.upper() for c in set_codes))
    for i, set_code in enumerate(codes):
        ratings, was_cache_hit = fetch_set_ratings(
            set_code, format=format, use_cache=use_cache, cache_dir=cache_dir
        )
        ratings_by_set[set_code] = ratings
        cache_hit_by_set[set_code] = was_cache_hit

        if not was_cache_hit and i < len(codes) - 1:
            time.sleep(BETWEEN_SET_SLEEP_SECONDS)

    return ratings_by_set, cache_hit_by_set
