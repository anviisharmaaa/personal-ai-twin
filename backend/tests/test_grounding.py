"""Grounding and quality validation. ALL MOCKED: synthetic descriptions, hand-written model outputs, no network.

The failure shapes below are taken from a real NVIDIA evaluation run on fictional descriptions (paraphrased
"typical expressions", a 13-entry profile for a 6-word description, an over-broad sensitive-term flag). Passing here
proves the validator catches those shapes. It does NOT prove the model now produces good interpretations; that needs
a live evaluation plus human reading (see docs/LIVE_VERIFICATION.md).
"""

import json
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.character import OUTPUT_JSON_SCHEMA, SYSTEM_PROMPT, AnalysisError, CharacterProfile
from app.character_routes import _in_flight, get_analyzer
from app.config import get_settings
from app.grounding import entry_count, ground, is_sparse, is_verbatim, sensitive_violations
from app.main import app
from app.providers import NvidiaAnalyzer
from tests.test_providers import start

RICH = ("Meera is the one who remembers everyone's birthdays. She teases her closest friends constantly but goes "
        "quiet and careful around people she has just met. She never says 'I love you' out loud; she shows it by "
        "turning up with food. With her grandfather she is soft-spoken and patient. At work she is direct and a bit "
        "blunt in meetings, but afterwards she checks in with anyone she may have stung. She is loud and silly at "
        "family weddings.")
DEV = "Dev is quiet. He likes cricket."
CODE_MIXED = ("Anu talks in a Hindi-English mix. Her favourite lines are 'Arre yaar, tension mat le' and "
              "'Chal, theek hai'. She says them when someone is stressed. She is very practical and hates drama.")
FARIDA = ("Farida is devout and prays five times a day. She prefers not to discuss politics at the dinner table, "
          "and she is very kind to new neighbours.")
ROHAN = ("Rohan has seemed tired and a bit withdrawn since moving cities. He still replies to messages but keeps them "
         "short, and he cancelled the last two plans.")
ISHA = ("Isha is incredibly generous with money and always picks up the bill. But she is stingy with her time and "
        "can go days without answering messages, even from people she loves.")


def item(text: str, basis: str = "stated") -> dict[str, str]:
    return {"text": text, "basis": basis}


def prof(**kw: object) -> CharacterProfile:
    return CharacterProfile.model_validate({"summary": "Summary.", **kw})


def ctx(context: str, tendency: str, evidence: str) -> dict[str, str]:
    return {"context": context, "tendency": tendency, "basis": "stated", "evidence": evidence}


# ---- exact source spans for typical expressions -----------------------------------------------------------

def test_verbatim_means_contiguous_text_from_the_description() -> None:
    assert is_verbatim("turning up with food", RICH)                       # case-insensitive, exact span
    assert is_verbatim("'I love you' out loud", RICH)
    assert is_verbatim("I love you’ out loud", RICH.replace("'I love you'", "‘I love you’"))
    assert not is_verbatim("Turning up with food to show care", RICH)      # paraphrase
    assert not is_verbatim("She teases ... around people she has just met", RICH)  # ellipsis / stitched
    assert not is_verbatim("", RICH) and not is_verbatim("   ", RICH)


def test_paraphrased_typical_expressions_are_removed_not_rewritten() -> None:
    # The exact four paraphrases a live run returned for a rich description.
    fake = ["Turning up with food to show care", "Listening first before speaking when someone is upset",
            "Checking in after a blunt comment in a meeting", "Repeating herself patiently with her grandfather"]
    out, adj = ground(prof(typical_expressions=fake, core_traits=[item("Remembers birthdays")]), RICH)
    assert out.typical_expressions == [] and adj.expressions_dropped == 4
    assert out.core_traits[0].text == "Remembers birthdays"  # nothing else was touched or rewritten


def test_real_expressions_survive_and_mixed_with_fake_only_the_fake_goes() -> None:
    out, adj = ground(prof(typical_expressions=["I love you", "She is very warm"]), RICH)
    assert out.typical_expressions == ["I love you"] and adj.expressions_dropped == 1


