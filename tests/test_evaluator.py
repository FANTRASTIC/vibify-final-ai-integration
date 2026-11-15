import pytest

from src.config import Config
from src.evaluator import DISCLAIMER, catalog_support_label, compute_confidence, evaluate
from src.rerank import RankedItem
from src.scoring import ProfileV2, ScoreBreakdown


def item(fraction, credit=1.0, energy=0.8, title="s", i=[0]):
    i[0] += 1
    bd = ScoreBreakdown(points={}, max_points={}, note="", total=fraction * 10, applicable_max=10.0,
                        fraction=fraction, genre_credit=credit)
    return RankedItem({"id": i[0], "title": f"{title}{i[0]}", "artist": "a", "genre": "pop", "mood": "happy",
                       "energy": energy}, bd)


GOOD = [item(0.9), item(0.85), item(0.8), item(0.75), item(0.7)]
P = ProfileV2(genres=["pop"], moods=["happy"], energy=0.8)


def codes(report):
    return {f.code for f in report.flags}


def test_clean_list_passes_without_flags():
    r = evaluate(P, GOOD)
    assert r.passed and codes(r) == set()


def test_low_top_score():
    r = evaluate(P, [item(0.55)] + [item(0.5)] * 4)
    assert "LOW_TOP_SCORE" in codes(r) and not r.passed
    assert "LOW_TOP_SCORE" not in codes(evaluate(P, GOOD))


def test_low_margin():
    r = evaluate(P, [item(0.80)] * 5)
    assert "LOW_MARGIN" in codes(r)
    assert "LOW_MARGIN" not in codes(evaluate(P, GOOD))


def test_no_genre_support():
    r = evaluate(P, [item(0.9, credit=0.0)] * 5)
    assert "NO_GENRE_SUPPORT" in codes(r)
    assert "NO_GENRE_SUPPORT" not in codes(evaluate(P, [item(0.9, credit=0.0)] * 4 + [item(0.9, credit=0.3)]))
    assert "NO_GENRE_SUPPORT" not in codes(evaluate(ProfileV2(energy=0.8), [item(0.9, credit=0.0)] * 5))


def test_unresolved_genre():
    assert "UNRESOLVED_GENRE" in codes(evaluate(P, GOOD, unresolved_genres=["k-pop"]))
    assert "UNRESOLVED_GENRE" not in codes(evaluate(P, GOOD))


@pytest.mark.parametrize("profile", [
    ProfileV2(moods=["sad"], energy=0.9),
    ProfileV2(moods=["angry"], energy=0.2),
    ProfileV2(likes_acoustic=True, energy=0.95),
])
def test_conflicting_preferences_rules(profile):
    assert "CONFLICTING_PREFERENCES" in codes(evaluate(profile, GOOD))


def test_conflict_not_raised_for_consistent_profile():
    assert "CONFLICTING_PREFERENCES" not in codes(evaluate(ProfileV2(moods=["sad"], energy=0.3), GOOD))
    assert "CONFLICTING_PREFERENCES" not in codes(evaluate(P, GOOD))


def test_feature_mismatch_only_in_top_three():
    far = item(0.9, energy=0.3)
    r = evaluate(P, [far] + GOOD[:4])
    assert "FEATURE_MISMATCH" in codes(r)
    r2 = evaluate(P, GOOD[:3] + [far, far])  # mismatching songs at ranks 4 and 5 are tolerated
    assert "FEATURE_MISMATCH" not in codes(r2)


def test_too_few_results():
    r = evaluate(P, GOOD[:3] + [item(0.2), item(0.1)])
    assert "TOO_FEW_RESULTS" in codes(r)
    assert "TOO_FEW_RESULTS" not in codes(evaluate(P, GOOD))


def test_diversity_skipped_is_info_only():
    r = evaluate(P, GOOD, diversity_applied=False)
    f = [x for x in r.flags if x.code == "DIVERSITY_SKIPPED_SMALL_CATALOG"]
    assert f and f[0].severity == "info" and r.passed


def test_acknowledged_flags_downgraded_and_do_not_block():
    r = evaluate(ProfileV2(moods=["sad"], energy=0.9), GOOD, acknowledged=["CONFLICTING_PREFERENCES"])
    flag = next(f for f in r.flags if f.code == "CONFLICTING_PREFERENCES")
    assert flag.severity == "info" and "handled" in flag.message and r.passed


def test_thresholds_come_from_config():
    r = evaluate(P, GOOD, config=Config(low_top_score=0.95))
    assert "LOW_TOP_SCORE" in codes(r)


def test_confidence_formula_hand_checked():
    conf = compute_confidence(P, GOOD, genres_requested=True)
    # top .9, genre_support 1.0, margin_norm min(1,(.9-.7)/.3)=0.6667 -> .45+.3+.1333
    assert conf["catalog_support"] == pytest.approx(0.8833, abs=1e-4)
    assert conf["label"] == "strong" and conf["disclaimer"] == DISCLAIMER
    assert "probability" not in conf


def test_confidence_without_genre_renormalizes():
    conf = compute_confidence(ProfileV2(energy=0.8), GOOD, genres_requested=False)
    assert conf["catalog_support"] == pytest.approx((0.5 * 0.9 + 0.2 * (0.2 / 0.3)) / 0.7, abs=1e-4)


def test_confidence_labels_and_empty():
    assert catalog_support_label(0.75) == "strong" and catalog_support_label(0.5) == "moderate"
    assert catalog_support_label(0.49) == "weak"
    assert compute_confidence(P, [], True)["catalog_support"] == 0.0


def test_disclaimer_text():
    assert DISCLAIMER == ("Catalog support: heuristic estimate of how well this catalog covers your request. "
                          "It is not a verified probability.")
