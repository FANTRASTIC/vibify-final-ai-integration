import pytest

from src.config import Config
from src.guardrails import ErrorCode, ValidationError, validate_profile, validate_text


def code_of(raw, **kw):
    with pytest.raises(ValidationError) as e:
        validate_profile(raw, **kw)
    return e.value.code


def test_valid_profile_normalized():
    p, w = validate_profile({"genres": ["  Pop ", "ROCK", "pop"], "moods": ["Happy"], "energy": 0.8,
                             "likes_acoustic": False, "tempo_bpm": 120})
    assert p.genres == ["pop", "rock"] and p.moods == ["happy"] and p.energy == 0.8 and w == []


def test_v1_style_keys_accepted():
    p, _ = validate_profile({"genre": "Pop", "mood": "happy", "energy": 0.9, "likes_acoustic": False})
    assert p.genres == ["pop"] and p.moods == ["happy"]


@pytest.mark.parametrize("raw,code", [
    ({"energy": 1.7}, ErrorCode.ENERGY_OUT_OF_RANGE),
    ({"energy": -0.1}, ErrorCode.ENERGY_OUT_OF_RANGE),
    ({"valence": 2}, ErrorCode.VALENCE_OUT_OF_RANGE),
    ({"danceability": -1}, ErrorCode.DANCEABILITY_OUT_OF_RANGE),
    ({"tempo_bpm": -5, "genres": ["pop"]}, ErrorCode.TEMPO_OUT_OF_RANGE),
    ({"tempo_bpm": 500, "genres": ["pop"]}, ErrorCode.TEMPO_OUT_OF_RANGE),
    ({"genres": ["pop"], "color": "red"}, ErrorCode.UNKNOWN_KEY),
    ({"genres": "pop", "energy": "high"}, ErrorCode.INVALID_TYPE),
    ({"genres": [1, 2]}, ErrorCode.INVALID_TYPE),
    ({"genres": ["pop", ""]}, ErrorCode.INVALID_TYPE),
    ({"genres": ["a", "b", "c", "d", "e", "f"]}, ErrorCode.TOO_MANY_ITEMS),
    ({"moods": ["a", "b", "c", "d", "e", "f"]}, ErrorCode.TOO_MANY_ITEMS),
    ({"genres": ["pop"], "likes_acoustic": "yes"}, ErrorCode.INVALID_TYPE),
    ({"energy": True}, ErrorCode.INVALID_TYPE),
    ({"energy": float("nan")}, ErrorCode.INVALID_TYPE),
    ({}, ErrorCode.EMPTY_PROFILE),
    ({"genres": [], "moods": []}, ErrorCode.EMPTY_PROFILE),
    ("not a dict", ErrorCode.INVALID_TYPE),
    ({"genres": ["pop"], "weights_override": {"loudness": 1}}, ErrorCode.INVALID_WEIGHTS),
    ({"genres": ["pop"], "weights_override": {"energy": 9}}, ErrorCode.INVALID_WEIGHTS),
    ({"genres": ["pop"], "weights_override": {"energy": -1}}, ErrorCode.INVALID_WEIGHTS),
    ({"genres": ["pop"], "weights_override": {"energy": 0, "mood": 0}}, ErrorCode.INVALID_WEIGHTS),
    ({"genres": ["pop"], "weights_override": {}}, ErrorCode.INVALID_WEIGHTS),
])
def test_strict_rejections(raw, code):
    assert code_of(raw) == code


def test_energy_not_silently_clamped_in_strict_mode():
    assert code_of({"energy": 1.0000001}) == ErrorCode.ENERGY_OUT_OF_RANGE
    p, _ = validate_profile({"energy": 1.0})
    assert p.energy == 1.0


def test_valid_weights_override():
    p, _ = validate_profile({"genres": ["pop"], "weights_override": {"energy": 4, "tempo": 0}})
    assert p.weights_override == {"energy": 4.0, "tempo": 0.0}


def test_lenient_mode_clamps_and_warns():
    p, w = validate_profile({"genres": ["pop"], "energy": 1.7, "tempo_bpm": 999, "valence": "x",
                             "evil": 1, "likes_acoustic": "maybe"}, lenient=True)
    assert p.energy == 1.0 and p.tempo_bpm == 220.0 and p.valence is None and p.likes_acoustic is None
    assert len(w) >= 4 and any("unknown" in x for x in w) and any("clamped energy" in x for x in w)


def test_lenient_still_rejects_empty():
    assert code_of({"evil": 1}, lenient=True) == ErrorCode.EMPTY_PROFILE


def test_lenient_truncates_lists():
    p, w = validate_profile({"genres": list("abcdefg")}, lenient=True)
    assert len(p.genres) == 5 and any("truncated" in x for x in w)


@pytest.mark.parametrize("text,code", [
    ("", ErrorCode.EMPTY_TEXT), ("   \n ", ErrorCode.EMPTY_TEXT), ("x" * 501, ErrorCode.TEXT_TOO_LONG),
    ("hello\x00world", ErrorCode.CONTROL_CHARACTERS), (None, ErrorCode.INVALID_TYPE),
])
def test_validate_text_rejections(text, code):
    with pytest.raises(ValidationError) as e:
        validate_text(text)
    assert e.value.code == code


def test_validate_text_ok_and_limit_configurable():
    assert validate_text("  late night study \n") == "late night study"
    assert validate_text("x" * 500) == "x" * 500
    with pytest.raises(ValidationError):
        validate_text("x" * 11, Config(text_max_len=10))
