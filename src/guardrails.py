"""Input validation and normalization.

Structured input is strict (out-of-range values are rejected, never silently clamped).
Parser output (untrusted LLM text) uses lenient=True: clamp and record a warning instead.
"""
from __future__ import annotations

import math
import unicodedata
from enum import Enum
from typing import Any, Dict, List, Tuple

from src.config import DEFAULT_CONFIG, FEATURES, Config
from src.scoring import ProfileV2


class ErrorCode(str, Enum):
    EMPTY_PROFILE = "EMPTY_PROFILE"
    EMPTY_TEXT = "EMPTY_TEXT"
    TEXT_TOO_LONG = "TEXT_TOO_LONG"
    CONTROL_CHARACTERS = "CONTROL_CHARACTERS"
    ENERGY_OUT_OF_RANGE = "ENERGY_OUT_OF_RANGE"
    VALENCE_OUT_OF_RANGE = "VALENCE_OUT_OF_RANGE"
    DANCEABILITY_OUT_OF_RANGE = "DANCEABILITY_OUT_OF_RANGE"
    TEMPO_OUT_OF_RANGE = "TEMPO_OUT_OF_RANGE"
    UNKNOWN_KEY = "UNKNOWN_KEY"
    INVALID_TYPE = "INVALID_TYPE"
    TOO_MANY_ITEMS = "TOO_MANY_ITEMS"
    INVALID_WEIGHTS = "INVALID_WEIGHTS"
    INVALID_K = "INVALID_K"
    PARSE_FAILED = "PARSE_FAILED"
    NO_USABLE_PREFERENCES = "NO_USABLE_PREFERENCES"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ValidationError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


ALLOWED_KEYS = {"genres", "moods", "genre", "mood", "energy", "likes_acoustic", "valence",
                "danceability", "tempo_bpm", "weights_override"}
_UNIT = {"energy": ErrorCode.ENERGY_OUT_OF_RANGE, "valence": ErrorCode.VALENCE_OUT_OF_RANGE,
         "danceability": ErrorCode.DANCEABILITY_OUT_OF_RANGE}


def validate_text(text: Any, config: Config = DEFAULT_CONFIG) -> str:
    """Return the stripped text or raise ValidationError."""
    if not isinstance(text, str):
        raise ValidationError(ErrorCode.INVALID_TYPE, "Text input must be a string.")
    cleaned = text.strip()
    if not cleaned:
        raise ValidationError(ErrorCode.EMPTY_TEXT, "Please describe what you want to hear; the text was empty.")
    if len(cleaned) > config.text_max_len:
        raise ValidationError(ErrorCode.TEXT_TOO_LONG,
                              f"Text is {len(cleaned)} characters; the limit is {config.text_max_len}. Please shorten it.")
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in cleaned):
        raise ValidationError(ErrorCode.CONTROL_CHARACTERS, "Text contains control characters, which are not allowed.")
    return cleaned


