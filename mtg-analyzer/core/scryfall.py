"""Scryfall card metadata client."""
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests

from .parser import DeckEntry

COLLECTION_URL = "https://api.scryfall.com/cards/collection"
NAMED_URL = "https://api.scryfall.com/cards/named"
BATCH_SIZE = 75
SLEEP_SECONDS = 0.1
USER_AGENT = "mtg-analyzer/0.1"


@dataclass
class CardInfo:
    name: str
    set: str
    collector_number: str
    rarity: str
    mana_cost: str
    cmc: float
    colors: str
    color_identity: str
    type_line: str
    image_uri: Optional[str]


def _headers() -> dict:
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _format_colors(colors: List[str]) -> str:
    return "".join(c for c in "WUBRG" if c in colors) or "C"


def _entry_key(entry: DeckEntry) -> Tuple:
    if entry.set_hint and entry.collector_number:
        return ("sc", entry.set_hint.upper(), entry.collector_number)
    return ("name", entry.name.strip().lower())


def _identifier_for_key(key: Tuple) -> dict:
    if key[0] == "sc":
        return {"set": key[1].lower(), "collector_number": key[2]}
    return {"name": key[1]}


def _card_to_info(card: dict) -> CardInfo:
    image_uri = None
    if "image_uris" in card:
        image_uri = card["image_uris"].get("normal")
    elif card.get("card_faces"):
        face = card["card_faces"][0]
        if "image_uris" in face:
            image_uri = face["image_uris"].get("normal")

    return CardInfo(
        name=card["name"],
        set=card["set"].upper(),
        collector_number=card["collector_number"],
        rarity=card.get("rarity", ""),
        mana_cost=card.get("mana_cost", ""),
        cmc=card.get("cmc", 0.0),
        colors=_format_colors(card.get("colors", [])),
        color_identity=_format_colors(card.get("color_identity", [])),
        type_line=card.get("type_line", ""),
        image_uri=image_uri,
    )


def _match_card_to_key(card: dict, keys: List[Tuple]) -> Optional[Tuple]:
    card_set = card.get("set", "").upper()
    card_cn = card.get("collector_number", "")
    card_name = card.get("name", "").lower()
    card_front = card_name.split(" // ")[0].strip()

    for key in keys:
        if key[0] == "sc" and key[1] == card_set and key[2] == card_cn:
            return key
    for key in keys:
        if key[0] == "name" and key[1] in (card_name, card_front):
            return key
    return None


def _fetch_batch(identifiers: List[dict]) -> dict:
    resp = requests.post(
        COLLECTION_URL, json={"identifiers": identifiers}, headers=_headers(), timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_fuzzy(name: str) -> Optional[dict]:
    try:
        resp = requests.get(
            NAMED_URL, params={"fuzzy": name}, headers=_headers(), timeout=30
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def fetch_cards(
    entries: List[DeckEntry], user_agent: str = USER_AGENT
) -> Tuple[Dict[Tuple, CardInfo], List[str]]:
    keys = list({_entry_key(e) for e in entries})
    cards_by_key: Dict[Tuple, CardInfo] = {}
    unresolved_keys = list(keys)

    batches = [keys[i:i + BATCH_SIZE] for i in range(0, len(keys), BATCH_SIZE)]
    for i, batch_keys in enumerate(batches):
        identifiers = [_identifier_for_key(k) for k in batch_keys]
        try:
            data = _fetch_batch(identifiers)
        except (requests.RequestException, ValueError) as exc:
            print(f"warning: Scryfall batch request failed: {exc}", file=sys.stderr)
            data = {"data": [], "not_found": identifiers}

        for card in data.get("data", []):
            matched_key = _match_card_to_key(card, unresolved_keys)
            if matched_key is not None:
                cards_by_key[matched_key] = _card_to_info(card)
                unresolved_keys.remove(matched_key)

        if i < len(batches) - 1:
            time.sleep(SLEEP_SECONDS)

    # map remaining unresolved name-keys back to display names for fuzzy retry / not_found
    not_found_names: List[str] = []
    key_to_entry_name = {}
    for e in entries:
        key_to_entry_name.setdefault(_entry_key(e), e.name)

    still_unresolved = [k for k in unresolved_keys if k not in cards_by_key]
    for key in still_unresolved:
        if key[0] != "name":
            not_found_names.append(key_to_entry_name.get(key, str(key)))
            continue
        display_name = key_to_entry_name.get(key, key[1])
        time.sleep(SLEEP_SECONDS)
        card = _fetch_fuzzy(display_name)
        if card is not None and "name" in card:
            cards_by_key[key] = _card_to_info(card)
        else:
            not_found_names.append(display_name)

    return cards_by_key, not_found_names
