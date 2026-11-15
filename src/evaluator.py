"""Reliability evaluator: the gate every ranked list passes before a user sees it.

Deterministic, no LLM. It returns flags, a pass/fail verdict and a heuristic confidence
("catalog_support"). The agent (src/agent.py) reads the flags and revises; the pipeline
carries flags and confidence to the user.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from src.config import DEFAULT_CONFIG, Config
from src.rerank import RankedItem
from src.scoring import ProfileV2

DISCLAIMER = ("Catalog support: heuristic estimate of how well this catalog covers your request. "
              "It is not a verified probability.")

# Flags that trigger the revise loop and decide `passed`.
LOOP_FLAGS = ("LOW_TOP_SCORE", "NO_GENRE_SUPPORT", "UNRESOLVED_GENRE", "CONFLICTING_PREFERENCES",
              "FEATURE_MISMATCH", "TOO_FEW_RESULTS")


@dataclass
class Flag:
    code: str
    severity: str  # info | warn | fail
    message: str

    def to_dict(self) -> Dict:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass
class EvaluationReport:
    flags: List[Flag]
    passed: bool
    metrics: Dict
    confidence: Dict

    def codes(self) -> List[str]:
        return [f.code for f in self.flags]

    def to_dict(self) -> Dict:
        return {"flags": [f.to_dict() for f in self.flags], "passed": self.passed,
                "metrics": self.metrics, "confidence": self.confidence}


def matches_conflict_rule(profile: ProfileV2, rule: Dict) -> bool:
    if "energy_min" in rule and (profile.energy is None or profile.energy < rule["energy_min"]):
        return False
    if "energy_max" in rule and (profile.energy is None or profile.energy > rule["energy_max"]):
        return False
    if "moods_any" in rule and not (set(profile.moods) & set(rule["moods_any"])):
        return False
    if "likes_acoustic" in rule and profile.likes_acoustic is not rule["likes_acoustic"]:
        return False
    return True


def catalog_support_label(value: float, config: Config = DEFAULT_CONFIG) -> str:
    if value >= config.conf_strong:
        return "strong"
    if value >= config.conf_moderate:
        return "moderate"
    return "weak"


def compute_confidence(profile: ProfileV2, items: Sequence[RankedItem], genres_requested: bool,
                       config: Config = DEFAULT_CONFIG) -> Dict:
    """catalog_support = clamp(c1*top_fraction + c2*genre_support + c3*margin_norm).

    When no genre was requested, the genre term does not apply and the other two are renormalized.
    """
    if not items:
        return {"catalog_support": 0.0, "label": "weak", "disclaimer": DISCLAIMER}
    fractions = [i.breakdown.fraction for i in items]
    top, last = fractions[0], fractions[-1]
    margin_norm = min(1.0, max(0.0, (top - last) / config.conf_margin_span))
    if genres_requested:
        support = sum(i.breakdown.genre_credit for i in items) / len(items)
        raw = config.conf_c1 * top + config.conf_c2 * support + config.conf_c3 * margin_norm
    else:
        support = None
        raw = (config.conf_c1 * top + config.conf_c3 * margin_norm) / (config.conf_c1 + config.conf_c3)
    value = round(max(0.0, min(1.0, raw)), 4)
    return {"catalog_support": value, "label": catalog_support_label(value, config),
            "genre_support": None if support is None else round(support, 4),
            "margin_norm": round(margin_norm, 4), "disclaimer": DISCLAIMER}


def evaluate(profile: ProfileV2, items: Sequence[RankedItem], *, k: int = 5,
             unresolved_genres: Iterable[str] = (), genres_requested: Optional[bool] = None,
             diversity_applied: bool = True, acknowledged: Iterable[str] = (),
             config: Config = DEFAULT_CONFIG) -> EvaluationReport:
    """Check a ranked list. `acknowledged` flag codes were already handled by a revision:
    they are still reported, but downgraded to info and no longer block `passed`."""
    ack = set(acknowledged)
    unresolved = list(unresolved_genres)
    if genres_requested is None:
        genres_requested = bool(profile.genres) or bool(unresolved)
    flags: List[Flag] = []

    def add(code: str, severity: str, message: str) -> None:
        if code in ack:
            flags.append(Flag(code, "info", message + " (handled by a revision)"))
        else:
            flags.append(Flag(code, severity, message))

    top = items[0].breakdown.fraction if items else 0.0
    last = items[-1].breakdown.fraction if items else 0.0
    if not items or top < config.low_top_score:
        add("LOW_TOP_SCORE", "warn",
            f"Best match covers only {top:.0%} of what you asked for (threshold {config.low_top_score:.0%}).")
    if len(items) >= 2 and (top - last) < config.low_margin:
        add("LOW_MARGIN", "warn",
            f"Top and last results are within {top - last:.1%} of each other; the ordering is nearly arbitrary.")
    if profile.genres and items and all(i.breakdown.genre_credit <= 0 for i in items):
        add("NO_GENRE_SUPPORT", "warn", "None of the recommended songs match or relate to your genre.")
    if unresolved:
        add("UNRESOLVED_GENRE", "warn",
            f"Could not match genre(s) to this catalog: {', '.join(unresolved)}.")
    for rule in config.conflict_rules:
        if matches_conflict_rule(profile, rule):
            add("CONFLICTING_PREFERENCES", "warn",
                "Your mood, energy or acoustic settings pull in opposite directions "
                f"(rule {rule['id']}); results are a compromise.")
            break
    if profile.energy is not None:
        for rank, item in enumerate(items[:config.feature_mismatch_top_n], start=1):
            gap = abs(item.song["energy"] - profile.energy)
            if gap > config.feature_mismatch_gap:
                add("FEATURE_MISMATCH", "warn",
                    f"'{item.song['title']}' ranks #{rank} but its energy {item.song['energy']:.2f} is "
                    f"{gap:.2f} away from your target {profile.energy:.2f}.")
                break
    n_good = sum(1 for i in items if i.breakdown.fraction >= config.min_fraction)
    if n_good < k:
        add("TOO_FEW_RESULTS", "fail" if n_good == 0 else "warn",
            f"Only {n_good} of {k} results score at least {config.min_fraction:.0%}.")
    if not diversity_applied:
        flags.append(Flag("DIVERSITY_SKIPPED_SMALL_CATALOG", "info",
                          f"Catalog has fewer than {config.diversity_min_catalog} songs, so diversity "
                          "re-ranking was skipped."))

    conf = compute_confidence(profile, items, bool(genres_requested), config)
    passed = not any(f.code in LOOP_FLAGS and f.severity != "info" for f in flags)
    metrics = {"top_fraction": round(top, 4), "last_fraction": round(last, 4),
               "margin": round(top - last, 4), "n_above_min": n_good, "n_items": len(items)}
    return EvaluationReport(flags=flags, passed=passed, metrics=metrics, confidence=conf)
