"""
Command line runner for the Music Recommender Simulation.

Runs several taste profiles (normal and adversarial) against the song catalog and
prints the top recommendations with the reasons behind each score.

Usage:
    python -m src.main               # Vibify 1.0 output (frozen 19-song catalog, baseline weights)
    python -m src.main --experiment  # Vibify 1.0, energy x2, genre x0.5
    python -m src.main --v2          # six profiles through the Vibify 2.0 pipeline
    python -m src.main --text "late-night study, nothing sleepy"
    python -m src.main --compare     # v1 vs v2 top 5, side by side
    python -m src.main --v2 --llm mock|anthropic
"""

import argparse
import os
import sys
from typing import Dict, Optional

from src.recommender import DEFAULT_WEIGHTS, load_songs, max_score, recommend_songs

PROFILES: Dict[str, Dict] = {
    # Normal profiles
    "High-Energy Pop": {"genre": "pop", "mood": "happy", "energy": 0.9, "likes_acoustic": False},
    "Chill Lofi": {"genre": "lofi", "mood": "chill", "energy": 0.4, "likes_acoustic": True},
    "Deep Intense Rock": {"genre": "rock", "mood": "intense", "energy": 0.92, "likes_acoustic": False},
    # Adversarial / edge-case profiles
    "Conflicting (sad but high energy)": {"genre": "blues", "mood": "sad", "energy": 0.9, "likes_acoustic": False},
    "Unknown genre (k-pop)": {"genre": "k-pop", "mood": "happy", "energy": 0.8, "likes_acoustic": False},
    "Mixed signals (pop + chill, mid energy)": {"genre": "pop", "mood": "chill", "energy": 0.5, "likes_acoustic": True},
}

# Experiment: double the importance of energy, halve the importance of genre
EXPERIMENT_WEIGHTS = {**DEFAULT_WEIGHTS, "energy": DEFAULT_WEIGHTS["energy"] * 2, "genre": DEFAULT_WEIGHTS["genre"] / 2}


def print_recommendations(name: str, prefs: Dict, songs, weights: Optional[Dict[str, float]]) -> None:
    """Print the top 5 recommendations for one profile in a readable layout."""
    top = max_score(weights)
    print("=" * 64)
    print(f"PROFILE: {name}")
    print(f"  genre={prefs['genre']}, mood={prefs['mood']}, energy={prefs['energy']}, "
          f"likes_acoustic={prefs['likes_acoustic']}")
    print("=" * 64)
    for rank, (song, score, explanation) in enumerate(recommend_songs(prefs, songs, k=5, weights=weights), start=1):
        print(f"{rank}. {song['title']} by {song['artist']} [{song['genre']}/{song['mood']}]")
        print(f"   Score: {score:.2f} / {top:.2f}")
        for reason in explanation.split("; "):
            print(f"     - {reason}")
    print()


def print_v2_result(title: str, result) -> None:
    """Print one pipeline Result: scores, breakdown, explanation, flags, catalog support."""
    print("=" * 64)
    print(f"[v2] {title}")
    print("=" * 64)
    if not result.ok:
        print(f"  ERROR {result.error_code}: {result.message}\n")
        return
    print(f"  parsed profile: {result.profile}")
    for w in result.warnings:
        print(f"  note: {w}")
    for rank, item in enumerate(result.items, start=1):
        s, bd = item.song, item.breakdown
        tag = f" <{item.label}>" if item.label else ""
        print(f"{rank}. {s['title']} by {s['artist']} [{s['genre']}/{s['mood']}]{tag}")
        print(f"   Fit: {bd['fraction']:.0%} ({bd['total']:.2f} / {bd['applicable_max']:.2f})")
        for feat, pts in bd["points"].items():
            print(f"     - {feat}: {pts:.2f} / {bd['max_points'][feat]:.2f}")
        print(f"   Why ({item.explanation_source}): {item.explanation}")
    for note in result.notes:
        print(f"  * {note}")
    for flag in result.evaluation["flags"]:
        print(f"  [{flag['severity'].upper()}] {flag['code']}: {flag['message']}")
    cs = result.catalog_support
    print(f"  Catalog support: {cs['label']} ({cs['value']})" if cs["value"] is not None
          else "  Catalog support: unavailable (evaluator disabled)")
    print(f"  {cs['disclaimer']}")
    if result.degraded:
        print("  (degraded: best effort after revisions)")
    print()


def run_v2(args) -> None:
    from src.pipeline import VibifyPipeline
    pipe = VibifyPipeline()
    print(f"Vibify 2.0 | catalog: {len(pipe.songs)} songs | LLM backend: {pipe.llm_name}\n")
    if args.text:
        print_v2_result(f'text: "{args.text}"', pipe.recommend_text(args.text))
        return
    for name, prefs in PROFILES.items():
        print_v2_result(name, pipe.recommend(prefs))


def run_compare() -> None:
    from src.pipeline import VibifyPipeline
    pipe = VibifyPipeline()
    songs = pipe.songs
    print(f"Vibify 1.0 vs 2.0, same {len(songs)}-song catalog, top 5 per profile\n")
    for name, prefs in PROFILES.items():
        v1 = [s["title"] for s, _, _ in recommend_songs(prefs, songs, k=5)]
        res = pipe.recommend(prefs)
        v2 = [i.song["title"] for i in res.items[:5]]
        print(f"PROFILE: {name}")
        print(f"  {'#':<2} {'Vibify 1.0':<28} {'Vibify 2.0':<28}")
        for i in range(5):
            print(f"  {i + 1:<2} {v1[i] if i < len(v1) else '':<28} {v2[i] if i < len(v2) else '':<28}")
        flags = ", ".join(res.flag_codes()) or "none"
        print(f"  v2 flags: {flags} | catalog support: {res.catalog_support['label']}\n")


def main() -> None:
    """Load the catalog and print recommendations for every profile."""
    ap = argparse.ArgumentParser(description="Vibify music recommender")
    ap.add_argument("--experiment", action="store_true", help="v1: energy x2, genre x0.5")
    ap.add_argument("--v2", action="store_true", help="run the six profiles through the v2 pipeline")
    ap.add_argument("--text", help="free-text request through the v2 pipeline")
    ap.add_argument("--compare", action="store_true", help="v1 vs v2 top 5 side by side")
    ap.add_argument("--llm", choices=["mock", "anthropic"], help="override VIBIFY_LLM")
    args = ap.parse_args()
    if args.llm:
        os.environ["VIBIFY_LLM"] = args.llm
    if args.compare:
        return run_compare()
    if args.v2 or args.text:
        return run_v2(args)

    experiment = args.experiment
    weights = EXPERIMENT_WEIGHTS if experiment else None

    songs = load_songs("data/songs_v1.csv")
    print(f"Loaded songs: {len(songs)}")
    print(f"Weights: {weights or DEFAULT_WEIGHTS} (max score {max_score(weights):.2f})\n")

    for name, prefs in PROFILES.items():
        print_recommendations(name, prefs, songs, weights)


if __name__ == "__main__":
    main()
