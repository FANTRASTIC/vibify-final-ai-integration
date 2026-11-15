"""Bounded plan -> act -> evaluate -> revise loop (agentic workflow).

No LLM is involved here: every action comes from a fixed menu keyed by evaluator flag.
The loop runs at most config.max_revisions revisions, records every step in a trace, keeps the
best-evaluated attempt and, if that attempt still fails, returns it marked degraded.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from src.config import DEFAULT_CONFIG, Config
from src.evaluator import EvaluationReport, LOOP_FLAGS, evaluate
from src.logging_setup import append_jsonl
from src.rerank import RankedItem, diversify
from src.retriever import KnowledgeBase
from src.scoring import ProfileV2, effective_weights, rank_v2

# Order in which unhandled flags are addressed (one action per revision).
PRIORITY = ("UNRESOLVED_GENRE", "CONFLICTING_PREFERENCES", "NO_GENRE_SUPPORT", "FEATURE_MISMATCH",
            "TOO_FEW_RESULTS", "LOW_TOP_SCORE")


@dataclass
class _State:
    profile: ProfileV2
    weights: Dict[str, float]
    neighbor_floor: float
    unresolved: List[str]
    acknowledged: Set[str] = field(default_factory=set)
    notes: List[str] = field(default_factory=list)
    conflict_picks: bool = False
    trim_below_min: bool = False
    genre_dropped: bool = False


@dataclass
class AgentOutcome:
    items: List[RankedItem]
    report: EvaluationReport
    trace: List[Dict]
    notes: List[str]
    degraded: bool
    weights: Dict[str, float]
    profile: ProfileV2


class RevisionAgent:
    def __init__(self, songs: List[Dict], kb: KnowledgeBase, config: Config = DEFAULT_CONFIG):
        self.songs, self.kb, self.config = songs, kb, config

    # ----- act -----
    def _neighbors(self, state: _State) -> Dict[str, Dict[str, float]]:
        out = {}
        for g in state.profile.genres:
            canon = self.kb.resolve_genre(g).canonical if g not in self.kb.genres else g
            if canon is None:
                continue
            out[g] = {n: w for n, w in self.kb.neighbors(canon).items() if w >= state.neighbor_floor}
        return out

    def _attempt(self, state: _State, k: int):
        ranked = rank_v2(state.profile, self.songs, self._neighbors(state), None, state.weights, self.config)
        items, applied = diversify(ranked, k, len(self.songs), self.config)
        if state.conflict_picks:
            items = self._add_conflict_picks(state, ranked, items)
        if state.trim_below_min:
            kept = [i for i in items if i.breakdown.fraction >= self.config.min_fraction]
            items = kept or items[:1]
        report = evaluate(state.profile, items, k=k, unresolved_genres=state.unresolved,
                          genres_requested=bool(state.profile.genres or state.unresolved),
                          diversity_applied=applied, acknowledged=state.acknowledged, config=self.config)
        return items, report

    def _add_conflict_picks(self, state: _State, ranked, items: List[RankedItem]) -> List[RankedItem]:
        items = list(items)
        top10 = ranked[:10]
        present = {i.song["id"]: i for i in items}
        mood_pick = next(((s, b) for s, b in top10 if s["mood"] in state.profile.moods), None)
        target = state.profile.energy
        energy_pick = None
        if target is not None:
            energy_pick = next(((s, b) for s, b in top10 if abs(s["energy"] - target) <= 0.15), None)
        for pick, label in ((mood_pick, "meets-your-mood"), (energy_pick, "meets-your-energy")):
            if pick is None:
                continue
            song, bd = pick
            if song["id"] in present:
                if present[song["id"]].label is None:
                    present[song["id"]].label = label
            else:
                new = RankedItem(song, bd, label)
                items.append(new)
                present[song["id"]] = new
        return items

    def _apply(self, state: _State, flag: str) -> Optional[str]:
        """Apply the menu action for `flag`; return an action name or None if nothing could change."""
        if flag == "UNRESOLVED_GENRE":
            state.profile.genres = [g for g in state.profile.genres if g not in state.unresolved]
            state.genre_dropped = True
            state.acknowledged.add("UNRESOLVED_GENRE")
            state.notes.append("Genre not found in this catalog (" + ", ".join(state.unresolved) +
                               "): ignored it and ranked on your other preferences.")
            return "drop_genre_rescale"
        if flag in ("NO_GENRE_SUPPORT", "LOW_TOP_SCORE"):
            if state.neighbor_floor > self.config.widen_min_neighbor and state.profile.genres:
                state.neighbor_floor = self.config.widen_min_neighbor
                if flag == "NO_GENRE_SUPPORT":
                    state.acknowledged.add(flag)
                state.notes.append("Widened genre matching to related genres.")
                return "widen_related_genres"
            return None
        if flag == "FEATURE_MISMATCH":
            cur = state.weights.get("energy", 0.0)
            new = min(self.config.energy_weight_cap, cur + self.config.energy_boost)
            if new <= cur:
                return None
            state.weights["energy"] = new
            state.notes.append(f"Raised the importance of energy (weight {cur:g} to {new:g}) because a top "
                               "result was far from your target energy.")
            return "boost_energy_weight"
        if flag == "CONFLICTING_PREFERENCES":
            state.conflict_picks = True
            state.acknowledged.add(flag)
            state.notes.append("Your preferences conflict, so results are a compromise; kept your stated numbers "
                               "and added labeled picks that satisfy your mood and your energy.")
            return "keep_numbers_add_labeled_picks"
        if flag == "TOO_FEW_RESULTS":
            state.trim_below_min = True
            state.acknowledged.add(flag)
            state.notes.append("Only the songs that fit well enough are shown; the list was not padded.")
            return "trim_instead_of_pad"
        return None

    # ----- plan / loop -----
    def run(self, profile: ProfileV2, unresolved_genres: List[str], k: int = 5,
            request_id: str = "", base_weights: Optional[Dict[str, float]] = None) -> AgentOutcome:
        cfg = self.config
        state = _State(profile=copy.deepcopy(profile),
                       weights=effective_weights(profile, base_weights or cfg.weights_v2),
                       neighbor_floor=cfg.neighbor_min_default, unresolved=list(unresolved_genres))
        items, report = self._attempt(state, k)
        trace: List[Dict] = [self._entry(0, "initial", None, state.weights, state.weights, report, items)]
        attempts = [(copy.deepcopy(state), items, report, 0)]

        for step in range(1, cfg.max_revisions + 1):
            if report.passed:
                break
            before = dict(state.weights)
            action, reason = None, None
            for flag in PRIORITY:
                if flag in report.codes() and any(f.code == flag and f.severity != "info" for f in report.flags):
                    action = self._apply(state, flag)
                    if action:
                        reason = flag
                        break
            if action is None:
                trace.append(self._entry(step, "no_action_available", None, before, state.weights, report, items))
                break
            items, report = self._attempt(state, k)
            trace.append(self._entry(step, action, reason, before, state.weights, report, items))
            attempts.append((copy.deepcopy(state), items, report, step))

        best_state, best_items, best_report, _ = min(
            attempts, key=lambda a: (self._open_flags(a[2]), -a[2].confidence["catalog_support"], a[3]))
        outcome = AgentOutcome(items=best_items, report=best_report, trace=trace, notes=list(best_state.notes),
                               degraded=not best_report.passed, weights=best_state.weights, profile=best_state.profile)
        if outcome.degraded:
            outcome.notes.append("Some quality checks still did not pass after revising, so treat this list as "
                                 "a best effort rather than a confident match.")
        if len(trace) > 1:   # only log runs where the loop actually did something
            append_jsonl(cfg.trace_file, {"request_id": request_id, "profile": profile.summary(),
                                          "unresolved_genres": list(unresolved_genres), "degraded": outcome.degraded,
                                          "trace": trace})
        return outcome

    @staticmethod
    def _open_flags(report: EvaluationReport) -> int:
        return sum(1 for f in report.flags if f.code in LOOP_FLAGS and f.severity != "info")

    @staticmethod
    def _entry(step, action, reason, before, after, report, items) -> Dict:
        return {"step": step, "action": action, "reason_flag": reason,
                "weights_before": {k: round(v, 3) for k, v in before.items()},
                "weights_after": {k: round(v, 3) for k, v in after.items()},
                "flags_after": [f.code + ("(info)" if f.severity == "info" else "") for f in report.flags],
                "top5_titles": [i.song["title"] for i in items[:5]]}
