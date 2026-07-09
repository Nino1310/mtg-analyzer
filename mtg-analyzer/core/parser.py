"""Parsing of pasted/uploaded decklists into DeckEntry records."""
import re
from dataclasses import dataclass
from typing import List, Optional

HEADER_RE = re.compile(
    r'^(deck|sideboard|commander|companion|maybeboard)\s*:?\s*$', re.IGNORECASE
)
ARENA_RE = re.compile(
    r'^(?P<count>\d+)\s+(?P<name>.+?)\s+\((?P<set>[A-Za-z0-9]{2,5})\)\s+(?P<cn>\S+)\s*.*$'
)
COUNT_NAME_RE = re.compile(r'^(?P<count>\d+)\s+(?P<name>.+)$')


@dataclass
class DeckEntry:
    name: str
    count: int = 1
    set_hint: Optional[str] = None
    collector_number: Optional[str] = None


def parse_line(line: str) -> Optional[DeckEntry]:
    s = line.strip()
    if not s or s.startswith('//') or s.startswith('#') or HEADER_RE.match(s):
        return None

    m = ARENA_RE.match(s)
    if m:
        return DeckEntry(
            name=m.group('name').strip(),
            count=int(m.group('count')),
            set_hint=m.group('set').upper(),
            collector_number=m.group('cn'),
        )

    m = COUNT_NAME_RE.match(s)
    if m:
        return DeckEntry(name=m.group('name').strip(), count=int(m.group('count')))

    return DeckEntry(name=s, count=1)


def parse_decklist(text: str) -> List[DeckEntry]:
    entries = []
    for line in text.splitlines():
        entry = parse_line(line)
        if entry is not None:
            entries.append(entry)
    return entries
