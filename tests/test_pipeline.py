import json
import os

import pytest

from src.config import Config
from src.llm import LLMUnavailable
from src.logging_setup import close_loggers
from src.pipeline import VibifyPipeline
from src.recommender import UserProfile


@pytest.fixture()
def pipe(cfg):
    return VibifyPipeline(config=cfg)


def test_structured_happy_path(pipe):
    r = pipe.recommend({"genres": ["lofi"], "moods": ["chill"], "energy": 0.4, "likes_acoustic": True})
    assert r.ok and len(r.items) == 5 and r.items[0].song["genre"] == "lofi"
    assert r.catalog_support["label"] in ("strong", "moderate", "weak")
    assert "not a verified probability" in r.catalog_support["disclaimer"]
    assert all(i.explanation for i in r.items) and r.retrieved_sources
    json.dumps(r.to_dict())  # serializable


def test_accepts_user_profile_object(pipe):
    r = pipe.recommend(UserProfile("pop", "happy", 0.9, False))
    assert r.ok and r.items[0].song["title"] in {"Sunrise City", "Glass Confetti"}


def test_text_path(pipe):
    r = pipe.recommend_text("late-night study, nothing sleepy")
    assert r.ok and r.profile["genres"] == ["lofi"]


@pytest.mark.parametrize("payload,code", [
    ({}, "EMPTY_PROFILE"), ({"energy": 1.7}, "ENERGY_OUT_OF_RANGE"),
    ({"genres": ["pop"], "tempo_bpm": -3}, "TEMPO_OUT_OF_RANGE"), ({"genres": ["pop"], "zzz": 1}, "UNKNOWN_KEY"),
])
def test_invalid_structured_returns_error_result_not_exception(pipe, payload, code):
    r = pipe.recommend(payload)
    assert not r.ok and r.error_code == code and r.message and r.items == []


@pytest.mark.parametrize("text,code", [("", "EMPTY_TEXT"), ("   ", "EMPTY_TEXT"), ("x" * 600, "TEXT_TOO_LONG"),
                                        ("asdkjh qwlkj zxcv", "EMPTY_PROFILE")])
def test_invalid_text(pipe, text, code):
    r = pipe.recommend_text(text)
    assert not r.ok and r.error_code == code


def test_invalid_k(pipe):
    assert pipe.recommend({"energy": 0.5}, k=0).error_code == "INVALID_K"
    assert pipe.recommend({"energy": 0.5}, k=99).error_code == "INVALID_K"


def test_only_unresolved_genre_has_no_usable_preferences(pipe):
    r = pipe.recommend({"genres": ["zzzz-unknown"]})
    assert not r.ok and r.error_code == "NO_USABLE_PREFERENCES"


def test_unsupported_genre_flags_and_falls_back(pipe):
    r = pipe.recommend({"genres": ["bossa nova"], "moods": ["happy"], "energy": 0.8})
    assert r.ok and "UNRESOLVED_GENRE" in r.flag_codes()
    assert any(t["action"] == "drop_genre_rescale" for t in r.trace)
    assert any("not found" in n for n in r.notes) and r.items


def test_alias_resolution_noted(pipe):
    r = pipe.recommend({"genres": ["k-pop"], "moods": ["happy"], "energy": 0.8})
    assert r.profile["genres"] == ["pop"] and any("k-pop" in w for w in r.warnings)
    assert "genres/pop.md" in r.retrieved_sources


def test_evaluator_is_integrated_removing_it_changes_outputs(cfg):
    """The evaluator changes what the user receives: flags, confidence, revisions and the item list."""
    profile = {"genres": ["blues"], "moods": ["sad"], "energy": 0.9, "likes_acoustic": False}
    on = VibifyPipeline(config=cfg).recommend(profile)
    off_cfg = Config(log_dir=cfg.log_dir, evaluator_enabled=False)
    off = VibifyPipeline(config=off_cfg).recommend(profile)
    assert on.ok and off.ok
    assert on.flag_codes() and off.flag_codes() == []
    assert on.catalog_support["value"] is not None and off.catalog_support["value"] is None
    assert [i.label for i in on.items] != [i.label for i in off.items] or \
        [i.song["id"] for i in on.items] != [i.song["id"] for i in off.items]
    assert on.notes and not off.notes

    unknown = {"genres": ["bossa nova"], "moods": ["happy"], "energy": 0.8}
    on2 = VibifyPipeline(config=cfg).recommend(unknown)
    off2 = VibifyPipeline(config=off_cfg).recommend(unknown)
    assert [i.breakdown["fraction"] for i in on2.items] != [i.breakdown["fraction"] for i in off2.items]


