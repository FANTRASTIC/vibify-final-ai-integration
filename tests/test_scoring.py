import pytest

from src.recommender import UserProfile
from src.scoring import (ProfileV2, effective_weights, profile_from_user_profile,
                         rank_v2, score_song_v2)

SONG = {"id": 1, "title": "T", "artist": "A", "genre": "pop", "mood": "happy",
        "energy": 0.8, "tempo_bpm": 120.0, "valence": 0.6, "danceability": 0.7, "acousticness": 0.2}


def test_full_profile_hand_checked():
    p = ProfileV2(genres=["pop"], moods=["happy"], energy=0.8, likes_acoustic=False,
                  valence=0.6, danceability=0.7, tempo_bpm=120)
    b = score_song_v2(p, SONG)
    assert b.total == pytest.approx(10.0) and b.applicable_max == 10.0 and b.fraction == pytest.approx(1.0)


def test_partial_credit_numbers():
    p = ProfileV2(genres=["rock"], moods=["sad"], energy=0.5, likes_acoustic=True, tempo_bpm=175)
    b = score_song_v2(p, SONG)
    # genre 0, mood 0, energy 2*(1-0.3)=1.4, acoustic 1*(1-0.6)=0.4, tempo 1*(1-55/110)=0.5
    assert b.points["genre"] == 0 and b.points["mood"] == 0
    assert b.points["energy"] == pytest.approx(1.4)
    assert b.points["acousticness"] == pytest.approx(0.4)
    assert b.points["tempo"] == pytest.approx(0.5)
    assert b.total == pytest.approx(2.3)
    assert b.applicable_max == pytest.approx(2.5 + 1.5 + 2.0 + 1.0 + 1.0)  # no valence/danceability


def test_skipped_features_excluded_from_max():
    p = ProfileV2(energy=0.8)
    b = score_song_v2(p, SONG)
    assert set(b.points) == {"energy"} and b.applicable_max == 2.0 and b.fraction == pytest.approx(1.0)


def test_related_genre_credit_and_note():
    p = ProfileV2(genres=["indie pop"], energy=0.8)
    nb = {"indie pop": {"pop": 0.70}}
    b = score_song_v2(p, SONG, nb)
    assert b.points["genre"] == pytest.approx(2.5 * 0.70)
    assert "related genre via retrieval: indie pop~pop 0.70" in b.note
    assert b.genre_credit == pytest.approx(0.70)


def test_neighbor_cap_applies():
    p = ProfileV2(genres=["indie pop"], energy=0.8)
    b = score_song_v2(p, SONG, {"indie pop": {"pop": 0.95}})
    assert b.genre_credit == pytest.approx(0.75)


def test_best_of_multiple_genres():
    p = ProfileV2(genres=["rock", "pop"], energy=0.8)
    assert score_song_v2(p, SONG).genre_credit == 1.0


def test_tempo_clamped_to_zero():
    p = ProfileV2(energy=0.8, tempo_bpm=40)  # 80 bpm away -> 1 - 80/110 > 0
    far = dict(SONG, tempo_bpm=200.0)
    b = score_song_v2(ProfileV2(energy=0.8, tempo_bpm=40), far)
    assert b.points["tempo"] == 0.0
    assert score_song_v2(p, SONG).points["tempo"] > 0


def test_rank_tiebreak_by_id():
    a, b = dict(SONG, id=7, title="A"), dict(SONG, id=3, title="B")
    ranked = rank_v2(ProfileV2(genres=["pop"], energy=0.8), [a, b], k=2)
    assert [s["id"] for s, _ in ranked] == [3, 7]


def test_rank_k_and_full():
    songs = [dict(SONG, id=i, energy=i / 10) for i in range(1, 6)]
    p = ProfileV2(energy=0.5)
    assert len(rank_v2(p, songs, k=2)) == 2 and len(rank_v2(p, songs, k=None)) == 5
    assert rank_v2(p, songs, k=1)[0][0]["energy"] == 0.5


def test_converter_from_user_profile():
    p = profile_from_user_profile(UserProfile("Pop", "Happy", 0.9, False))
    assert p.genres == ["pop"] and p.moods == ["happy"] and p.energy == 0.9 and p.likes_acoustic is False


def test_weights_override_applied():
    p = ProfileV2(energy=0.8, weights_override={"energy": 4.0})
    w = effective_weights(p)
    assert w["energy"] == 4.0 and w["genre"] == 2.5
    assert score_song_v2(p, SONG, weights=w).points["energy"] == pytest.approx(4.0)
