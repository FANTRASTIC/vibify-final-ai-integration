import shutil
from pathlib import Path

import pytest

from src.catalog import load_catalog
from src.retriever import KnowledgeBase, KnowledgeBaseError, TfidfIndex, tokenize
from src.scoring import ProfileV2, rank_v2

KB_DIR = "knowledge"


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.load(KB_DIR)


def test_tokenize_drops_stopwords():
    assert tokenize("The Quick, brown FOX!") == ["quick", "brown", "fox"]


def test_tfidf_cosine_prefers_matching_doc():
    idx = TfidfIndex(["red apple fruit", "blue ocean water"])
    s = idx.scores("apple")
    assert s[0] > 0 and s[1] == 0
    assert idx.scores("zzz") == [0.0, 0.0]


def test_all_catalog_genres_have_files(kb):
    genres = {s["genre"] for s in load_catalog("data/songs.csv")}
    assert genres == set(kb.genre_names())
    for g in genres:
        if g != "pop":
            assert kb.genres[g]["aliases"], g


@pytest.mark.parametrize("name,canon,method", [
    ("pop", "pop", "exact"), (" Pop ", "pop", "exact"), ("k-pop", "pop", "alias"),
    ("trip hop", "lofi", "alias"), ("country western", "country", "semantic"),
])
def test_resolve_genre(kb, name, canon, method):
    r = kb.resolve_genre(name)
    assert (r.canonical, r.method) == (canon, method)


def test_resolve_unknown_does_not_force_match(kb):
    for q in ("asdkjfh qwerty", "", "   "):
        r = kb.resolve_genre(q)
        assert r.canonical is None and r.method == "none"


def test_neighbors_are_symmetric_max(kb):
    # pop file lists indie pop=0.70; indie pop file lists pop=0.70
    assert kb.neighbors("pop")["indie pop"] == 0.70
    assert kb.neighbors("indie pop")["pop"] == 0.70
    # reggae lists pop=0.20 but pop does not list reggae: symmetrization adds it
    assert kb.neighbors("pop")["reggae"] == pytest.approx(0.20)
    assert all(0 < w < 1 for g in kb.genre_names() for w in kb.neighbors(g).values())


def test_snippets_cite_source(kb):
    sn = kb.snippets("heavy distorted guitars aggression", k=2)
    assert sn and sn[0].source_file.endswith(".md") and sn[0].score >= sn[-1].score
    assert kb.snippets("zzzzqqqq") == []


def test_catalog_retrieval(kb):
    kb.index_catalog(load_catalog("data/songs.csv"))
    assert kb.search_catalog("Gym Hero")[0]["title"] == "Gym Hero"


def test_bad_header_raises(tmp_path):
    (tmp_path / "genres").mkdir()
    (tmp_path / "genres" / "x.md").write_text("genre: x\nrelated: y=1.5\n---\ntext", encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match="must be in"):
        KnowledgeBase.load(str(tmp_path))
    with pytest.raises(KnowledgeBaseError):
        KnowledgeBase.load(str(tmp_path / "missing"))


def test_changing_related_weight_changes_score_and_rank(tmp_path):
    """RAG is load-bearing: editing a knowledge file changes scores and rankings."""
    songs = load_catalog("data/songs.csv")
    profile = ProfileV2(genres=["indie pop"], energy=0.80)

    def ranking(kbase):
        nb = {"indie pop": kbase.neighbors("indie pop")}
        return rank_v2(profile, songs, nb, k=None)

    base = ranking(KnowledgeBase.load(KB_DIR))
    tmp_kb = tmp_path / "knowledge"
    shutil.copytree(KB_DIR, tmp_kb)
    for f in ("indie-pop.md", "pop.md"):
        p = Path(tmp_kb) / "genres" / f
        p.write_text(p.read_text(encoding="utf-8").replace("pop=0.70", "pop=0.05")
                     .replace("indie pop=0.70", "indie pop=0.05"), encoding="utf-8")
    changed = ranking(KnowledgeBase.load(str(tmp_kb)))

    def info(r, title):
        for i, (s, b) in enumerate(r):
            if s["title"] == title:
                return i, b.total
    rank0, score0 = info(base, "Sunrise City")
    rank1, score1 = info(changed, "Sunrise City")
    assert score1 < score0
    assert rank1 > rank0