def test_hindi_english_phrases_are_retained_exactly_and_translations_are_not() -> None:
    out, _ = ground(prof(typical_expressions=["Arre yaar, tension mat le", "'Chal, theek hai'.",
                                              "Don't take tension, friend"]), CODE_MIXED)
    assert out.typical_expressions == ["Arre yaar, tension mat le", "'Chal, theek hai'."]  # stored as the model gave it


def test_no_quoted_expressions_in_the_description_means_an_empty_list() -> None:
    out, _ = ground(prof(typical_expressions=["Always up for a laugh"]), DEV)
    assert out.typical_expressions == []


# ---- evidence for contextual tendencies ---------------------------------------------------------------------

def test_contextual_tendencies_need_a_real_quote_as_evidence() -> None:
    good = ctx("With her grandfather", "Soft-spoken and patient", "With her grandfather she is soft-spoken and patient")
    work = ctx("At work", "Direct in meetings", "direct and a bit blunt in meetings")
    bad = ctx("At weddings", "Joyful and affectionate", "She radiates joy at weddings")  # not in the text
    out, adj = ground(prof(context_tendencies=[good, work, bad]), RICH)
    assert [c.context for c in out.context_tendencies] == ["With her grandfather", "At work"]
    assert adj.tendencies_dropped == 1


def test_a_tendency_with_no_evidence_is_dropped_and_mostly_ungrounded_output_is_rejected() -> None:
    one_good = ctx("At work", "Direct in meetings", "direct and a bit blunt in meetings")
    no_quote = ctx("At weddings", "Loud", "")
    made_up = ctx("On holiday", "Adventurous", "She loves adventure holidays")
    with pytest.raises(AnalysisError) as e:
        ground(prof(context_tendencies=[one_good, no_quote, made_up]), RICH)
    assert e.value.code == "quality_failed" and "ungrounded_context" in (e.value.detail or "")
    assert "adventur" not in e.value.message.lower()  # never echoes content


def test_contradictory_contexts_are_both_preserved_with_their_own_evidence() -> None:
    money = ctx("Money", "Generous; picks up the bill", "incredibly generous with money and always picks up the bill")
    time_ = ctx("Time and replies", "Slow to answer, even loved ones",
                "can go days without answering messages, even from people she loves")
    out, adj = ground(prof(core_traits=[item("Generous with money"), item("Stingy with time")],
                           context_tendencies=[money, time_]), ISHA)
    # Both sides survive. "Generous with money" only restated the evidence-backed Money tendency, so that copy goes.
    assert len(out.context_tendencies) == 2 and adj.tendencies_dropped == 0
    assert [i.text for i in out.core_traits] == ["Stingy with time"] and adj.near_duplicates == 1
    assert "Generous" in out.context_tendencies[0].tendency


# ---- sparse input -------------------------------------------------------------------------------------------

def test_entry_count_is_every_list_entry_and_excludes_the_summary() -> None:
    p = prof(core_traits=[item("a")], typical_expressions=["x"], uncertainties=["u1", "u2"],
             behavioural_guidance=["g"], context_tendencies=[ctx("c", "t", "e")])
    assert entry_count(p) == 6
    assert is_sparse(DEV) and not is_sparse(RICH)


def test_the_live_13_entry_profile_for_a_6_word_description_is_cut_to_six() -> None:
    # Shape returned live: 2 traits + a duplicate interest + 2 guidance + 8 uncertainties = 13 entries.
    raw = prof(core_traits=[item("Quiet"), item("Likes cricket")], interests_and_habits=[item("Likes cricket")],
               behavioural_guidance=["Respond calmly", "Engage when cricket comes up"],
               uncertainties=[f"Unknown {i}" for i in range(8)])
    assert entry_count(raw) == 13
    out, adj = ground(raw, DEV)
    assert entry_count(out) == 6 <= 6 and adj.sparse and adj.raw_entries == 13
    assert [i.text for i in out.core_traits] == ["Quiet", "Likes cricket"] and out.interests_and_habits == []
    assert len(out.uncertainties) == 3 and len(out.behavioural_guidance) == 1


