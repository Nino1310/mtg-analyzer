#!/usr/bin/env python3
"""CLI: read a decklist text file, write an enriched CSV."""
import argparse
import os
import sys

from core.merge import build_dataframe
from core.parser import parse_decklist
from core.scryfall import fetch_cards
from core.seventeenlands import get_ratings_for_sets


def main():
    parser = argparse.ArgumentParser(prog="mtg_analyze.py")
    parser.add_argument("input_file")
    parser.add_argument("-o", "--output", default="cards.csv")
    parser.add_argument(
        "--format", default="PremierDraft",
        choices=["PremierDraft", "TradDraft", "Sealed"],
    )
    parser.add_argument("--set-override", default=None)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    with open(args.input_file, encoding="utf-8") as f:
        text = f.read()

    entries = parse_decklist(text)
    if not entries:
        print("No cards found in input.")
        return

    cards_by_key, not_found = fetch_cards(entries)

    distinct_sets = sorted({
        (args.set_override or card.set).upper() for card in cards_by_key.values()
    })
    ratings_by_set, cache_hit_by_set = get_ratings_for_sets(
        distinct_sets, format=args.format, use_cache=not args.no_cache
    )

    df = build_dataframe(entries, cards_by_key, ratings_by_set, set_override=args.set_override)
    df.to_csv(args.output, index=False, encoding="utf-8-sig", na_rep="")

    total = len(entries)
    resolved = len(df)

    if not_found:
        not_found_path = os.path.join(os.path.dirname(args.output) or ".", "not_found.txt")
        with open(not_found_path, "w", encoding="utf-8") as f:
            f.write("\n".join(not_found) + "\n")
        print(f"warning: {len(not_found)} card(s) not found -> {not_found_path}")

    hits = sum(1 for hit in cache_hit_by_set.values() if hit)
    print(f"Resolved: {resolved}/{total} cards")
    print(f"Not found: {len(not_found)}" + (f" ({', '.join(not_found)})" if not_found else ""))
    print(f"Sets queried: {', '.join(distinct_sets)} ({len(distinct_sets)})")
    print(f"Cache hits: {hits}/{len(distinct_sets)}")


if __name__ == "__main__":
    main()
