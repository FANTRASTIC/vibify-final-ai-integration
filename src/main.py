"""
Command line runner for the Music Recommender Simulation.

Runs several taste profiles (normal and adversarial) against the song catalog and
prints the top recommendations with the reasons behind each score.

Usage:
    python -m src.main               # baseline weights
    python -m src.main --experiment  # energy x2, genre x0.5
"""

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


def main() -> None:
    """Load the catalog and print recommendations for every profile."""
    experiment = "--experiment" in sys.argv
    weights = EXPERIMENT_WEIGHTS if experiment else None

    songs = load_songs("data/songs_v1.csv")
    print(f"Loaded songs: {len(songs)}")
    print(f"Weights: {weights or DEFAULT_WEIGHTS} (max score {max_score(weights):.2f})\n")

    for name, prefs in PROFILES.items():
        print_recommendations(name, prefs, songs, weights)


if __name__ == "__main__":
    main()
