from src.config import Config
from src.rerank import diversify
from src.scoring import ProfileV2, rank_v2


def full_rank(songs, profile, kb_neighbors=None):
    return rank_v2(profile, songs, kb_neighbors, k=None)


def test_skipped_on_small_catalog(songs):
    small = songs[:10]
    items, applied = diversify(full_rank(small, ProfileV2(energy=0.9)), 5, len(small))
    assert applied is False and len(items) == 5
    assert [i.song["id"] for i in items] == [s["id"] for s, _ in full_rank(small, ProfileV2(energy=0.9))[:5]]


def test_artist_cap(songs):
    # Neon Echo has two songs (ids 1 and 8); both match this profile strongly.
    p = ProfileV2(genres=["pop"], energy=0.80)
    items, applied = diversify(full_rank(songs, p), 5, len(songs))
    assert applied
    artists = [i.song["artist"] for i in items]
    assert len(artists) == len(set(artists))


def test_genre_cap(songs):
    p = ProfileV2(genres=["lofi"], moods=["chill"], energy=0.4)
    items, _ = diversify(full_rank(songs, p), 5, len(songs))
    from collections import Counter
    assert max(Counter(i.song["genre"] for i in items).values()) <= 2


def test_discovery_slot_labeled_and_new_genre(songs, kb):
    p = ProfileV2(genres=["indie pop"], moods=["happy"], energy=0.7)
    items, _ = diversify(full_rank(songs, p, {"indie pop": kb.neighbors("indie pop")}), 5, len(songs))
    disc = [i for i in items if i.label == "discovery"]
    assert len(disc) == 1 and items[-1] is disc[0]
    assert disc[0].song["genre"] not in {i.song["genre"] for i in items[:4]}
    assert disc[0].breakdown.fraction >= 0.7 * items[0].breakdown.fraction


def test_discovery_falls_back_when_none_qualifies(songs, kb):
    cfg = Config(discovery_ratio=1.01)  # impossible threshold
    p = ProfileV2(genres=["indie pop"], moods=["happy"], energy=0.7)
    items, _ = diversify(full_rank(songs, p, {"indie pop": kb.neighbors("indie pop")}), 5, len(songs), cfg)
    assert len(items) == 5 and all(i.label is None for i in items)


def test_backfill_when_caps_starve_list():
    songs = [{"id": i, "title": f"t{i}", "artist": "same", "genre": "pop", "mood": "happy", "energy": 0.5,
              "tempo_bpm": 100.0, "valence": 0.5, "danceability": 0.5, "acousticness": 0.5} for i in range(1, 6)]
    cfg = Config(diversity_min_catalog=1)
    items, applied = diversify(full_rank(songs, ProfileV2(energy=0.5)), 5, 5, cfg)
    assert applied and len(items) == 5


def test_empty_and_zero_k(songs):
    assert diversify([], 5, 50) == ([], False)
    assert diversify(full_rank(songs, ProfileV2(energy=0.5)), 0, 50) == ([], False)
