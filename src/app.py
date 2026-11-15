"""Thin Streamlit front end for Vibify 2.0.   Run: streamlit run src/app.py

All Streamlit-specific code lives in main(), so `import src.app` is safe in tests.
Thumbs up/down append one JSON line to data/feedback.jsonl (no raw free text is stored).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import FEATURES, FEEDBACK_PATH  # noqa: E402
from src.logging_setup import append_jsonl  # noqa: E402
from src.recommender import recommend_songs  # noqa: E402

ACOUSTIC_CHOICES = {"No preference": None, "Likes acoustic": True, "Prefers non-acoustic": False}


def build_profile(genres: List[str], moods: List[str], energy: float, acoustic: Optional[bool],
                  valence: Optional[float], danceability: Optional[float], tempo: Optional[float],
                  overrides: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """Assemble the raw structured profile from UI inputs (validation happens in the pipeline)."""
    raw: Dict[str, Any] = {"genres": genres, "moods": moods, "energy": energy}
    if acoustic is not None:
        raw["likes_acoustic"] = acoustic
    if valence is not None:
        raw["valence"] = valence
    if danceability is not None:
        raw["danceability"] = danceability
    if tempo is not None:
        raw["tempo_bpm"] = tempo
    if overrides:
        raw["weights_override"] = overrides
    return raw


def record_feedback(request_id: str, song_id: int, rating: str, profile_summary: Dict,
                    path: str = FEEDBACK_PATH) -> Dict:
    """Append one feedback line. rating is 'up' or 'down'. Never stores raw free text."""
    if rating not in ("up", "down"):
        raise ValueError("rating must be 'up' or 'down'")
    row = {"timestamp": datetime.now(timezone.utc).isoformat(), "request_id": request_id,
           "song_id": song_id, "rating": rating, "profile_summary": profile_summary}
    append_jsonl(path, row)
    return row


def v1_view(profile: Dict, songs: List[Dict]) -> List[Dict]:
    """Top 5 from the Vibify 1.0 scorer for a (v2-style) profile summary."""
    prefs: Dict[str, Any] = {}
    if profile.get("genres"):
        prefs["genre"] = profile["genres"][0]
    if profile.get("moods"):
        prefs["mood"] = profile["moods"][0]
    if "energy" in profile:
        prefs["energy"] = profile["energy"]
    if "likes_acoustic" in profile:
        prefs["likes_acoustic"] = profile["likes_acoustic"]
    return [s for s, _, _ in recommend_songs(prefs, songs, k=5)]


def main() -> None:  # pragma: no cover - exercised by tests/test_app.py via Streamlit's AppTest
    import streamlit as st

    from src.pipeline import VibifyPipeline

    st.set_page_config(page_title="Vibify 2.0", layout="wide")

    @st.cache_resource
    def get_pipeline() -> VibifyPipeline:
        return VibifyPipeline()

    pipe = get_pipeline()
    st.title("Vibify 2.0")
    st.caption("Content-based music recommender with a reliability evaluator. Ranking is deterministic; "
               "a language model only parses text and phrases explanations.")

    sb = st.sidebar
    sb.header("Your taste")
    sb.caption(f"LLM backend: **{pipe.llm_name}**" + (" (offline test double)" if pipe.llm_name == "mock" else ""))
    genres = sb.multiselect("Genres", pipe.kb.genre_names())
    moods = sb.multiselect("Moods", sorted({s["mood"] for s in pipe.songs}))
    energy = sb.slider("Energy", 0.0, 1.0, 0.6, 0.01)
    use_val = sb.checkbox("Target valence (positivity)")
    valence = sb.slider("Valence", 0.0, 1.0, 0.6, 0.01) if use_val else None
    use_dance = sb.checkbox("Target danceability")
    dance = sb.slider("Danceability", 0.0, 1.0, 0.6, 0.01) if use_dance else None
    use_tempo = sb.checkbox("Target tempo")
    tempo = float(sb.slider("Tempo (BPM)", 40, 220, 110)) if use_tempo else None
    acoustic = ACOUSTIC_CHOICES[sb.radio("Acoustic sound", list(ACOUSTIC_CHOICES), horizontal=True)]
    overrides = None
    with sb.expander("Priorities (advanced)"):
        st.caption("Raise a feature's weight to make it matter more. Each weight is capped at 5.")
        if st.checkbox("Customize priorities"):
            overrides = {f: st.slider(f, 0.0, 5.0, float(pipe.config.weights_v2[f]), 0.5) for f in FEATURES}
    go = sb.button("Get recommendations", type="primary")
    sb.divider()
    text = sb.text_area("...or describe it in words", max_chars=500, placeholder="late-night study, nothing sleepy")
    parse = sb.button("Parse my description")

    if go:
        st.session_state["result"] = pipe.recommend(
            build_profile(genres, moods, energy, acoustic, valence, dance, tempo, overrides))
    elif parse:
        st.session_state["result"] = pipe.recommend_text(text)
    result = st.session_state.get("result")
    if result is None:
        st.info("Choose your taste in the sidebar, or describe it in words, then press a button.")
        return
    if not result.ok:
        st.error(f"{result.error_code}: {result.message}")
        return

    for flag in result.evaluation["flags"]:
        (st.info if flag["severity"] == "info" else st.warning)(f"{flag['code']}: {flag['message']}")
    for note in result.notes + result.warnings:
        st.caption(note)
    cs = result.catalog_support
    if cs["value"] is not None:
        st.metric("Catalog support", f"{cs['label']} ({cs['value']:.2f})")
    st.caption(cs["disclaimer"])
    if result.degraded:
        st.warning("Degraded: best effort after revising. Treat this list with care.")

    rows = [{"Rank": i.rank, "Title": i.song["title"], "Artist": i.song["artist"], "Genre": i.song["genre"],
             "Mood": i.song["mood"], "Fit": f"{i.breakdown['fraction']:.0%}", "Label": i.label or ""}
            for i in result.items]
    compare = st.toggle("Compare with Vibify 1.0")
    if compare:
        left, right = st.columns(2)
        left.subheader("Vibify 1.0")
        left.dataframe([{"Rank": n, "Title": s["title"], "Genre": s["genre"]}
                        for n, s in enumerate(v1_view(result.profile, pipe.songs), start=1)], hide_index=True)
        right.subheader("Vibify 2.0")
        right.dataframe(rows, hide_index=True)
    else:
        st.dataframe(rows, hide_index=True)

    for item in result.items:
        with st.expander(f"{item.rank}. {item.song['title']} - {item.song['artist']}"):
            st.write(item.explanation)
            st.caption(f"Explanation source: {item.explanation_source}")
            st.table([{"Feature": f, "Points": round(p, 2), "Max": item.breakdown["max_points"][f]}
                      for f, p in item.breakdown["points"].items()])
            c1, c2, _ = st.columns([1, 1, 6])
            for col, label, rating in ((c1, "Thumbs up", "up"), (c2, "Thumbs down", "down")):
                if col.button(label, key=f"{result.request_id}-{item.song['id']}-{rating}"):
                    record_feedback(result.request_id, item.song["id"], rating, result.profile)
                    st.toast("Thanks, feedback saved.")


if __name__ == "__main__":
    main()