def _number(raw: Any, name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValidationError(ErrorCode.INVALID_TYPE, f"'{name}' must be a number, got {type(raw).__name__}.")
    if not math.isfinite(raw):
        raise ValidationError(ErrorCode.INVALID_TYPE, f"'{name}' must be a finite number.")
    return float(raw)


def _str_list(raw: Any, name: str, config: Config, lenient: bool, warnings: List[str]) -> List[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValidationError(ErrorCode.INVALID_TYPE, f"'{name}' must be a list of strings.")
    out: List[str] = []
    for item in raw:
        if not isinstance(item, str):
            if lenient:
                warnings.append(f"dropped non-string entry in '{name}'")
                continue
            raise ValidationError(ErrorCode.INVALID_TYPE, f"'{name}' entries must be strings.")
        s = " ".join(item.strip().lower().split())
        if not s:
            if lenient:
                warnings.append(f"dropped empty entry in '{name}'")
                continue
            raise ValidationError(ErrorCode.INVALID_TYPE, f"'{name}' entries must be non-empty strings.")
        if s not in out:
            out.append(s)
    if len(out) > config.max_list_items:
        if lenient:
            warnings.append(f"'{name}' truncated to {config.max_list_items} entries")
            out = out[:config.max_list_items]
        else:
            raise ValidationError(ErrorCode.TOO_MANY_ITEMS,
                                  f"'{name}' has {len(out)} entries; the maximum is {config.max_list_items}.")
    return out


def validate_weights_override(raw: Any, config: Config = DEFAULT_CONFIG) -> Dict[str, float]:
    if not isinstance(raw, dict) or not raw:
        raise ValidationError(ErrorCode.INVALID_WEIGHTS, "weights_override must be a non-empty object.")
    out: Dict[str, float] = {}
    for key, val in raw.items():
        if key not in FEATURES:
            raise ValidationError(ErrorCode.INVALID_WEIGHTS,
                                  f"Unknown weight '{key}'. Allowed: {', '.join(FEATURES)}.")
        v = _number(val, f"weights_override.{key}")
        if not 0.0 <= v <= config.override_max:
            raise ValidationError(ErrorCode.INVALID_WEIGHTS,
                                  f"Weight '{key}' = {v} must be between 0 and {config.override_max:g}.")
        out[key] = v
    if not any(v > 0 for v in out.values()):
        raise ValidationError(ErrorCode.INVALID_WEIGHTS, "At least one weight must be positive.")
    return out


def validate_profile(raw: Any, config: Config = DEFAULT_CONFIG, lenient: bool = False) -> Tuple[ProfileV2, List[str]]:
    """Validate a raw dict and return (ProfileV2, warnings); raise ValidationError on strict failure."""
    warnings: List[str] = []
    if not isinstance(raw, dict):
        raise ValidationError(ErrorCode.INVALID_TYPE, "Profile must be an object/dict.")
    data = dict(raw)
    unknown = [k for k in data if k not in ALLOWED_KEYS]
    if unknown:
        if lenient:
            warnings.append(f"dropped unknown key(s): {', '.join(sorted(map(str, unknown)))}")
            for k in unknown:
                data.pop(k)
        else:
            raise ValidationError(ErrorCode.UNKNOWN_KEY,
                                  f"Unknown field(s): {', '.join(sorted(map(str, unknown)))}. "
                                  f"Allowed: {', '.join(sorted(ALLOWED_KEYS))}.")
    genres = _str_list(data.get("genres", data.get("genre", [])) or [], "genres", config, lenient, warnings)
    moods = _str_list(data.get("moods", data.get("mood", [])) or [], "moods", config, lenient, warnings)

    numbers: Dict[str, Any] = {}
    for name in ("energy", "valence", "danceability"):
        if data.get(name) is None:
            continue
        try:
            val = _number(data[name], name)
        except ValidationError:
            if lenient:
                warnings.append(f"dropped invalid '{name}'")
                continue
            raise
        if not 0.0 <= val <= 1.0:
            if lenient:
                clamped = min(1.0, max(0.0, val))
                warnings.append(f"clamped {name} {val:g} to {clamped:g}")
                val = clamped
            else:
                raise ValidationError(_UNIT[name], f"'{name}' must be between 0 and 1, got {val:g}.")
        numbers[name] = val
    tempo = None
    if data.get("tempo_bpm") is not None:
        try:
            tempo = _number(data["tempo_bpm"], "tempo_bpm")
        except ValidationError:
            if not lenient:
                raise
            warnings.append("dropped invalid 'tempo_bpm'")
        if tempo is not None:
            lo, hi = config.tempo_range
            if not lo <= tempo <= hi:
                if lenient:
                    clamped = min(hi, max(lo, tempo))
                    warnings.append(f"clamped tempo_bpm {tempo:g} to {clamped:g}")
                    tempo = clamped
                else:
                    raise ValidationError(ErrorCode.TEMPO_OUT_OF_RANGE,
                                          f"'tempo_bpm' must be between {lo:g} and {hi:g}, got {tempo:g}.")
    acoustic = data.get("likes_acoustic")
    if acoustic is not None and not isinstance(acoustic, bool):
        if lenient:
            warnings.append("dropped non-boolean 'likes_acoustic'")
            acoustic = None
        else:
            raise ValidationError(ErrorCode.INVALID_TYPE, "'likes_acoustic' must be true, false or null.")
    override = None
    if data.get("weights_override") is not None:
        override = validate_weights_override(data["weights_override"], config)

    if not genres and not moods and not numbers and tempo is None and acoustic is None:
        raise ValidationError(ErrorCode.EMPTY_PROFILE,
                              "The profile has no genre, mood or numeric target. Add at least one preference "
                              "(for example a genre, a mood, or an energy level).")
    profile = ProfileV2(genres=genres, moods=moods, energy=numbers.get("energy"), likes_acoustic=acoustic,
                        valence=numbers.get("valence"), danceability=numbers.get("danceability"),
                        tempo_bpm=tempo, weights_override=override)
    return profile, warnings
