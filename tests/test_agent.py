import json
import os

from src.agent import RevisionAgent
from src.scoring import ProfileV2


def run(songs, kb, cfg, profile, unresolved=(), k=5):
    return RevisionAgent(songs, kb, cfg).run(profile, list(unresolved), k, request_id="t")


def test_clean_profile_needs_no_revision(songs, kb, cfg):
    out = run(songs, kb, cfg, ProfileV2(genres=["lofi"], moods=["chill"], energy=0.4, likes_acoustic=True))
    assert len(out.trace) == 1 and out.trace[0]["action"] == "initial" and out.report.passed and not out.degraded
    assert not os.path.exists(cfg.trace_file)  # nothing to log when the loop did not act


def test_unresolved_genre_converges_after_one_revision(songs, kb, cfg):
    p = ProfileV2(genres=["zzz-unknown"], moods=["happy"], energy=0.8, likes_acoustic=False)
    out = run(songs, kb, cfg, p, unresolved=["zzz-unknown"])
    assert [t["action"] for t in out.trace][:2] == ["initial", "drop_genre_rescale"]
    assert "UNRESOLVED_GENRE" in out.trace[0]["flags_after"]
    assert "NO_GENRE_SUPPORT" in out.trace[0]["flags_after"]
    assert not any(f in out.trace[1]["flags_after"] for f in ("NO_GENRE_SUPPORT", "LOW_TOP_SCORE"))
    assert "UNRESOLVED_GENRE(info)" in out.trace[1]["flags_after"]
    assert out.report.passed and out.profile.genres == []
    assert any("Genre not found" in n for n in out.notes)
    rec = [json.loads(line) for line in open(cfg.trace_file, encoding="utf-8")]
    assert rec[0]["request_id"] == "t" and len(rec[0]["trace"]) == len(out.trace)


def test_revision_budget_is_bounded(songs, kb, cfg):
    p = ProfileV2(genres=["zzz"], moods=["sad"], energy=0.95, likes_acoustic=True)
    out = run(songs, kb, cfg, p, unresolved=["zzz"])
    assert len(out.trace) - 1 <= cfg.max_revisions
    assert out.items  # never empty for a valid profile


def test_conflicting_preferences_adds_labeled_picks(songs, kb, cfg):
    p = ProfileV2(genres=["blues"], moods=["sad"], energy=0.9, likes_acoustic=False)
    out = run(songs, kb, cfg, p)
    assert "CONFLICTING_PREFERENCES" in out.trace[0]["flags_after"]
    actions = [t["action"] for t in out.trace]
    assert "keep_numbers_add_labeled_picks" in actions
    labels = {i.label for i in out.items}
    assert "meets-your-mood" in labels or "meets-your-energy" in labels
    assert p.energy == 0.9 and out.profile.energy == 0.9  # stated numbers kept
    assert any("conflict" in n.lower() for n in out.notes)


def test_energy_weight_boost_is_capped(songs, kb, cfg):
    cfg.max_revisions = 6
    cfg.energy_weight_cap = 2.5
    p = ProfileV2(genres=["pop"], energy=0.1)
    out = run(songs, kb, cfg, p)
    assert out.weights["energy"] <= 2.5


def test_degraded_when_loop_cannot_fix(songs, kb, cfg):
    cfg.max_revisions = 0
    p = ProfileV2(genres=["zzz"], moods=["happy"], energy=0.8, likes_acoustic=False)
    out = run(songs, kb, cfg, p, unresolved=["zzz"])
    assert out.degraded and any("best effort" in n for n in out.notes) and out.items


def test_weights_are_not_mutated_between_runs(songs, kb, cfg):
    before = dict(cfg.weights_v2)
    run(songs, kb, cfg, ProfileV2(genres=["pop"], energy=0.1))
    assert cfg.weights_v2 == before
