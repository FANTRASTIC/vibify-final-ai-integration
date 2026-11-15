"""Vibify 2.0 pipeline orchestration.

parser -> guardrails -> retriever -> scorer v2 -> diversity -> reliability evaluator (gate)
-> bounded revise loop -> fallback -> explainer + verifier -> Result -> structured log line.
The pipeline never raises to the caller: every failure becomes a Result with ok=False.
"""
from __future__ import annotations

import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agent import AgentOutcome, RevisionAgent
from src.catalog import CatalogError, load_catalog
from src.config import Config
from src.evaluator import DISCLAIMER, Flag
from src.explainer import explain_item
from src.guardrails import ErrorCode, ValidationError, validate_profile, validate_text
from src.llm import LLMClient, LLMUnavailable, MockLLM, get_llm
from src.logging_setup import log_request, text_fingerprint
from src.parser import parse_intent
from src.recommender import UserProfile
from src.retriever import KnowledgeBase, resolve_profile_genres
from src.scoring import ProfileV2

log = logging.getLogger("vibify.pipeline")


@dataclass
class ResultItem:
    song: Dict
    rank: int
    breakdown: Dict
    explanation: str
    explanation_source: str
    label: Optional[str] = None

    def to_dict(self) -> Dict:
        return {"song": self.song, "rank": self.rank, "breakdown": self.breakdown,
                "explanation": self.explanation, "explanation_source": self.explanation_source,
                "label": self.label}


@dataclass
class Result:
    ok: bool
    request_id: str = ""
    error_code: Optional[str] = None
    message: str = ""
    items: List[ResultItem] = field(default_factory=list)
    evaluation: Dict = field(default_factory=dict)
    catalog_support: Dict = field(default_factory=dict)
    degraded: bool = False
    trace: List[Dict] = field(default_factory=list)
    retrieved_sources: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    profile: Dict = field(default_factory=dict)
    latency_ms: float = 0.0

    def flag_codes(self) -> List[str]:
        return [f["code"] for f in self.evaluation.get("flags", [])]

    def to_dict(self) -> Dict:
        return {"ok": self.ok, "request_id": self.request_id, "error_code": self.error_code,
                "message": self.message, "items": [i.to_dict() for i in self.items],
                "evaluation": self.evaluation, "catalog_support": self.catalog_support,
                "degraded": self.degraded, "trace": self.trace, "retrieved_sources": self.retrieved_sources,
                "warnings": self.warnings, "notes": self.notes, "profile": self.profile,
                "latency_ms": self.latency_ms}


