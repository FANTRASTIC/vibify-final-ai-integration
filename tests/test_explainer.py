import pytest

from src.explainer import (explain_item, strength_phrases, template_explanation, verify_explanation)
from src.llm import LLMUnavailable, MockLLM
from src.rerank import RankedItem
from src.retriever import Snippet
from src.scoring import ProfileV2, score_song_v2


@pytest.fixture()
def setup(songs):
    song = next(s for s in songs if s["title"] == "Sunrise City")
    profile = ProfileV2(genres=["pop"], moods=["happy"], energy=0.8, likes_acoustic=False)
    bd = score_song_v2(profile, song)
    return song, profile, bd, RankedItem(song, bd), [Snippet("genres/pop.md", "Pop is ...", 1.0)]


class Scripted:
    name = "scripted"

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def complete(self, system, user, *, max_tokens, temperature=0.0):
        self.prompts.append(user)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


GOOD = "Sunrise City by Neon Echo has a genre match (pop) and energy 0.82 close to your target 0.80."


def test_verifier_accepts_grounded_text(setup, songs):
    song, profile, bd, _, _ = setup
    assert verify_explanation(GOOD, song, bd, profile, songs).ok


def test_verifier_rejects_unknown_number(setup, songs):
    song, profile, bd, _, _ = setup
    v = verify_explanation("It has energy 0.55 which is great.", song, bd, profile, songs)
    assert not v.ok and "0.55" in v.problems[0]


def test_verifier_accepts_rounding_within_tolerance(setup, songs):
    song, profile, bd, _, _ = setup
    assert verify_explanation("Energy is 0.82 and tempo is 118 BPM.", song, bd, profile, songs).ok


def test_verifier_rejects_other_song_or_artist(setup, songs):
    song, profile, bd, _, _ = setup
    assert not verify_explanation("Better than Gym Hero.", song, bd, profile, songs).ok
    assert not verify_explanation("Sounds like Voltline.", song, bd, profile, songs).ok
    assert verify_explanation("By Neon Echo.", song, bd, profile, songs).ok  # own artist (also on another song)


def test_verifier_rejects_contradicting_claims(songs):
    song = next(s for s in songs if s["title"] == "Iron Verdict")
    profile = ProfileV2(genres=["pop"], moods=["happy"], energy=0.9)
    bd = score_song_v2(profile, song)
    assert not verify_explanation("A clear genre match for you.", song, bd, profile, songs).ok
    assert not verify_explanation("A mood match too.", song, bd, profile, songs).ok
    assert not verify_explanation("A related genre pick.", song, bd, profile, songs).ok


def test_verifier_rejects_urls_empty_and_long(setup, songs):
    song, profile, bd, _, _ = setup
    assert not verify_explanation("See https://example.com", song, bd, profile, songs).ok
    assert not verify_explanation("visit www.spam.example", song, bd, profile, songs).ok
    assert not verify_explanation("  ", song, bd, profile, songs).ok
    assert not verify_explanation("word " * 200, song, bd, profile, songs).ok


def test_path_llm_first_try(setup, songs):
    _, profile, _, item, sn = setup
    llm = Scripted(GOOD)
    e = explain_item(item, profile, sn, [], songs, llm)
    assert e.source == "llm" and e.text == GOOD and e.verifier_failures == 0


def test_path_llm_retry_receives_problems(setup, songs):
    _, profile, _, item, sn = setup
    llm = Scripted("Energy is 0.55, like Gym Hero.", GOOD)
    e = explain_item(item, profile, sn, [], songs, llm)
    assert e.source == "llm_retry" and e.text == GOOD
    assert "PROBLEMS" in llm.prompts[1] and "Gym Hero" in llm.prompts[1]
    assert e.verifier_failures == 1


def test_path_template_after_two_failures(setup, songs):
    song, profile, bd, item, sn = setup
    llm = Scripted("Energy 0.55 https://x.example", "Better than Gym Hero")
    e = explain_item(item, profile, sn, [], songs, llm)
    assert e.source == "template" and e.text == template_explanation(item, profile, sn)
    assert e.verifier_failures == 2 and len(e.problems) >= 2
    assert verify_explanation(e.text, song, bd, profile, songs).ok  # the template always passes the verifier


def test_path_template_when_llm_unavailable_or_absent(setup, songs):
    _, profile, _, item, sn = setup
    e = explain_item(item, profile, sn, [], songs, Scripted(LLMUnavailable("down")))
    assert e.source == "template" and e.llm_unavailable
    assert explain_item(item, profile, sn, [], songs, None).source == "template"


def test_mock_llm_explanations_pass_verifier_for_whole_catalog(songs):
    profile = ProfileV2(genres=["pop"], moods=["happy"], energy=0.8, likes_acoustic=False, valence=0.8)
    for song in songs:
        bd = score_song_v2(profile, song, {"pop": {"indie pop": 0.7}})
        item = RankedItem(song, bd)
        e = explain_item(item, profile, [Snippet("genres/x.md", "t", 1)], [], songs, MockLLM())
        assert e.source == "llm", (song["title"], e.problems)


def test_explanation_cites_source_and_names_strengths(setup, songs):
    _, profile, _, item, sn = setup
    e = explain_item(item, profile, sn, [], songs, MockLLM())
    assert "genres/pop.md" in e.text and "genre match (pop)" in e.text
    assert strength_phrases(item, profile)[0].startswith("genre match")
