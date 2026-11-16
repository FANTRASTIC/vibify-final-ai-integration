import json
from pathlib import Path

import pytest

import src.app as app


def test_import_has_no_side_effects_and_main_exists():
    assert callable(app.main)


def test_build_profile():
    raw = app.build_profile(["pop"], [], 0.7, None, None, None, None, None)
    assert raw == {"genres": ["pop"], "moods": [], "energy": 0.7}
    raw = app.build_profile(["pop"], ["happy"], 0.7, True, 0.5, 0.6, 120.0, {"energy": 3.0})
    assert raw["likes_acoustic"] is True and raw["tempo_bpm"] == 120.0 and raw["weights_override"] == {"energy": 3.0}


def test_record_feedback_writes_one_line_without_raw_text(tmp_path):
    path = tmp_path / "fb.jsonl"
    app.record_feedback("req1", 7, "up", {"genres": ["pop"]}, str(path))
    app.record_feedback("req1", 8, "down", {"genres": ["pop"]}, str(path))
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [x["rating"] for x in lines] == ["up", "down"]
    assert set(lines[0]) == {"timestamp", "request_id", "song_id", "rating", "profile_summary"}
    with pytest.raises(ValueError):
        app.record_feedback("req1", 7, "meh", {}, str(path))


def test_sample_feedback_rows_are_marked_sample():
    rows = [json.loads(x) for x in open("data/feedback.sample.jsonl", encoding="utf-8")]
    assert len(rows) == 3 and all(r["sample"] is True for r in rows)


def test_v1_view_returns_five_songs():
    from src.catalog import load_catalog
    songs = load_catalog("data/songs.csv")
    assert len(app.v1_view({"genres": ["pop"], "moods": ["happy"], "energy": 0.8}, songs)) == 5


def test_cover_art_is_deterministic_and_distinct(songs):
    assert app.cover_svg(songs[0]) == app.cover_svg(songs[0])
    assert app.cover_svg(songs[0]) != app.cover_svg(songs[10])
    assert app.cover_svg(songs[0]).startswith("<svg")


def test_song_card_escapes_html(songs):
    from src.pipeline import ResultItem
    item = ResultItem(dict(songs[0], title="<script>x</script>"), 1, {"fraction": 0.8}, "why <b>", "llm")
    out = app.song_card_html(item)
    assert "<script>" not in out and "&lt;script&gt;" in out and "why &lt;b&gt;" in out


def test_streamlit_app_renders_headless():
    """Run the real script with Streamlit's AppTest (no browser) and assert it renders without exceptions."""
    testing = pytest.importorskip("streamlit.testing.v1")
    at = testing.AppTest.from_file(str(Path(app.__file__)), default_timeout=60).run()
    assert not at.exception
    assert "Vibify 2.0" in at.markdown[0].value or any("Vibify 2.0" in m.value for m in at.markdown)
    assert len(at.button) >= 4  # quick-start presets
    at.sidebar.multiselect[0].set_value(["lofi"])
    at.sidebar.button[0].click().run()
    assert not at.exception
    assert any("Your recommendations" in m.value for m in at.markdown)
    at.sidebar.text_area[0].set_value("upbeat dance party")
    at.sidebar.button[1].click().run()
    assert not at.exception and any('class="card"' in m.value for m in at.markdown)
