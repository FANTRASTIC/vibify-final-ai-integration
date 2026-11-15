"""Vibify 2.0 deterministic scorer.

Nothing here calls an LLM. Every score is a hand-checkable weighted sum.

Skipped-feature rule: a feature whose target is absent from the profile is skipped AND its
weight is removed from the maximum, so ``fraction = total / applicable_max`` stays comparable
between profiles that state different numbers of preferences.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.config import DEFAULT_CONFIG, FEATURES, Config
from src.recommender import UserProfile

Neighbors = Dict[str, Dict[str, float]]  # profile genre -> {related genre: weight}


@dataclass
class ProfileV2:
    genres: List[str] = field(default_factory=list)
    moods: List[str] = field(default_factory=list)
    energy: Optional[float] = None
    likes_acoustic: Optional[bool] = None
    valence: Optional[float] = None
    danceability: Optional[float] = None
    tempo_bpm: Optional[float] = None
    weights_override: Optional[Dict[str, float]] = None

    def summary(self) -> Dict:
        """Compact, free-text-free description for logs and feedback."""
        return {k: v for k, v in {
            "genres": self.genres, "moods": self.moods, "energy": self.energy,
            "likes_acoustic": self.likes_acoustic, "valence": self.valence,
            "danceability": self.danceability, "tempo_bpm": self.tempo_bpm,
            "weights_override": self.weights_override}.items() if v not in (None, [], {})}


def profile_from_user_profile(user: UserProfile) -> ProfileV2:
    """Convert a Vibify 1.0 UserProfile into a ProfileV2."""
    return ProfileV2(genres=[user.favorite_genre.lower()], moods=[user.favorite_mood.lower()],
                     energy=user.target_energy, likes_acoustic=user.likes_acoustic)


def profile_from_v1_prefs(prefs: Dict) -> ProfileV2:
    """Convert a v1 prefs dict (genre/mood/energy/likes_acoustic) into a ProfileV2."""
    return ProfileV2(
        genres=[str(prefs["genre"]).lower()] if prefs.get("genre") else [],
        moods=[str(prefs["mood"]).lower()] if prefs.get("mood") else [],
        energy=prefs.get("energy", 0.5), likes_acoustic=prefs.get("likes_acoustic"))


@dataclass
class ScoreBreakdown:
    points: Dict[str, float]
    max_points: Dict[str, float]
    note: str
    total: float
    applicable_max: float
    fraction: float
    notes: Dict[str, str] = field(default_factory=dict)
    genre_credit: float = 0.0   # 0..1 genre credit (1 exact, neighbor weight if related)

    def to_dict(self) -> Dict:
        return {"points": {k: round(v, 4) for k, v in self.points.items()},
                "max_points": self.max_points, "note": self.note, "total": round(self.total, 4),
                "applicable_max": self.applicable_max, "fraction": round(self.fraction, 4),
                "genre_credit": round(self.genre_credit, 4)}


def effective_weights(profile: ProfileV2, base: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Base weights with the user's (already validated) priority overrides applied."""
    w = dict(base or DEFAULT_CONFIG.weights_v2)
    if profile.weights_override:
        w.update(profile.weights_override)
    return w


def _closeness(a: float, b: float) -> float:
    return 1.0 - abs(a - b)


def score_song_v2(profile: ProfileV2, song: Dict, neighbors: Optional[Neighbors] = None,
                  weights: Optional[Dict[str, float]] = None,
                  config: Config = DEFAULT_CONFIG) -> ScoreBreakdown:
    w = weights or config.weights_v2
    neighbors = neighbors or {}
    points: Dict[str, float] = {}
    maxes: Dict[str, float] = {}
    notes: Dict[str, str] = {}
    genre_credit = 0.0

    if profile.genres:
        best, note = 0.0, f"no genre match ({song['genre']})"
        for g in profile.genres:
            if g == song["genre"]:
                best, note = 1.0, f"genre match: {song['genre']}"
                break
            rel = min(neighbors.get(g, {}).get(song["genre"], 0.0), config.neighbor_cap)
            if rel > best:
                best = rel
                note = f"related genre via retrieval: {g}~{song['genre']} {neighbors[g][song['genre']]:.2f}"
        genre_credit = best
        points["genre"], maxes["genre"], notes["genre"] = w["genre"] * best, w["genre"], note

    if profile.moods:
        hit = song["mood"] in profile.moods
        points["mood"], maxes["mood"] = (w["mood"] if hit else 0.0), w["mood"]
        notes["mood"] = f"mood match: {song['mood']}" if hit else f"mood {song['mood']} not requested"

    targets = {"energy": profile.energy, "valence": profile.valence, "danceability": profile.danceability}
    if profile.likes_acoustic is not None:
        targets["acousticness"] = (config.acoustic_target_liked if profile.likes_acoustic
                                   else config.acoustic_target_disliked)
    for feat, target in targets.items():
        if target is None:
            continue
        credit = _closeness(song[feat], target)
        points[feat], maxes[feat] = w[feat] * credit, w[feat]
        notes[feat] = f"{feat} {song[feat]:.2f} vs target {target:.2f}"

    if profile.tempo_bpm is not None:
        credit = max(0.0, min(1.0, 1.0 - abs(song["tempo_bpm"] - profile.tempo_bpm) / config.tempo_span))
        points["tempo"], maxes["tempo"] = w["tempo"] * credit, w["tempo"]
        notes["tempo"] = f"tempo {song['tempo_bpm']:.0f} bpm vs target {profile.tempo_bpm:.0f}"

    total = sum(points.values())
    applicable = sum(maxes.values())
    fraction = total / applicable if applicable > 0 else 0.0
    ordered = [notes[f] for f in FEATURES if f in notes]
    return ScoreBreakdown(points=points, max_points=maxes, note="; ".join(ordered), total=total,
                          applicable_max=applicable, fraction=fraction, notes=notes,
                          genre_credit=genre_credit)


def rank_v2(profile: ProfileV2, songs: List[Dict], neighbors: Optional[Neighbors] = None,
            k: Optional[int] = 5, weights: Optional[Dict[str, float]] = None,
            config: Config = DEFAULT_CONFIG) -> List[Tuple[Dict, ScoreBreakdown]]:
    """Score every song and sort by (-total, id). k=None returns the full ranking."""
    scored = [(s, score_song_v2(profile, s, neighbors, weights, config)) for s in songs]
    scored.sort(key=lambda item: (-item[1].total, item[0]["id"]))
    return scored if k is None else scored[:k]
