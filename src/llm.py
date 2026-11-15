"""LLM interface. An LLM may parse free text and write explanation text. It never scores,
ranks or selects songs.

MockLLM is a deterministic rule-based TEST DOUBLE, not a model. It exists so the whole project
(tests, evaluation harness, demos) runs offline with no API key. Its results say nothing about
how a real LLM would behave.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional, Protocol, Tuple

from src.config import DEFAULT_CONFIG, Config

log = logging.getLogger("vibify.llm")


class LLMUnavailable(RuntimeError):
    """Raised by a backend that cannot produce a response (no key, network error, timeout, ...)."""


class LLMClient(Protocol):
    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float = 0.0) -> str: ...


# ---------------------------------------------------------------- MockLLM rules
_GENRE_WORDS: List[Tuple[str, str]] = [
    (r"\bk-?pop\b", "k-pop"), (r"\bj-?pop\b", "j-pop"), (r"\bindie\b", "indie pop"), (r"\bpop\b", "pop"),
    (r"\blo-?fi\b", "lofi"), (r"\brock\b", "rock"), (r"\bambient\b", "ambient"), (r"\bjazz", "jazz"),
    (r"\bsynth(?:wave)?\b|\bretro\b", "synthwave"), (r"\bhip[- ]?hop\b|\brap\b", "hip hop"),
    (r"\bclassical\b|\borchestra", "classical"), (r"\bmetal\b", "metal"), (r"\bcountry\b", "country"),
    (r"\br&b\b|\brnb\b|\bsoul\b", "r&b"), (r"\bedm\b|\belectronic\b|\bclub\b|\brave\b", "edm"),
    (r"\breggae\b", "reggae"), (r"\bfolk\b", "folk"), (r"\bblues\b", "blues"),
    # genres that are NOT in the catalog, so unresolved-genre handling can be exercised
    (r"\bbossa nova\b", "bossa nova"), (r"\bgospel\b", "gospel"), (r"\bemo\b", "emo"),
    (r"\bopera\b", "opera"), (r"\bpolka\b", "polka"),
]
_MOOD_WORDS: List[Tuple[str, List[str]]] = [
    (r"\bhappy\b|\bupbeat\b|\bcheerful\b|\bjoy", ["happy"]),
    (r"\bsad\b|\bcry|\bheartbreak", ["sad"]), (r"\brainy\b|\brain\b|\bmelanchol", ["melancholic", "sad"]),
    (r"\bchill\b|\bmellow\b|\bcalm\b", ["chill"]), (r"\brelax", ["relaxed"]),
    (r"\bfocus|\bstudy|\bstudying\b|\bconcentrat", ["focused"]),
    (r"\bangry\b|\brage\b|\baggressive\b", ["angry"]), (r"\bromantic\b|\bdate night\b", ["romantic"]),
    (r"\bnostalgi|\bthrowback", ["nostalgic"]), (r"\bmoody\b|\blate[- ]night\b|\bdark\b", ["moody"]),
    (r"\bintense\b|\bpowerful\b|\bgym\b|\bworkout\b", ["intense"]),
    (r"\beuphori|\bparty\b", ["euphoric"]), (r"\bpeaceful\b|\bsleep|\bmeditat", ["peaceful"]),
    (r"\bconfident\b|\bswagger\b", ["confident"]), (r"\blaid[- ]back\b|\bbeach\b", ["laid-back"]),
]


def mock_parse(text: str) -> Dict:
    """Keyword rules mapping free text to a profile dict (JSON-serializable)."""
    t = text.lower()
    out: Dict = {}
    genres: List[str] = []
    for pat, g in _GENRE_WORDS:
        if re.search(pat, t) and g not in genres:
            genres.append(g)
    if re.search(r"\bstudy|\bstudying\b|\bfocus", t) and "lofi" not in genres and not genres:
        genres.append("lofi")
    moods: List[str] = []
    for pat, ms in _MOOD_WORDS:
        if re.search(pat, t):
            moods += [m for m in ms if m not in moods]
    negated_sleepy = bool(re.search(r"(nothing|not|no|never|isn'?t|without)\s+(too\s+)?(sleepy|boring|slow)", t))
    energy: Optional[float] = None
    if re.search(r"\bgym\b|\bworkout\b|\brun(?:ning)?\b|\bpump|\bhype\b|\bparty\b|\bhigh[- ]energy\b|\bintense\b|\bloud\b", t):
        energy = 0.9
    elif re.search(r"\bstudy|\bstudying\b|\bfocus|\bbackground\b", t):
        energy = 0.4
    elif re.search(r"\bsleep|\bcalm\b|\bchill\b|\brelax|\bquiet\b|\bpeaceful\b|\bmellow\b|\blow[- ]energy\b|\bsad\b|\brain", t):
        energy = 0.3
    elif re.search(r"\blate[- ]night\b|\bmid[- ]energy\b", t):
        energy = 0.5
    if negated_sleepy:
        energy = max(energy if energy is not None else 0.0, 0.55)
        moods = [m for m in moods if m != "peaceful"]
    if re.search(r"\bacoustic\b|\bunplugged\b", t):
        out["likes_acoustic"] = True
    elif re.search(r"\belectronic\b|\bsynth", t):
        out["likes_acoustic"] = False
    if re.search(r"\bupbeat\b|\bhappy\b|\bcheerful\b", t):
        out["valence"] = 0.8
    elif re.search(r"\bsad\b|\bdark\b|\bmelanchol", t):
        out["valence"] = 0.3
    if re.search(r"\bdance|\bparty\b|\bclub\b", t):
        out["danceability"] = 0.85
    m = re.search(r"(\d{2,3})\s*bpm", t)
    if m:
        out["tempo_bpm"] = float(m.group(1))
    elif re.search(r"\bfast\b", t):
        out["tempo_bpm"] = 150.0
    elif re.search(r"\bslow\b", t):
        out["tempo_bpm"] = 70.0
    if genres:
        out["genres"] = genres
    if moods:
        out["moods"] = moods
    if energy is not None:
        out["energy"] = energy
    return out


def mock_explain(data: Dict) -> str:
    """Compose 2-3 sentences strictly from the facts in the prompt data."""
    parts = data.get("strengths", [])[:2]
    if parts:
        first = f"{data['title']} by {data['artist']} ranks here because of " + " and ".join(parts) + "."
    else:
        first = f"{data['title']} by {data['artist']} is the closest remaining fit in this catalog."
    sentences = [first]
    if data.get("compromises"):
        sentences.append("Compromise: " + "; ".join(data["compromises"][:2]) + ".")
    if data.get("source"):
        sentences.append(f"Context from {data['source']}.")
    return " ".join(sentences)


class MockLLM:
    """Deterministic rule-based test double. Not a language model."""
    name = "mock"

    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float = 0.0) -> str:
        if "TASK:PARSE" in system:
            m = re.search(r"<user_text>\n?(.*?)\n?</user_text>", user, re.S)
            return json.dumps(mock_parse(m.group(1) if m else ""))
        if "TASK:EXPLAIN" in system:
            m = re.search(r"<data>\n?(.*?)\n?</data>", user, re.S)
            data = json.loads(m.group(1)) if m else {}
            return mock_explain(data)
        raise LLMUnavailable("MockLLM does not understand this task")


class AnthropicLLM:
    """Optional real backend. Imported lazily; selected only with VIBIFY_LLM=anthropic."""
    name = "anthropic"

    def __init__(self, config: Config = DEFAULT_CONFIG):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic  # lazy: never required for tests or default runs
        except ImportError as exc:
            raise LLMUnavailable("the 'anthropic' package is not installed") from exc
        self._client = anthropic.Anthropic(api_key=key, timeout=config.llm_timeout_s)
        self._model = config.llm_model

    def complete(self, system: str, user: str, *, max_tokens: int, temperature: float = 0.0) -> str:
        last: Optional[Exception] = None
        for _ in range(2):  # one retry
            try:
                msg = self._client.messages.create(model=self._model, max_tokens=max_tokens,
                                                   temperature=temperature, system=system,
                                                   messages=[{"role": "user", "content": user}])
                return "".join(getattr(b, "text", "") for b in msg.content)
            except Exception as exc:  # network, auth, rate limit, timeout...
                last = exc
        raise LLMUnavailable(f"Anthropic call failed: {type(last).__name__}") from last


def get_llm(config: Config = DEFAULT_CONFIG, backend: Optional[str] = None) -> Tuple[LLMClient, Optional[str]]:
    """Select a backend by name (default: config.llm_backend). Returns (client, fallback_reason).

    fallback_reason is None normally, or a short string when a requested backend was unusable and
    MockLLM was substituted.
    """
    choice = (backend or config.llm_backend or "mock").strip().lower()
    if choice == "mock":
        return MockLLM(), None
    if choice == "anthropic":
        try:
            return AnthropicLLM(config), None
        except LLMUnavailable as exc:
            log.warning("anthropic backend unavailable (%s); using MockLLM", exc)
            return MockLLM(), str(exc)
    log.warning("unknown VIBIFY_LLM value %r; using MockLLM", choice)
    return MockLLM(), f"unknown backend {choice!r}"
