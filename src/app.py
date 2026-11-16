"""Streamlit front end for Vibify 2.0.   Run: streamlit run src/app.py

All Streamlit-specific code lives in main(), so `import src.app` is safe in tests.
Thumbs up/down append one JSON line to data/feedback.jsonl (no raw free text is stored).
Cover art is generated locally as inline SVG from each song's own attributes (no external images).
"""
from __future__ import annotations

import html
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

PRESETS = {
    "Late-night study": "late-night study, nothing sleepy",
    "Gym session": "high energy gym workout with electronic music",
    "Rainy day": "sad rainy day, something acoustic",
    "Dance party": "upbeat dance party",
}


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


# ----------------------------------------------------------------------------- visuals
CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1100px;}
.hero {background: linear-gradient(120deg,#6d28d9 0%,#db2777 55%,#f59e0b 100%); border-radius: 22px;
  padding: 28px 32px; margin-bottom: 18px; box-shadow: 0 10px 40px rgba(109,40,217,.35);}
.hero h1 {margin: 0; font-size: 2.4rem; color: #fff; letter-spacing: -0.5px;}
.hero p {margin: 6px 0 0 0; color: rgba(255,255,255,.9); font-size: 1.02rem;}
.stat {background:#1a1530; border:1px solid #2d2650; border-radius:16px; padding:14px 18px;}
.stat .k {font-size:.75rem; text-transform:uppercase; letter-spacing:.08em; color:#9b92c7;}
.stat .v {font-size:1.5rem; font-weight:700; color:#f3f0ff;}
.card {display:flex; gap:18px; background:#1a1530; border:1px solid #2d2650; border-radius:18px;
  padding:16px; margin:12px 0 4px 0; transition: transform .15s, border-color .15s;}
.card:hover {transform: translateY(-2px); border-color:#a78bfa;}
.card .rank {font-size:1.9rem; font-weight:800; color:#a78bfa; width:34px; text-align:center; align-self:center;}
.card .cover {width:104px; height:104px; border-radius:14px; flex:none; overflow:hidden;}
.card .body {flex:1; min-width:0;}
.card .title {font-size:1.15rem; font-weight:700; color:#fff;}
.card .artist {color:#9b92c7; margin-bottom:6px;}
.pill {display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem; font-weight:600;
  margin:0 6px 6px 0; background:#2d2650; color:#ddd6fe;}
.pill.tag {background:#be185d; color:#fff;}
.fitbar {height:8px; background:#2d2650; border-radius:6px; overflow:hidden; margin:6px 0 2px 0;}
.fitbar > div {height:100%; border-radius:6px;}
.fitlabel {font-size:.8rem; color:#9b92c7;}
.why {color:#d9d4f5; font-size:.92rem; margin-top:6px;}
.flag {border-radius:12px; padding:10px 14px; margin:6px 0; font-size:.9rem;}
.flag.warn {background:rgba(245,158,11,.12); border:1px solid rgba(245,158,11,.5); color:#fde68a;}
.flag.info {background:rgba(96,165,250,.10); border:1px solid rgba(96,165,250,.4); color:#bfdbfe;}
.disclaimer {color:#8a82b5; font-size:.8rem;}
@media (max-width: 640px) {.card {flex-wrap: wrap;} .card .rank {display:none;}}
</style>
"""


def _hue(text: str) -> int:
    return sum((i + 1) * ord(c) for i, c in enumerate(text)) % 360


def cover_svg(song: Dict) -> str:
    """Deterministic generated cover art: hue from genre, accent from mood, bars from the song's numbers."""
    h1, h2 = _hue(song["genre"]), (_hue(song["mood"]) + 40) % 360
    vals = [song["energy"], song["danceability"], song["valence"], song["acousticness"], song["energy"],
            song["danceability"], song["valence"]]
    bars = []
    for i, v in enumerate(vals):
        height = 14 + int(v * 56)
        bars.append(f'<rect x="{14 + i * 13}" y="{96 - height}" width="8" height="{height}" rx="4" '
                    f'fill="rgba(255,255,255,{0.45 + 0.4 * v:.2f})"/>')
    gid = f"g{song['id']}"
    return (f'<svg viewBox="0 0 104 104" xmlns="http://www.w3.org/2000/svg"><defs>'
            f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="hsl({h1},70%,45%)"/><stop offset="1" stop-color="hsl({h2},75%,35%)"/>'
            f'</linearGradient></defs><rect width="104" height="104" fill="url(#{gid})"/>'
            f'<circle cx="82" cy="22" r="{10 + int(song["energy"] * 8)}" fill="rgba(255,255,255,0.22)"/>'
            + "".join(bars) + "</svg>")


def fit_color(fraction: float) -> str:
    return "#34d399" if fraction >= 0.75 else "#fbbf24" if fraction >= 0.5 else "#f87171"


def song_card_html(item) -> str:
    e = html.escape
    s, bd = item.song, item.breakdown
    pct = bd["fraction"]
    tag = f'<span class="pill tag">{e(item.label)}</span>' if item.label else ""
    return (f'<div class="card"><div class="rank">{item.rank}</div><div class="cover">{cover_svg(s)}</div>'
            f'<div class="body"><div class="title">{e(s["title"])}</div><div class="artist">{e(s["artist"])}</div>'
            f'{tag}<span class="pill">{e(s["genre"])}</span><span class="pill">{e(s["mood"])}</span>'
            f'<div class="fitbar"><div style="width:{pct * 100:.0f}%;background:{fit_color(pct)}"></div></div>'
            f'<div class="fitlabel">{pct:.0%} fit</div>'
            f'<div class="why">{e(item.explanation)}</div></div></div>')


def stat_html(label: str, value: str) -> str:
    return (f'<div class="stat"><div class="k">{html.escape(label)}</div>'
            f'<div class="v">{html.escape(value)}</div></div>')


def flag_html(flag: Dict) -> str:
    kind = "info" if flag["severity"] == "info" else "warn"
    return (f'<div class="flag {kind}"><b>{html.escape(flag["code"])}</b> &middot; '
            f'{html.escape(flag["message"])}</div>')


def main() -> None:  # pragma: no cover - exercised by tests/test_app.py via Streamlit's AppTest
    import streamlit as st

    from src.pipeline import VibifyPipeline

    st.set_page_config(page_title="Vibify 2.0", page_icon="🎧", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    @st.cache_resource
    def get_pipeline() -> VibifyPipeline:
        return VibifyPipeline()

    pipe = get_pipeline()
    st.markdown('<div class="hero"><h1>🎧 Vibify 2.0</h1><p>Tell us your vibe. Songs are ranked with '
                'transparent math, double-checked before you see them, and every pick is explained.</p></div>',
                unsafe_allow_html=True)

    sb = st.sidebar
    sb.markdown("### Your taste")
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
    go = sb.button("Get recommendations", type="primary", use_container_width=True)
    sb.divider()
    text = sb.text_area("...or describe it in words", max_chars=500, placeholder="late-night study, nothing sleepy")
    parse = sb.button("Parse my description", use_container_width=True)

    if go:
        st.session_state["result"] = pipe.recommend(
            build_profile(genres, moods, energy, acoustic, valence, dance, tempo, overrides))
    elif parse:
        st.session_state["result"] = pipe.recommend_text(text)
    result = st.session_state.get("result")

    if result is None:
        st.markdown("#### Quick start")
        cols = st.columns(len(PRESETS))
        for col, (label, phrase) in zip(cols, PRESETS.items()):
            if col.button(label, key=f"preset-{label}", use_container_width=True):
                st.session_state["result"] = pipe.recommend_text(phrase)
                st.rerun()
        st.info("Pick a preset, set your taste in the sidebar, or describe it in words.")
        return
    if not result.ok:
        st.error(f"{result.error_code}: {result.message}")
        return

    cs = result.catalog_support
    top_fit = result.items[0].breakdown["fraction"] if result.items else 0.0
    c1, c2, c3 = st.columns(3)
    c1.markdown(stat_html("Catalog support", f"{cs['label'].title()} ({cs['value']:.2f})"
                          if cs["value"] is not None else "Unavailable"), unsafe_allow_html=True)
    c2.markdown(stat_html("Best match", f"{top_fit:.0%} fit"), unsafe_allow_html=True)
    c3.markdown(stat_html("Checks", "Passed" if not result.degraded and result.evaluation["passed"]
                          else "Best effort"), unsafe_allow_html=True)
    st.markdown(f'<div class="disclaimer">{html.escape(cs["disclaimer"])}</div>', unsafe_allow_html=True)
    for flag in result.evaluation["flags"]:
        st.markdown(flag_html(flag), unsafe_allow_html=True)
    for note in result.notes + result.warnings:
        st.caption(note)

    if st.toggle("Compare with Vibify 1.0"):
        left, right = st.columns(2)
        left.subheader("Vibify 1.0")
        left.dataframe([{"Rank": n, "Title": s["title"], "Genre": s["genre"]}
                        for n, s in enumerate(v1_view(result.profile, pipe.songs), start=1)], hide_index=True)
        right.subheader("Vibify 2.0")
        right.dataframe([{"Rank": i.rank, "Title": i.song["title"], "Genre": i.song["genre"],
                          "Fit": f"{i.breakdown['fraction']:.0%}"} for i in result.items], hide_index=True)

    st.markdown("### Your recommendations")
    for item in result.items:
        st.markdown(song_card_html(item), unsafe_allow_html=True)
        with st.expander("Score breakdown and feedback"):
            for feat, pts in item.breakdown["points"].items():
                mx = item.breakdown["max_points"][feat]
                st.progress(min(1.0, pts / mx) if mx else 0.0, text=f"{feat}: {pts:.2f} / {mx:g}")
            st.caption(f"Explanation source: {item.explanation_source}")
            b1, b2, _ = st.columns([1, 1, 6])
            for col, label, rating in ((b1, "👍", "up"), (b2, "👎", "down")):
                if col.button(label, key=f"{result.request_id}-{item.song['id']}-{rating}"):
                    record_feedback(result.request_id, item.song["id"], rating, result.profile)
                    st.toast("Thanks, feedback saved.")


if __name__ == "__main__":
    main()