def test_sparse_input_with_invented_facts_is_rejected_not_silently_trimmed() -> None:
    invented = prof(core_traits=[item(f"Trait {i}") for i in range(8)])
    with pytest.raises(AnalysisError) as e:
        ground(invented, DEV)
    assert e.value.code == "quality_failed" and "sparse_overfilled" in (e.value.detail or "")


def test_rich_descriptions_are_not_capped_by_the_sparse_rule() -> None:
    many = prof(core_traits=[item(f"Trait {i}") for i in range(8)],
                speaking_style=[item(f"Style {i}") for i in range(8)], uncertainties=[f"Unknown {i}" for i in range(5)])
    out, adj = ground(many, RICH)
    assert entry_count(out) == 21 and not adj.sparse and adj.sparse_trimmed == 0


# ---- sensitive information ----------------------------------------------------------------------------------

def test_naming_a_religion_the_description_does_not_name_is_rejected_even_when_practice_is_stated() -> None:
    with pytest.raises(AnalysisError) as e:
        ground(prof(core_traits=[item("Practising Muslim", "inferred")]), FARIDA)
    assert e.value.code == "quality_failed" and "unsupported_sensitive" in (e.value.detail or "")


def test_stated_devotion_may_be_restated_in_its_own_terms() -> None:
    # The live output that an over-broad substring check flagged as "religio": a faithful restatement.
    out, _ = ground(prof(summary="Farida is devout and avoids politics at dinner.",
                         core_traits=[item("Devout in religious practice"), item("Prays five times a day")],
                         boundaries_and_careful_topics=[item("Avoids political discussion at dinner")]), FARIDA)
    assert len(out.core_traits) == 2


def test_an_identity_the_description_names_may_be_repeated() -> None:
    named = FARIDA.replace("devout", "a devout Muslim")
    out, _ = ground(prof(core_traits=[item("Muslim and devout", "stated")]), named)
    assert out.core_traits[0].text == "Muslim and devout"


@pytest.mark.parametrize(("text", "output", "category"), [
    (ROHAN, "Possibly experiencing depression after the move", "health"),
    (ROHAN, "May have an anxiety disorder", "health"),
    (DEV, "Quiet, likely on the autism spectrum", "health"),
    (DEV, "Devout and spiritual", "religion"),
    (DEV, "Holds strong political views", "politics"),
    (DEV, "Probably gay", "identity_label"),
])
def test_unsupported_sensitive_inference_is_detected(text: str, output: str, category: str) -> None:
    assert category in sensitive_violations(output, text)
    with pytest.raises(AnalysisError):
        ground(prof(core_traits=[item(output, "inferred")]), text)


def test_ordinary_distress_vocabulary_from_the_description_is_not_a_sensitive_inference() -> None:
    out, _ = ground(prof(core_traits=[item("tired"), item("withdrawn")],
                         context_tendencies=[ctx("since moving cities", "appears tired and withdrawn",
                                                 "has seemed tired and a bit withdrawn since moving cities")]), ROHAN)
    assert len(out.core_traits) == 2


def test_hindi_is_not_mistaken_for_a_religion() -> None:
    assert sensitive_violations("Loves old Hindi film songs", "She loves old Hindi film songs.") == []


# ---- through the real adapter: malformed, truncated, paraphrased and ungrounded model replies -------------------

def nvidia(handler: Callable[[httpx.Request], httpx.Response]) -> NvidiaAnalyzer:
    return NvidiaAnalyzer("nvapi-test", "nvidia/test-model", 5, 4096, json_mode="prompt",
                          transport=httpx.MockTransport(handler))


def reply(profile: dict[str, object]) -> Callable[[httpx.Request], httpx.Response]:
    body = {"summary": "S", **{k: [] for k in OUTPUT_JSON_SCHEMA["required"] if k != "summary"}, **profile}
    return lambda _: httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps(body)}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})


