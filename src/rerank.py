"""Diversity and discovery re-rank (only on catalogs big enough for it to make sense)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.config import DEFAULT_CONFIG, Config
from src.scoring import ScoreBreakdown


@dataclass
class RankedItem:
    song: Dict
    breakdown: ScoreBreakdown
    label: Optional[str] = None


def diversify(ranked: List[Tuple[Dict, ScoreBreakdown]], k: int, catalog_size: int,
              config: Config = DEFAULT_CONFIG) -> Tuple[List[RankedItem], bool]:
    """Pick k items from a full (-score, id) ranking.

    Returns (items, applied). When catalog_size < config.diversity_min_catalog the plain top k is
    returned and applied=False. Otherwise: at most max_per_artist songs per artist and
    max_per_genre per genre; the last slot (when k >= 5) is a discovery pick.
    """
    if k <= 0 or not ranked:
        return [], False
    if catalog_size < config.diversity_min_catalog:
        return [RankedItem(s, b) for s, b in ranked[:k]], False

    chosen: List[RankedItem] = []
    artists: Counter = Counter()
    genres: Counter = Counter()
    used = set()

    def allowed(song: Dict) -> bool:
        return (artists[song["artist"]] < config.max_per_artist
                and genres[song["genre"]] < config.max_per_genre)

    def take(idx: int, label: Optional[str] = None) -> None:
        song, bd = ranked[idx]
        chosen.append(RankedItem(song, bd, label))
        artists[song["artist"]] += 1
        genres[song["genre"]] += 1
        used.add(idx)

    regular = k - 1 if k >= 5 else k
    for i in range(len(ranked)):
        if len(chosen) >= regular:
            break
        if allowed(ranked[i][0]):
            take(i)

    if k >= 5 and chosen:
        top_fraction = chosen[0].breakdown.fraction
        top_genres = {c.song["genre"] for c in chosen}
        pick = None
        for i, (song, bd) in enumerate(ranked):
            if i in used or song["genre"] in top_genres or not allowed(song):
                continue
            if bd.fraction >= config.discovery_ratio * top_fraction:
                pick = i
                break
        if pick is not None:
            take(pick, "discovery")
        else:
            for i in range(len(ranked)):
                if i not in used and allowed(ranked[i][0]):
                    take(i)
                    break

    # Backfill ignoring caps only if the caps starved the list (tiny or very homogeneous catalog).
    for i in range(len(ranked)):
        if len(chosen) >= k:
            break
        if i not in used:
            take(i)
    return chosen, True