def test_llm_unavailable_falls_back(cfg):
    class Down:
        name = "down"

        def complete(self, *a, **k):
            raise LLMUnavailable("network")

    pipe = VibifyPipeline(config=cfg, llm=Down())
    r = pipe.recommend_text("chill lofi for studying")
    assert r.ok and "LLM_FALLBACK_USED" in r.flag_codes()
    assert all(i.explanation_source == "template" for i in r.items)


def test_unexpected_exception_returns_internal_error(cfg, monkeypatch):
    pipe = VibifyPipeline(config=cfg)
    monkeypatch.setattr(pipe.agent, "run", lambda *a, **k: 1 / 0)
    r = pipe.recommend({"energy": 0.5})
    assert not r.ok and r.error_code == "INTERNAL_ERROR"
    close_loggers()
    line = json.loads(open(cfg.log_file, encoding="utf-8").read().strip().splitlines()[-1])
    assert "ZeroDivisionError" in line["traceback"]


def test_one_log_line_per_request_and_no_raw_text(cfg):
    pipe = VibifyPipeline(config=cfg)
    secret = "my private breakup playlist, sad slow acoustic songs please"
    pipe.recommend_text(secret)
    pipe.recommend({"energy": 0.5})
    pipe.recommend({"energy": 9})
    close_loggers()
    raw = open(cfg.log_file, encoding="utf-8").read()
    lines = [json.loads(x) for x in raw.strip().splitlines()]
    assert len(lines) == 3
    assert "breakup" not in raw and "private" not in raw
    first = lines[0]
    assert first["mode"] == "text" and first["text_len"] == len(secret) and len(first["text_hash"]) == 8
    for key in ("request_id", "timestamp", "latency_ms", "flags", "fallbacks", "validators", "errors", "profile"):
        assert key in first
    assert lines[2]["errors"] == ["ENERGY_OUT_OF_RANGE"] and lines[2]["ok"] is False


def test_logs_never_contain_api_keys(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-should-never-appear")
    pipe = VibifyPipeline(config=cfg)
    pipe.recommend_text("chill lofi")
    close_loggers()
    assert "sk-test" not in open(cfg.log_file, encoding="utf-8").read()


def test_weights_override_changes_ranking(cfg):
    pipe = VibifyPipeline(config=cfg)
    base = {"genres": ["pop"], "energy": 0.9, "tempo_bpm": 60}
    a = pipe.recommend(base)
    b = pipe.recommend({**base, "weights_override": {"tempo": 5, "genre": 0.5}})
    assert [i.song["id"] for i in a.items] != [i.song["id"] for i in b.items]


def test_diversity_applied_on_full_catalog_skipped_on_small(cfg, tmp_path):
    full = VibifyPipeline(config=cfg).recommend({"genres": ["lofi"], "moods": ["chill"], "energy": 0.4})
    artists = [i.song["artist"] for i in full.items]
    assert len(set(artists)) == len(artists)
    assert "DIVERSITY_SKIPPED_SMALL_CATALOG" not in full.flag_codes()
    small = VibifyPipeline(songs_path="data/songs_v1.csv", config=cfg).recommend(
        {"genres": ["lofi"], "moods": ["chill"], "energy": 0.4})
    assert "DIVERSITY_SKIPPED_SMALL_CATALOG" in small.flag_codes()


def test_missing_catalog_raises_at_construction(cfg):
    from src.catalog import CatalogError
    with pytest.raises(CatalogError):
        VibifyPipeline(songs_path="nope.csv", config=cfg)