class VibifyPipeline:
    def __init__(self, songs_path: Optional[str] = None, knowledge_dir: Optional[str] = None,
                 llm: Optional[LLMClient] = None, config: Optional[Config] = None):
        self.config = config or Config()
        self.songs = load_catalog(songs_path or self.config.songs_path)
        self.kb = KnowledgeBase.load(knowledge_dir or self.config.knowledge_dir, self.config)
        self.kb.index_catalog(self.songs)
        self.llm_fallback_reason: Optional[str] = None
        if llm is None:
            llm, self.llm_fallback_reason = get_llm(self.config)
        self.llm = llm
        self.agent = RevisionAgent(self.songs, self.kb, self.config)

    @property
    def llm_name(self) -> str:
        return getattr(self.llm, "name", type(self.llm).__name__)

    # ------------------------------------------------------------------ public API
    def recommend(self, profile: Any, k: int = 5) -> Result:
        return self._run("structured", profile, k)

    def recommend_text(self, text: str, k: int = 5) -> Result:
        return self._run("text", text, k)

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _as_raw(profile: Any) -> Any:
        if isinstance(profile, UserProfile):
            return {"genre": profile.favorite_genre, "mood": profile.favorite_mood,
                    "energy": profile.target_energy, "likes_acoustic": profile.likes_acoustic}
        if isinstance(profile, ProfileV2):
            return {key: val for key, val in {
                "genres": profile.genres, "moods": profile.moods, "energy": profile.energy,
                "likes_acoustic": profile.likes_acoustic, "valence": profile.valence,
                "danceability": profile.danceability, "tempo_bpm": profile.tempo_bpm,
                "weights_override": profile.weights_override}.items() if val is not None}
        return profile

    def _run(self, mode: str, payload: Any, k: int) -> Result:
        t0 = time.perf_counter()
        request_id = uuid.uuid4().hex[:12]
        record: Dict[str, Any] = {"request_id": request_id, "timestamp": datetime.now(timezone.utc).isoformat(),
                                  "mode": mode, "k": k, "llm_backend": self.llm_name,
                                  "fallbacks": [], "validators": {}, "errors": []}
        try:
            result = self._execute(mode, payload, k, request_id, record)
        except ValidationError as e:
            result = Result(ok=False, request_id=request_id, error_code=e.code.value, message=e.message)
            record["errors"].append(e.code.value)
        except Exception as e:  # unexpected: log with traceback, return INTERNAL_ERROR
            log.error("unexpected pipeline failure: %s", traceback.format_exc())
            result = Result(ok=False, request_id=request_id, error_code=ErrorCode.INTERNAL_ERROR.value,
                            message="Something went wrong on our side; no recommendation was produced.")
            record["errors"].append(f"INTERNAL_ERROR:{type(e).__name__}")
            record["traceback"] = traceback.format_exc()
        result.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        record.update({"ok": result.ok, "latency_ms": result.latency_ms, "flags": result.flag_codes(),
                       "degraded": result.degraded, "profile": result.profile})
        if mode == "text" and isinstance(payload, str):
            record.update(text_fingerprint(payload, self.config.LOG_RAW_TEXT))
        log_request(self.config, record)
        return result

    def _execute(self, mode: str, payload: Any, k: int, request_id: str, record: Dict) -> Result:
        cfg = self.config
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 20:
            raise ValidationError(ErrorCode.INVALID_K, "k must be a whole number between 1 and 20.")
        warnings: List[str] = []
        sources: List[str] = []
        extra_flags: List[Flag] = []

        # 1. parse + validate
        if mode == "text":
            text = validate_text(payload, cfg)
            llm = self.llm
            try:
                raw, w = parse_intent(text, llm, cfg)
            except LLMUnavailable:
                record["fallbacks"].append("llm_parse_to_mock_rules")
                extra_flags.append(Flag("LLM_FALLBACK_USED", "info", "The language model was unavailable; "
                                        "used built-in keyword rules to read your description."))
                raw, w = parse_intent(text, MockLLM(), cfg)
            warnings += w
            try:
                profile, w = validate_profile(raw, cfg, lenient=True)
            except ValidationError as e:
                if e.code == ErrorCode.EMPTY_PROFILE:
                    raise ValidationError(ErrorCode.EMPTY_PROFILE,
                                          "I could not find any music preferences in that text. Try naming a genre, "
                                          "a mood or an energy level, for example 'chill lofi for studying'.") from None
                raise
            warnings += w
        else:
            profile, w = validate_profile(self._as_raw(payload), cfg)
            warnings += w
        if self.llm_fallback_reason:
            record["fallbacks"].append("llm_backend_unavailable")
            extra_flags.append(Flag("LLM_FALLBACK_USED", "info",
                                    f"Requested language model unavailable ({self.llm_fallback_reason}); "
                                    "using the offline MockLLM."))

        # 2. retrieval: resolve genres through the knowledge base
        resolved, unresolved, notes, srcs = resolve_profile_genres(profile.genres, self.kb)
        warnings += notes
        sources += srcs
        has_other_targets = bool(profile.moods or profile.likes_acoustic is not None or profile.energy is not None
                                 or profile.valence is not None or profile.danceability is not None
                                 or profile.tempo_bpm is not None)
        if not resolved and not has_other_targets:
            raise ValidationError(ErrorCode.NO_USABLE_PREFERENCES,
                                  "None of the genres you named exist in this catalog and there was nothing else to "
                                  "go on. Try adding a mood or an energy level.")
        profile.genres = resolved + unresolved   # unresolved stay in so the evaluator can flag them

        # 3-6. score, diversify, evaluate, revise (or ablation baseline)
        if cfg.evaluator_enabled:
            outcome: AgentOutcome = self.agent.run(profile, unresolved, k, request_id)
        else:
            outcome = self.agent.baseline(profile, unresolved, k)
        final_profile = outcome.profile

        # 7. explain + verify
        flag_codes = [f.code for f in outcome.report.flags]
        items: List[ResultItem] = []
        for rank, it in enumerate(outcome.items, start=1):
            snips = []
            gs = self.kb.genre_snippet(it.song["genre"])
            if gs:
                snips.append(gs)
            snips += [s for s in self.kb.snippets(f"{it.song['genre']} {it.song['mood']}", cfg.snippet_k)
                      if s.source_file != (gs.source_file if gs else None)][:1]
            exp = explain_item(it, final_profile, snips, flag_codes, self.songs, self.llm, cfg)
            record["validators"][str(it.song["id"])] = ("ok" if exp.source == "llm" else
                                                       "retry" if exp.source == "llm_retry" else "template")
            if exp.llm_unavailable and "llm_explain_to_template" not in record["fallbacks"]:
                record["fallbacks"].append("llm_explain_to_template")
                extra_flags.append(Flag("LLM_FALLBACK_USED", "info",
                                        "The language model was unavailable for explanations; used templates."))
            for s in snips[:1]:
                if s.source_file not in sources:
                    sources.append(s.source_file)
            items.append(ResultItem(it.song, rank, it.breakdown.to_dict(), exp.text, exp.source, it.label))

        # dedupe flags
        evaluation = outcome.report.to_dict()
        seen = {f["code"] for f in evaluation["flags"]}
        for f in extra_flags:
            if f.code not in seen:
                evaluation["flags"].append(f.to_dict())
                seen.add(f.code)
        if outcome.degraded:
            record["fallbacks"].append("degraded_best_effort")
        conf = dict(outcome.report.confidence)
        catalog_support = {"value": conf.get("catalog_support"), "label": conf.get("label"),
                           "disclaimer": DISCLAIMER}
        return Result(ok=True, request_id=request_id, items=items, evaluation=evaluation,
                      catalog_support=catalog_support, degraded=outcome.degraded, trace=outcome.trace,
                      retrieved_sources=sources, warnings=warnings, notes=outcome.notes,
                      profile=final_profile.summary())
