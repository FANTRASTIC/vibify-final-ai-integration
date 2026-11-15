"""Explainer and verifier.

The LLM (or MockLLM) may only write explanation text. generate -> verify -> retry once with the
problems listed -> deterministic template. The verifier is plain code, so a hallucinated number,
song or claim cannot reach the user.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from src.config import DEFAULT_CONFIG, Config
from src.llm import LLMClient, LLMUnavailable
from src.rerank import RankedItem
from src.retriever import Snippet
from src.scoring import ProfileV2, ScoreBreakdown

EXPLAINER_SYSTEM = (
    "TASK:EXPLAIN\n"
    "Write 2-3 plain sentences explaining why one song was recommended. Use ONLY the facts in the "
    "<data> block: do not invent numbers, songs, artists or claims, and do not include URLs. Name the "
    "strongest contributing features, mention any compromise, and cite the source file name when one is given."
)

_NUM = re.compile(r"\d+(?:\.\d+)?")
_URL = re.compile(r"https?://|www\.", re.I)


@dataclass
class VerifierResult:
    ok: bool
    problems: List[str] = field(default_factory=list)


@dataclass
class Explanation:
    text: str
    source: str  # llm | llm_retry | template
    problems: List[str] = field(default_factory=list)   # verifier problems seen on the way
    llm_unavailable: bool = False
    verifier_runs: int = 0
    verifier_failures: int = 0


# ------------------------------------------------------------ facts shared by prompt and template
def strength_phrases(item: RankedItem, profile: ProfileV2) -> List[str]:
    """Phrases for the strongest contributing features (best first), built from the breakdown."""
    song, bd = item.song, item.breakdown
    cands = []
    for feat, pts in bd.points.items():
        mx = bd.max_points.get(feat, 0.0)
        if pts <= 0 or mx <= 0:
            continue
        frac = pts / mx
        if feat == "genre":
            phrase = (f"genre match ({song['genre']})" if bd.genre_credit >= 1.0
                      else f"related genre ({song['genre']}, credit {bd.genre_credit:.2f})")
        elif feat == "mood":
            phrase = f"mood match ({song['mood']})"
        elif frac < 0.85:
            continue
        elif feat == "energy":
            phrase = f"energy {song['energy']:.2f} close to your target {profile.energy:.2f}"
        elif feat == "acousticness":
            phrase = (f"acousticness {song['acousticness']:.2f} fitting your "
                      f"{'acoustic' if profile.likes_acoustic else 'non-acoustic'} preference")
        elif feat == "valence":
            phrase = f"valence {song['valence']:.2f} near your target {profile.valence:.2f}"
        elif feat == "danceability":
            phrase = f"danceability {song['danceability']:.2f} near your target {profile.danceability:.2f}"
        else:
            phrase = f"tempo {song['tempo_bpm']:.0f} BPM near your target {profile.tempo_bpm:.0f}"
        cands.append((pts, phrase))
    cands.sort(key=lambda c: -c[0])
    return [p for _, p in cands]


def compromise_phrases(item: RankedItem, profile: ProfileV2, flags: Sequence[str] = ()) -> List[str]:
    song, bd = item.song, item.breakdown
    out: List[str] = []
    if profile.energy is not None and abs(song["energy"] - profile.energy) > 0.2:
        direction = "lower" if song["energy"] < profile.energy else "higher"
        out.append(f"its energy {song['energy']:.2f} is {direction} than the {profile.energy:.2f} you asked for")
    if profile.genres and bd.genre_credit <= 0:
        out.append("it does not match your requested genre")
    elif profile.genres and 0 < bd.genre_credit < 1:
        out.append("it is a related genre rather than an exact match")
    if item.label == "discovery":
        out.append("it is a discovery pick from a different genre")
    return out


def build_prompt_data(item: RankedItem, profile: ProfileV2, snippets: Sequence[Snippet],
                      flags: Sequence[str]) -> Dict:
    return {"title": item.song["title"], "artist": item.song["artist"], "genre": item.song["genre"],
            "mood": item.song["mood"], "strengths": strength_phrases(item, profile),
            "compromises": compromise_phrases(item, profile, flags),
            "source": snippets[0].source_file if snippets else None,
            "snippets": [s.text for s in snippets[:2]], "flags": list(flags)}


def template_explanation(item: RankedItem, profile: ProfileV2, snippets: Sequence[Snippet],
                         flags: Sequence[str] = ()) -> str:
    """Deterministic fallback: the Vibify 1.0 style reason list rendered as a sentence."""
    reasons = strength_phrases(item, profile) or ["closest remaining fit"]
    text = f"Why: {'; '.join(reasons[:3])}."
    comp = compromise_phrases(item, profile, flags)
    if comp:
        text += " Compromise: " + "; ".join(comp[:2]) + "."
    if snippets:
        text += f" Source: {snippets[0].source_file}."
    return text


# ------------------------------------------------------------ verifier
def _allowed_numbers(song: Dict, bd: ScoreBreakdown, profile: ProfileV2) -> List[float]:
    vals: List[float] = []
    for k in ("energy", "valence", "danceability", "acousticness", "tempo_bpm"):
        vals.append(float(song[k]))
    for v in (profile.energy, profile.valence, profile.danceability, profile.tempo_bpm):
        if v is not None:
            vals.append(float(v))
    for v in (0.2, 0.8):   # acoustic targets used by the scorer
        vals.append(v)
    vals += list(bd.points.values()) + list(bd.max_points.values())
    vals += [bd.total, bd.applicable_max, bd.fraction, bd.fraction * 100, round(bd.fraction * 100),
             bd.genre_credit]
    vals += [float(x) for x in _NUM.findall(bd.note)]
    return vals


def verify_explanation(text: str, song: Dict, breakdown: ScoreBreakdown, profile: ProfileV2,
                       catalog: Sequence[Dict], config: Config = DEFAULT_CONFIG) -> VerifierResult:
    problems: List[str] = []
    if not text or not text.strip():
        return VerifierResult(False, ["explanation is empty"])
    if len(text) > config.explanation_max_chars:
        problems.append(f"too long ({len(text)} > {config.explanation_max_chars} characters)")
    if _URL.search(text):
        problems.append("contains a URL")
    allowed = _allowed_numbers(song, breakdown, profile)
    for tok in _NUM.findall(text):
        v = float(tok)
        if not any(abs(v - a) <= 0.0100001 for a in allowed):
            problems.append(f"number {tok} does not match any value in the score breakdown, song or profile")
    low = text.lower()
    own = {song["title"].lower(), song["artist"].lower()}
    for other in catalog:
        if other["id"] == song["id"]:
            continue
        for name in (other["title"], other["artist"]):
            if name.lower() in own:
                continue
            if re.search(r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])", low):
                problems.append(f"mentions another catalog entry: {name}")
    gc = breakdown.genre_credit
    if "genre match" in low and gc < 1.0:
        problems.append("claims a genre match but genre credit is not exact")
    if "related genre" in low and not 0 < gc < 1.0:
        problems.append("claims a related genre but there is no related-genre credit")
    if "mood match" in low and breakdown.points.get("mood", 0.0) <= 0:
        problems.append("claims a mood match but mood points are 0")
    return VerifierResult(not problems, problems)


# ------------------------------------------------------------ generate -> verify -> retry -> template
def explain_item(item: RankedItem, profile: ProfileV2, snippets: Sequence[Snippet], flags: Sequence[str],
                 catalog: Sequence[Dict], llm: Optional[LLMClient], config: Config = DEFAULT_CONFIG) -> Explanation:
    result = Explanation(text="", source="template")
    if llm is not None:
        data = build_prompt_data(item, profile, snippets, flags)
        user = "<data>\n" + json.dumps(data, sort_keys=True) + "\n</data>"
        problems: List[str] = []
        for attempt in range(2):
            prompt = user if attempt == 0 else (
                user + "\nPROBLEMS with your previous answer (fix them):\n- " + "\n- ".join(problems))
            try:
                text = llm.complete(EXPLAINER_SYSTEM, prompt, max_tokens=250, temperature=0.0).strip()
            except Exception:   # LLMUnavailable or any backend failure: fall back to the template
                result.llm_unavailable = True
                break
            verdict = verify_explanation(text, item.song, item.breakdown, profile, catalog, config)
            result.verifier_runs += 1
            if verdict.ok:
                result.text, result.source = text, ("llm" if attempt == 0 else "llm_retry")
                return result
            result.verifier_failures += 1
            problems = verdict.problems
            result.problems += verdict.problems
    result.text = template_explanation(item, profile, snippets, flags)
    result.source = "template"
    return result
