"""Single source of truth for every tunable in Vibify 2.0.

Nothing in here is read from free text or from an LLM: weights and thresholds can only
be changed by editing this file (or passing a Config object in code).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent

# The seven scoring features of Vibify 2.0.
FEATURES = ("genre", "mood", "energy", "acousticness", "valence", "danceability", "tempo")

# Vibify 1.0 weights (reference only; src/recommender.py owns the real DEFAULT_WEIGHTS).
V1_WEIGHTS = {"genre": 2.0, "mood": 1.0, "energy": 2.0, "acoustic": 1.0}

STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i in is it its me my of on or songs song "
    "music that the their this to was with you your often usually typically very more most "
    "than not no so can into also they them which what when who how".split()
)

# Conflict rules: each is checked against a ProfileV2. A rule matches when every present key holds.
CONFLICT_RULES: List[dict] = [
    {"id": "high_energy_calm_mood", "energy_min": 0.8,
     "moods_any": ["sad", "melancholic", "peaceful", "relaxed", "nostalgic"]},
    {"id": "low_energy_intense_mood", "energy_max": 0.3,
     "moods_any": ["intense", "angry", "euphoric"]},
    {"id": "acoustic_extreme_energy", "energy_min": 0.9, "likes_acoustic": True},
]


@dataclass
class Config:
    # --- scoring v2 (sum 10.0) ---
    weights_v2: Dict[str, float] = field(default_factory=lambda: {
        "genre": 2.5, "mood": 1.5, "energy": 2.0, "acousticness": 1.0,
        "valence": 1.0, "danceability": 1.0, "tempo": 1.0})
    neighbor_cap: float = 0.75          # max credit a related (non-exact) genre can earn
    tempo_span: float = 110.0
    acoustic_target_liked: float = 0.8
    acoustic_target_disliked: float = 0.2

    # --- retrieval ---
    semantic_min_similarity: float = 0.12   # below this, an unknown genre stays unresolved
    snippet_k: int = 3

    # --- evaluator thresholds ---
    low_top_score: float = 0.60
    low_margin: float = 0.05
    feature_mismatch_gap: float = 0.35
    feature_mismatch_top_n: int = 3
    min_fraction: float = 0.35
    conflict_rules: List[dict] = field(default_factory=lambda: list(CONFLICT_RULES))

    # --- diversity / discovery ---
    diversity_min_catalog: int = 40
    max_per_artist: int = 1
    max_per_genre: int = 2
    discovery_ratio: float = 0.7

    # --- confidence (catalog_support) ---
    conf_c1: float = 0.5
    conf_c2: float = 0.3
    conf_c3: float = 0.2
    conf_margin_span: float = 0.30
    conf_strong: float = 0.75
    conf_moderate: float = 0.5

    # --- revise loop ---
    max_revisions: int = 2
    energy_boost: float = 1.0
    energy_weight_cap: float = 4.0
    widen_min_neighbor: float = 0.2

    # --- guardrails ---
    text_max_len: int = 500
    max_list_items: int = 5
    tempo_range: tuple = (40.0, 220.0)
    override_max: float = 5.0

    # --- explainer ---
    explanation_max_chars: int = 400

    # --- LLM (environment-selected; mock by default) ---
    llm_backend: str = field(default_factory=lambda: os.environ.get("VIBIFY_LLM", "mock").strip().lower() or "mock")
    llm_model: str = field(default_factory=lambda: os.environ.get("VIBIFY_MODEL", "claude-sonnet-5-5"))
    llm_timeout_s: float = 20.0

    # --- paths ---
    songs_path: str = str(ROOT / "data" / "songs.csv")
    knowledge_dir: str = str(ROOT / "knowledge")
    log_dir: str = str(ROOT / "logs")
    log_max_bytes: int = 1_000_000
    log_backups: int = 3
    LOG_RAW_TEXT: bool = False   # never flip casually: free text may contain personal data

    @property
    def log_file(self) -> str:
        return str(Path(self.log_dir) / "vibify.log")

    @property
    def trace_file(self) -> str:
        return str(Path(self.log_dir) / "agent_traces.jsonl")


DEFAULT_CONFIG = Config()
FEEDBACK_PATH = str(ROOT / "data" / "feedback.jsonl")
