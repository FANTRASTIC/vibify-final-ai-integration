import csv
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

# Algorithm Recipe weights (baseline max total = 6.0)
DEFAULT_WEIGHTS: Dict[str, float] = {"genre": 2.0, "mood": 1.0, "energy": 2.0, "acoustic": 1.0}


def max_score(weights: Optional[Dict[str, float]] = None) -> float:
    """Return the highest possible score for a set of weights (sum of all weights)."""
    return sum((weights or DEFAULT_WEIGHTS).values())

# Target acousticness used when a profile only says whether the user likes acoustic music
ACOUSTIC_TARGET_LIKED = 0.8
ACOUSTIC_TARGET_DISLIKED = 0.2


@dataclass
class Song:
    """
    Represents a song and its attributes.
    Required by tests/test_recommender.py
    """
    id: int
    title: str
    artist: str
    genre: str
    mood: str
    energy: float
    tempo_bpm: float
    valence: float
    danceability: float
    acousticness: float

@dataclass
class UserProfile:
    """
    Represents a user's taste preferences.
    Required by tests/test_recommender.py
    """
    favorite_genre: str
    favorite_mood: str
    target_energy: float
    likes_acoustic: bool

class Recommender:
    """
    OOP implementation of the recommendation logic.
    Required by tests/test_recommender.py
    """
    def __init__(self, songs: List[Song]):
        """Store the song catalog this recommender ranks."""
        self.songs = songs

    def recommend(self, user: UserProfile, k: int = 5) -> List[Song]:
        """Return the top k songs for a user, best score first."""
        prefs = _profile_to_prefs(user)
        ranked = sorted(
            self.songs,
            key=lambda s: score_song(prefs, _song_to_dict(s))[0],
            reverse=True,
        )
        return ranked[:k]

    def explain_recommendation(self, user: UserProfile, song: Song) -> str:
        """Return a plain-language explanation of why a song scored as it did."""
        score, reasons = score_song(_profile_to_prefs(user), _song_to_dict(song))
        return f"Score {score:.2f}: " + "; ".join(reasons)


def _profile_to_prefs(user: UserProfile) -> Dict:
    """Convert a UserProfile into the prefs dict used by score_song."""
    return {
        "genre": user.favorite_genre,
        "mood": user.favorite_mood,
        "energy": user.target_energy,
        "likes_acoustic": user.likes_acoustic,
    }


def _song_to_dict(song: Song) -> Dict:
    """Convert a Song dataclass into the dict form used by score_song."""
    return {
        "id": song.id, "title": song.title, "artist": song.artist,
        "genre": song.genre, "mood": song.mood, "energy": song.energy,
        "tempo_bpm": song.tempo_bpm, "valence": song.valence,
        "danceability": song.danceability, "acousticness": song.acousticness,
    }


def load_songs(csv_path: str) -> List[Dict]:
    """Read a songs CSV into a list of dicts, converting numeric columns to int/float."""
    int_fields = ("id",)
    float_fields = ("energy", "tempo_bpm", "valence", "danceability", "acousticness")
    songs: List[Dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for field in int_fields:
                row[field] = int(row[field])
            for field in float_fields:
                row[field] = float(row[field])
            songs.append(row)
    return songs


def score_song(user_prefs: Dict, song: Dict, weights: Optional[Dict[str, float]] = None) -> Tuple[float, List[str]]:
    """Score one song against user prefs; return (score, list of human-readable reasons)."""
    w = weights or DEFAULT_WEIGHTS
    score = 0.0
    reasons: List[str] = []

    if song["genre"] == user_prefs.get("genre"):
        score += w["genre"]
        reasons.append(f"genre match: {song['genre']} (+{w['genre']:.1f})")

    if song["mood"] == user_prefs.get("mood"):
        score += w["mood"]
        reasons.append(f"mood match: {song['mood']} (+{w['mood']:.1f})")

    if "energy" in user_prefs:
        target = user_prefs["energy"]
        pts = w["energy"] * (1 - abs(song["energy"] - target))
        score += pts
        reasons.append(f"energy {song['energy']:.2f} vs target {target:.2f} (+{pts:.2f})")

    if "likes_acoustic" in user_prefs:
        target = ACOUSTIC_TARGET_LIKED if user_prefs["likes_acoustic"] else ACOUSTIC_TARGET_DISLIKED
        pts = w["acoustic"] * (1 - abs(song["acousticness"] - target))
        score += pts
        reasons.append(f"acousticness {song['acousticness']:.2f} vs target {target:.2f} (+{pts:.2f})")

    return score, reasons


def recommend_songs(user_prefs: Dict, songs: List[Dict], k: int = 5, weights: Optional[Dict[str, float]] = None) -> List[Tuple[Dict, float, str]]:
    """Score every song, sort best-first, and return the top k as (song, score, explanation).

    Tie-break rule: sorted(..., reverse=True) is stable, so equal scores keep catalog order.
    This equals the v2 sort key (-score, id) whenever catalog order is id order.
    """
    scored = []
    for song in songs:
        score, reasons = score_song(user_prefs, song, weights)
        scored.append((song, score, "; ".join(reasons)))
    return sorted(scored, key=lambda item: item[1], reverse=True)[:k]
