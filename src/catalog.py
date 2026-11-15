"""Catalog loading with strict validation."""
from __future__ import annotations

import csv
from collections import Counter
from typing import Dict, List

REQUIRED = ("id", "title", "artist", "genre", "mood", "energy", "tempo_bpm",
            "valence", "danceability", "acousticness")
UNIT_FIELDS = ("energy", "valence", "danceability", "acousticness")
TEXT_FIELDS = ("title", "artist", "genre", "mood")
TEMPO_RANGE = (50.0, 200.0)


class CatalogError(ValueError):
    """Raised for an invalid catalog; the message names the CSV row number and field."""

    def __init__(self, message: str, row: int | None = None, field: str | None = None):
        where = f"row {row}" if row is not None else "file"
        if field:
            where += f", field '{field}'"
        super().__init__(f"{where}: {message}")
        self.row, self.field = row, field


def load_catalog(path: str) -> List[Dict]:
    """Load and validate a songs CSV. Row numbers are 1-based data rows (header excluded)."""
    try:
        f = open(path, newline="", encoding="utf-8")
    except FileNotFoundError:
        raise CatalogError(f"catalog file not found: {path}") from None
    with f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise CatalogError(f"missing required column(s): {', '.join(missing)}")
        songs: List[Dict] = []
        ids, titles = set(), set()
        for n, row in enumerate(reader, start=1):
            song: Dict = {}
            for field in TEXT_FIELDS:
                val = (row.get(field) or "").strip()
                if not val:
                    raise CatalogError("must be non-empty", n, field)
                song[field] = val
            try:
                song["id"] = int(row["id"])
            except (TypeError, ValueError):
                raise CatalogError(f"id must be an integer, got {row.get('id')!r}", n, "id") from None
            if song["id"] in ids:
                raise CatalogError(f"duplicate id {song['id']}", n, "id")
            ids.add(song["id"])
            key = song["title"].lower()
            if key in titles:
                raise CatalogError(f"duplicate title {song['title']!r}", n, "title")
            titles.add(key)
            for field in UNIT_FIELDS + ("tempo_bpm",):
                try:
                    song[field] = float(row[field])
                except (TypeError, ValueError):
                    raise CatalogError(f"must be numeric, got {row.get(field)!r}", n, field) from None
            for field in UNIT_FIELDS:
                if not 0.0 <= song[field] <= 1.0:
                    raise CatalogError(f"{song[field]} outside [0, 1]", n, field)
            if not TEMPO_RANGE[0] <= song["tempo_bpm"] <= TEMPO_RANGE[1]:
                raise CatalogError(f"{song['tempo_bpm']} outside {TEMPO_RANGE}", n, "tempo_bpm")
            songs.append(song)
    return songs


def catalog_stats(songs: List[Dict]) -> Dict[str, Dict[str, int]]:
    """Songs per genre, per artist, and per mood."""
    return {
        "genres": dict(Counter(s["genre"] for s in songs)),
        "artists": dict(Counter(s["artist"] for s in songs)),
        "moods": dict(Counter(s["mood"] for s in songs)),
    }
