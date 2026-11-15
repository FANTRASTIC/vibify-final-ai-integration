"""Tests for the Vibify 1.0 functions (load_songs, score_song, recommend_songs)."""
import pytest

from src.recommender import DEFAULT_WEIGHTS, load_songs, max_score, recommend_songs, score_song

SONG = {"id": 1, "title": "T", "artist": "A", "genre": "pop", "mood": "happy",
        "energy": 0.8, "tempo_bpm": 120.0, "valence": 0.5, "danceability": 0.5, "acousticness": 0.2}


def test_load_songs_converts_types():
    songs = load_songs("data/songs_v1.csv")
    s = songs[0]
    assert isinstance(s["id"], int) and isinstance(s["energy"], float)
    assert isinstance(s["tempo_bpm"], float) and isinstance(s["title"], str)


def test_load_songs_missing_file_raises_clear_error():
    with pytest.raises(FileNotFoundError) as exc:
        load_songs("data/does_not_exist.csv")
    assert "does_not_exist.csv" in str(exc.value)


def test_max_score_default():
    assert max_score() == 6.0


def test_score_exact_match():
    prefs = {"genre": "pop", "mood": "happy", "energy": 0.8, "likes_acoustic": False}
    score, reasons = score_song(prefs, SONG)
    assert score == pytest.approx(2.0 + 1.0 + 2.0 + 1.0)
    assert len(reasons) == 4


def test_score_no_match():
    prefs = {"genre": "metal", "mood": "angry", "energy": 0.0, "likes_acoustic": True}
    score, _ = score_song(prefs, SONG)
    # energy: 2*(1-0.8)=0.4 ; acoustic: 1*(1-|0.2-0.8|)=0.4
    assert score == pytest.approx(0.8)


def test_energy_closeness_is_symmetric():
    lo = dict(SONG, energy=0.6)
    hi = dict(SONG, energy=1.0)
    prefs = {"energy": 0.8}
    assert score_song(prefs, lo)[0] == pytest.approx(score_song(prefs, hi)[0])


def test_score_missing_pref_keys_are_skipped():
    score, reasons = score_song({}, SONG)
    assert score == 0.0 and reasons == []
    score, _ = score_song({"energy": 0.8}, SONG)
    assert score == pytest.approx(DEFAULT_WEIGHTS["energy"])


def test_score_song_missing_song_key_raises():
    with pytest.raises(KeyError):
        score_song({"genre": "pop"}, {"mood": "happy"})


def test_recommend_k_larger_than_catalog():
    songs = load_songs("data/songs_v1.csv")[:3]
    assert len(recommend_songs({"energy": 0.5}, songs, k=10)) == 3


def test_recommend_k_zero_and_empty_catalog():
    songs = load_songs("data/songs_v1.csv")
    assert recommend_songs({"energy": 0.5}, songs, k=0) == []
    assert recommend_songs({"energy": 0.5}, [], k=5) == []


def test_recommend_ties_keep_catalog_order():
    a, b, c = dict(SONG, id=1, title="A"), dict(SONG, id=2, title="B"), dict(SONG, id=3, title="C")
    prefs = {"genre": "pop"}
    assert [s["title"] for s, _, _ in recommend_songs(prefs, [a, b, c], k=3)] == ["A", "B", "C"]
    assert [s["title"] for s, _, _ in recommend_songs(prefs, [c, a, b], k=3)] == ["C", "A", "B"]