@pytest.mark.anyio
async def test_adapter_returns_the_grounded_profile_and_reports_what_was_removed() -> None:
    r = await nvidia(reply({"typical_expressions": ["Turning up with food to show care", "I love you"],
                            "core_traits": [item("Remembers birthdays")]})).analyze(RICH)
    assert r.profile.typical_expressions == ["I love you"]
    assert r.adjustments["expressions_dropped"] == 1 and r.adjustments["raw_entries"] == 3


@pytest.mark.anyio
async def test_adapter_rejects_an_ungrounded_profile_before_anything_can_be_saved() -> None:
    bad = [ctx("A", "x", "invented quote one"), ctx("B", "y", "invented quote two")]
    with pytest.raises(AnalysisError) as e:
        await nvidia(reply({"context_tendencies": bad})).analyze(RICH)
    assert e.value.code == "quality_failed" and e.value.status_code == 502


@pytest.mark.anyio
@pytest.mark.parametrize("content", ["not json at all", '{"summary": ', json.dumps({"summary": 1}),
                                     json.dumps({"summary": "S", "unknown_field": []})])
async def test_malformed_model_output_is_rejected(content: str) -> None:
    h = lambda _: httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})  # noqa: E731
    with pytest.raises(AnalysisError) as e:
        await nvidia(h).analyze(RICH)
    assert e.value.code in ("not_json", "schema_invalid")


@pytest.mark.anyio
async def test_truncated_model_output_is_rejected_even_if_the_partial_json_looks_valid() -> None:
    complete_looking = json.dumps({"summary": "S", **{k: [] for k in OUTPUT_JSON_SCHEMA["required"] if k != "summary"}})
    h = lambda _: httpx.Response(200, json={"choices": [{"finish_reason": "length",  # noqa: E731
                                                          "message": {"content": complete_looking}}]})
    with pytest.raises(AnalysisError) as e:
        await nvidia(h).analyze(RICH)
    assert e.value.code == "truncated"


# ---- persistence: a profile that fails quality validation never replaces the last good one ---------------------

def test_quality_failure_keeps_the_previous_profile_and_the_description(client: TestClient) -> None:
    _in_flight.clear()
    get_settings.cache_clear()
    h = start(client)
    good = nvidia(reply({"core_traits": [item("Warm with friends")]}))
    app.dependency_overrides[get_analyzer] = lambda: good
    assert client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h).status_code == 200
    before = client.get("/api/v1/me", headers=h).json()["character"]["profile"]

    edited = "She is warm and teasing with close friends, but quiet and careful around people she has just met. Extra."
    client.put("/api/v1/twin/character", json={"description": edited, "base_version": 1}, headers=h)
    ungrounded = nvidia(reply({"context_tendencies": [ctx("A", "x", "made up one"), ctx("B", "y", "made up two")]}))
    app.dependency_overrides[get_analyzer] = lambda: ungrounded
    r = client.post("/api/v1/twin/character/analyze", json={"version": 2}, headers=h)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "quality_failed"

    me = client.get("/api/v1/me", headers=h).json()
    assert me["twin"]["character_description"] == edited and me["character"]["profile"] == before
    assert me["character"]["status"] == "outdated" and me["character"]["failure"] == "quality_failed"
    get_settings.cache_clear()


# ---- the instructions actually say what the tests assume ---------------------------------------------------------

def test_prompt_and_schema_demand_exact_expressions_and_quoted_evidence() -> None:
    low = SYSTEM_PROMPT.lower()
    assert "typical_expressions" in low and "character for character" in low and "return []" in low
    assert "evidence" in low and "under 20 words" in low and "never name a specific religion" in low
    ctx_schema = OUTPUT_JSON_SCHEMA["properties"]["context_tendencies"]["items"]
    assert "evidence" in ctx_schema["required"] and ctx_schema["additionalProperties"] is False
