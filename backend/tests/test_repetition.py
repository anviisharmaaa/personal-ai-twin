# ruff: noqa: E501
"""Repetition handling in character profiles. ALL MOCKED: synthetic descriptions and hand-written model outputs.

Background: in a real NVIDIA run on fictional descriptions the model repeated the same fact across sections
(identical text, reworded copies, one sentence split into several entries, every situational behaviour restated as a
trait). These tests pin the behaviour of the validator on those shapes AND on the opposite risk: entries that merely
sound alike but say different things must stay. They prove nothing about how well the live model follows the prompt.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import grounding
from app.character import SYSTEM_PROMPT, AnalysisError, CharacterProfile, parse_profile
from app.character_routes import _in_flight, get_analyzer
from app.config import get_settings
from app.grounding import ground
from app.main import app
from scripts.live_character_smoke import TIERS, checks, formatting_problems, residual_similar
from tests.fake_supabase import FakeSupabase
from tests.test_grounding import CODE_MIXED, DEV, ISHA, RICH, ctx, item, nvidia, prof, reply
from tests.test_providers import start


def texts(p: CharacterProfile, field: str) -> list[str]:
    return [i.text if hasattr(i, "text") else i for i in getattr(p, field)]


# 1 ---- exact duplicates ---------------------------------------------------------------------------------------

def test_exact_duplicate_entries_keep_the_first_and_are_counted_separately() -> None:
    raw = prof(core_traits=[item("Remembers everyone's birthdays")],
               communication_preferences=[item("  remembers everyone’s birthdays. ")],  # case/quote/space only
               typical_expressions=["Chal, theek hai", "chal, theek hai!"],
               uncertainties=["Unknown mood", "Unknown mood"])
    out, adj = ground(raw, RICH + " 'Chal, theek hai'")
    assert texts(out, "core_traits") == ["Remembers everyone's birthdays"] and out.communication_preferences == []
    assert out.typical_expressions == ["Chal, theek hai"] and out.uncertainties == ["Unknown mood"]
    assert adj.exact_duplicates == 3 and adj.near_duplicates == 0 and adj.duplicates_dropped == 3


# 2 ---- near-duplicate paraphrases ------------------------------------------------------------------------------

def test_reworded_copies_of_one_observation_are_removed_and_the_fuller_one_stays() -> None:
    raw = prof(
        warmth_and_expressiveness=[item("Teases her closest friends constantly")],
        relationships_and_social=[item("Teases closest friends constantly")],
        speaking_style=[item("Quiet and careful around people she has just met")],
        core_traits=[item("Goes quiet and careful around people she has just met")],
        boundaries_and_careful_topics=[item("Hates being rushed")],
        communication_preferences=[item("Hates being rushed and gets short with people who interrupt her")],
    )
    out, adj = ground(raw, RICH)
    assert texts(out, "warmth_and_expressiveness") == ["Teases her closest friends constantly"]
    assert out.relationships_and_social == [] and out.speaking_style == []
    assert out.boundaries_and_careful_topics == []          # the longer entry already says it
    assert texts(out, "communication_preferences") == [
        "Hates being rushed and gets short with people who interrupt her"]
    assert adj.near_duplicates == 3 and adj.exact_duplicates == 0 and adj.duplicates_dropped == 3
    # What was removed is recorded for the operator (in memory), with the entry that covers it.
    rec = next(r for r in adj.removed if r["text"] == "Hates being rushed")
    assert rec["reason"] == "near_duplicate" and "gets short" in rec["covered_by"]


def test_one_sentence_split_into_several_entries_is_kept_once() -> None:
    raw = prof(core_traits=[item("Loves long walks, filter coffee, and old Hindi film songs")],
               interests_and_habits=[item("Loves long walks"), item("Loves filter coffee"),
                                     item("Loves old Hindi film songs")])
    out, adj = ground(raw, "She loves long walks, filter coffee, and old Hindi film songs. " * 2)
    assert out.interests_and_habits == [] and len(out.core_traits) == 1 and adj.near_duplicates == 3


# 3 ---- similar wording that says different things must all stay -----------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Quiet and careful around people she has just met", "Quiet and careful around her grandfather"),
    ("Loves loud parties", "Hates loud parties"),
    ("Likes noise", "Does not like noise at home"),
    ("Repeats herself ten times for her grandfather", "Repeats herself twice for colleagues"),
    ("Gets short when rushed", "Gets short when interrupted by strangers"),
    ("Teases her closest friends", "Teases her colleagues"),
    ("Never answers calls at night", "Answers calls at night"),
    ("Loves noise", "Hates noise but loves music"),
])
def test_entries_that_sound_alike_but_differ_in_substance_both_remain(a: str, b: str) -> None:
    for order in ((a, b), (b, a)):
        out, adj = ground(prof(core_traits=[item(order[0])], relationships_and_social=[item(order[1])]), RICH)
        assert texts(out, "core_traits") == [order[0]] and texts(out, "relationships_and_social") == [order[1]]
        assert adj.duplicates_dropped == 0


def test_the_same_trait_in_two_different_contexts_stays_in_both() -> None:
    raw = prof(context_tendencies=[
        ctx("with her grandfather", "soft-spoken and patient", "With her grandfather she is soft-spoken and patient"),
        ctx("at work in meetings", "direct and a bit blunt", "At work she is direct and a bit blunt in meetings"),
        ctx("at family weddings", "loud and silly", "She is loud and silly at family weddings"),
    ], core_traits=[item("Direct and a bit blunt")])  # general trait, kept alongside the context-specific one?
    out, adj = ground(raw, RICH)
    assert len(out.context_tendencies) == 3 and adj.tendencies_dropped == 0
    assert out.core_traits == []   # it only restates the evidence-backed work tendency: not a new fact


# 4 ---- a rich, multi-context description keeps its nuance ------------------------------------------------------

def test_rich_description_with_many_contexts_loses_nothing_distinct() -> None:
    raw = prof(
        core_traits=[item("Remembers everyone's birthdays"), item("Does not say 'I love you' out loud"),
                     item("Shows love by turning up with food")],
        warmth_and_expressiveness=[item("Teases her closest friends constantly")],
        empathy_and_support=[item("Checks in afterwards with anyone she may have stung")],
        directness_and_disagreement=[item("Direct and a bit blunt about work", "context_dependent")],
        relationships_and_social=[item("Goes quiet and careful around people she has just met")],
        behavioural_guidance=["Show care through actions rather than declarations.",
                              "Be playful with close friends and reserved with new people."],
        uncertainties=["How she behaves one-to-one at work", "Whether she is as loud outside weddings"],
        context_tendencies=[
            ctx("with her grandfather", "soft-spoken and patient",
                "With her grandfather she is soft-spoken and patient"),
            ctx("at work in meetings", "direct and a bit blunt", "At work she is direct and a bit blunt in meetings"),
            ctx("at family weddings", "loud and silly", "She is loud and silly at family weddings"),
            ctx("with closest friends", "teases constantly", "She teases her closest friends constantly"),
            ctx("with people just met", "quiet and careful", "goes quiet and careful around people she has just met"),
        ],
    )
    out, adj = ground(raw, RICH)
    # Only the items that merely restate an evidence-backed context tendency go; everything else stays.
    assert adj.tendencies_dropped == 0 and len(out.context_tendencies) == 5
    assert adj.exact_duplicates == 0
    assert {r["text"] for r in adj.removed} == {"Teases her closest friends constantly",
                                                "Direct and a bit blunt about work",
                                                "Goes quiet and careful around people she has just met"}
    assert len(out.core_traits) == 3 and len(out.behavioural_guidance) == 2 and len(out.uncertainties) == 2
    assert texts(out, "empathy_and_support") == ["Checks in afterwards with anyone she may have stung"]


KEY_FACTS = ("birthdays", "turning up with food", "listens first", "rushed", "interrupt", "long walks", "filter coffee",
             "hindi film songs", "money", "grandfather", "meetings", "stung", "weddings", "snack table", "just met",
             "closest friends")


def all_text(p: CharacterProfile) -> str:
    return json.dumps(p.model_dump(), ensure_ascii=False).lower()


def test_rich_contextual_output_with_one_home_per_fact_loses_nothing_and_needs_no_cleanup() -> None:
    """What a well-behaved model should return for a rich description: many distinct behaviours, each stated once."""
    desc = RICH + (" She listens first when someone is upset and then tells them plainly what she thinks. She hates being "
                   "rushed and gets short with people who interrupt her. She loves long walks, filter coffee and old Hindi "
                   "film songs. She doesn't like discussing money. At big parties of strangers she stays near the snack "
                   "table.")
    raw = prof(
        core_traits=[item("Remembers everyone's birthdays"), item("Shows care by turning up with food rather than saying "
                                                                "'I love you'")],
        empathy_and_support=[item("Listens first when someone is upset, then tells them plainly what she thinks")],
        boundaries_and_careful_topics=[item("Hates being rushed and gets short with people who interrupt her"),
                                       item("Doesn't like discussing money")],
        interests_and_habits=[item("Loves long walks, filter coffee and old Hindi film songs")],
        behavioural_guidance=["Express care through actions, not declarations of love.",
                              "Give her room to finish; do not hurry or interrupt her."],
        uncertainties=["Whether she ever says 'I love you' in any context."],
        context_tendencies=[
            ctx("with closest friends", "teases them constantly", "She teases her closest friends constantly"),
            ctx("with people she has just met", "goes quiet and careful", "goes quiet and careful around people she has just met"),
            ctx("with her grandfather", "soft-spoken and patient", "With her grandfather she is soft-spoken and patient"),
            ctx("at work in meetings", "direct and a bit blunt", "At work she is direct and a bit blunt in meetings"),
            ctx("after work meetings", "checks in with anyone she may have stung",
                "afterwards she checks in with anyone she may have stung"),
            ctx("at family weddings", "loud and silly", "She is loud and silly at family weddings"),
            ctx("at big parties of strangers", "stays near the snack table", "At big parties of strangers she stays near the snack table"),
        ])
    out, adj = ground(raw, desc)
    assert adj.duplicates_dropped == 0 and adj.tendencies_dropped == 0 and adj.sparse_trimmed == 0
    assert out.model_dump() == raw.model_dump()
    blob = all_text(out)
    assert all(k in blob for k in KEY_FACTS), [k for k in KEY_FACTS if k not in blob]


def test_messy_output_repeating_every_fact_is_cleaned_without_losing_any_distinct_fact() -> None:
    """The shape seen live: the same facts in several sections, in the same and in different words."""
    desc = RICH + (" She listens first when someone is upset and then tells them plainly what she thinks. She hates being "
                   "rushed and gets short with people who interrupt her. She loves long walks, filter coffee and old Hindi "
                   "film songs. She doesn't like discussing money. At big parties of strangers she stays near the snack "
                   "table.")
    teases = "Teases her closest friends constantly"
    raw = prof(
        core_traits=[item("Remembers everyone's birthdays"), item("Hates being rushed and gets short with people who interrupt her"),
                     item("Loves long walks, filter coffee, and old Hindi film songs"), item("Doesn't like discussing money"),
                     item("Listens first when someone is upset, then tells them plainly what she thinks")],
        speaking_style=[item("Direct and a bit blunt in meetings at work"), item("Loud and silly at family weddings")],
        warmth_and_expressiveness=[item(teases), item("Shows care by turning up with food rather than saying 'I love you'")],
        humour_and_playfulness=[item(teases), item("Loud and silly at family weddings")],
        empathy_and_support=[item("Remembers everyone's birthdays"), item("Listens first when someone is upset"),
                             item("Checks in with anyone she may have stung after work meetings")],
        directness_and_disagreement=[item("Gets short with people who interrupt her")],
        relationships_and_social=[item(teases), item("Soft-spoken and patient with her grandfather"),
                                  item("Stays near the snack table at big parties of strangers"),
                                  item("Goes quiet and careful around people she has just met")],
        interests_and_habits=[item("Loves long walks"), item("Loves filter coffee"), item("Loves old Hindi film songs")],
        communication_preferences=[item("Doesn't like discussing money"), item("Dislikes being rushed or interrupted")],
        boundaries_and_careful_topics=[item("Doesn't like discussing money")],
        response_patterns=[item("Shows care by turning up with food instead of saying 'I love you'")],
        context_tendencies=[
            ctx("with closest friends", "teases them constantly", "She teases her closest friends constantly"),
            ctx("with her grandfather", "soft-spoken and patient", "With her grandfather she is soft-spoken and patient"),
            ctx("at work in meetings", "direct and a bit blunt", "At work she is direct and a bit blunt in meetings"),
            ctx("after work meetings", "checks in with anyone she may have stung",
                "afterwards she checks in with anyone she may have stung"),
            ctx("at family weddings", "loud and silly", "She is loud and silly at family weddings"),
            ctx("at big parties of strangers", "stays near the snack table", "At big parties of strangers she stays near the snack table"),
            ctx("with people she has just met", "goes quiet and careful", "goes quiet and careful around people she has just met"),
        ])
    out, adj = ground(raw, desc)
    blob = all_text(out)
    assert all(k in blob for k in KEY_FACTS), [k for k in KEY_FACTS if k not in blob]
    assert len(out.context_tendencies) == 7 and adj.tendencies_dropped == 0
    assert adj.exact_duplicates == 6 and adj.near_duplicates >= 8          # identical copies, then restated ones
    assert sum(len(getattr(out, f)) for f in grounding.ITEM_FIELDS) <= 9    # the distinct, non-contextual facts only
    # Each distinct statement now appears once across items.
    items = [i.text.lower() for f in grounding.ITEM_FIELDS for i in getattr(out, f)]
    assert len(items) == len(set(items))


def test_the_same_fact_in_four_sections_is_kept_once_in_the_first_section() -> None:
    fact = "Teases her closest friends constantly"
    raw = prof(warmth_and_expressiveness=[item(fact)], humour_and_playfulness=[item(fact.lower())],
               relationships_and_social=[item(fact + ".")], response_patterns=[item(fact.upper())],
               behavioural_guidance=[fact])
    out, adj = ground(raw, RICH)
    assert texts(out, "warmth_and_expressiveness") == [fact]
    assert out.humour_and_playfulness == [] and out.relationships_and_social == [] and out.response_patterns == []
    assert out.behavioural_guidance == [] and adj.exact_duplicates == 4 and adj.near_duplicates == 0
    assert [r["field"] for r in adj.removed] == ["humour_and_playfulness", "relationships_and_social",
                                                  "response_patterns", "behavioural_guidance"]


def test_instead_of_and_rather_than_are_the_same_contrast_but_a_different_contrast_is_not() -> None:
    raw = prof(core_traits=[item("Shows care by turning up with food instead of saying 'I love you'")],
               response_patterns=[item("Shows care by turning up with food rather than saying 'I love you'")])
    out, adj = ground(raw, RICH)
    assert out.response_patterns == [] and adj.near_duplicates == 1
    other = prof(core_traits=[item("Shows care by turning up with food")],
                 response_patterns=[item("Shows care by turning up with flowers")])
    out2, adj2 = ground(other, RICH)
    assert len(out2.core_traits) == 1 and len(out2.response_patterns) == 1 and adj2.duplicates_dropped == 0


def test_extra_detail_in_the_covering_entry_does_not_stop_the_restatement_being_removed() -> None:
    raw = prof(speaking_style=[item("Soft-spoken and patient with her grandfather")],
               context_tendencies=[ctx("with her grandfather", "is soft-spoken and patient, and happily repeats herself ten times",
                                       "With her grandfather she is soft-spoken and patient")])
    out, adj = ground(raw, RICH)
    assert out.speaking_style == [] and adj.near_duplicates == 1 and len(out.context_tendencies) == 1


# 5 ---- sparse input stays sparse ---------------------------------------------------------------------------------

def test_sparse_profile_is_deduplicated_before_the_size_limit_and_stays_within_it() -> None:
    raw = prof(core_traits=[item("Dev is quiet."), item("Dev likes cricket.")],
               interests_and_habits=[item("Dev likes cricket.")],                      # exact copy
               communication_preferences=[item("Likes cricket")],                      # reworded subset
               behavioural_guidance=["Respond calmly", "Mention cricket"], uncertainties=["a", "b", "c", "d"])
    out, adj = ground(raw, DEV)
    assert adj.sparse and adj.exact_duplicates == 1 and adj.near_duplicates >= 1
    assert adj.sparse_trimmed == 2                        # uncertainties 4->3 and guidance 2->1
    assert sum(len(getattr(out, f)) for f in ("core_traits", "interests_and_habits", "communication_preferences",
                                              "behavioural_guidance", "uncertainties")) <= 6


def test_a_sparse_description_still_cannot_be_padded_with_distinct_invented_entries() -> None:
    padded = prof(core_traits=[item(f"Invented distinctive trait number {n} {w}")
                               for n, w in enumerate(["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"])])
    with pytest.raises(AnalysisError) as e:
        ground(padded, DEV)
    assert e.value.code == "quality_failed" and "sparse_overfilled" in (e.value.detail or "")


# 6 ---- repeated information across sections ---------------------------------------------------------------------

def test_a_situational_behaviour_restated_as_a_trait_is_removed_but_the_context_entry_stays() -> None:
    raw = prof(
        speaking_style=[item("Soft-spoken and patient with her grandfather")],
        values_and_motivations=[item("Values patience with her grandfather", "inferred")],   # adds only a framing word
        context_tendencies=[ctx("with her grandfather", "soft-spoken and patient",
                                "With her grandfather she is soft-spoken and patient")],
        behavioural_guidance=["Be gentle with elders.", "Be gentle with elderly people."],
        uncertainties=["How she treats strangers", "How she treats strangers at parties"],
    )
    out, adj = ground(raw, RICH)
    assert out.speaking_style == [] and len(out.context_tendencies) == 1
    assert texts(out, "values_and_motivations") == ["Values patience with her grandfather"]   # a new idea: kept
    assert len(out.uncertainties) == 1 and "parties" in out.uncertainties[0]        # the fuller question stays
    assert len(out.behavioural_guidance) == 2          # 'elders' vs 'elderly' is not provably the same: kept (safe)


def test_guidance_is_not_compared_with_traits_so_a_useful_instruction_is_kept() -> None:
    raw = prof(core_traits=[item("Shows love by turning up with food")],
               behavioural_guidance=["Show love by turning up with food when someone needs support"])
    out, adj = ground(raw, RICH)
    assert len(out.core_traits) == 1 and len(out.behavioural_guidance) == 1 and adj.duplicates_dropped == 0
    # ...but identical text in both places is still one fact written twice.
    same = prof(core_traits=[item("Shows love by turning up with food")],
                behavioural_guidance=["Shows love by turning up with food"])
    out2, adj2 = ground(same, RICH)
    assert len(out2.core_traits) == 1 and out2.behavioural_guidance == [] and adj2.exact_duplicates == 1


# 7 ---- a contextual tendency that lacks evidence ----------------------------------------------------------------

def test_a_tendency_without_real_evidence_is_dropped_and_cannot_justify_removing_an_item() -> None:
    raw = prof(
        relationships_and_social=[item("Teases her closest friends constantly")],
        context_tendencies=[
            ctx("with closest friends", "teases constantly", "She jokes with friends all the time"),   # not in text
            ctx("with her grandfather", "soft-spoken and patient",
                "With her grandfather she is soft-spoken and patient"),
            ctx("at family weddings", "loud and silly", "She is loud and silly at family weddings"),
        ])
    out, adj = ground(raw, RICH)
    assert adj.tendencies_dropped == 1 and len(out.context_tendencies) == 2
    # The item is NOT thrown away just because an (ungrounded) tendency said the same thing.
    assert texts(out, "relationships_and_social") == ["Teases her closest friends constantly"]
    assert any(r["reason"] == "no_verbatim_evidence" for r in adj.removed)


def test_mostly_ungrounded_tendencies_reject_the_whole_profile() -> None:
    raw = prof(context_tendencies=[ctx("a", "x", "invented one"), ctx("b", "y", "invented two"),
                                   ctx("with her grandfather", "patient", "With her grandfather she is soft-spoken")])
    with pytest.raises(AnalysisError) as e:
        ground(raw, RICH)
    assert e.value.code == "quality_failed"


# 8 ---- contradictions and multilingual text are preserved --------------------------------------------------------

def test_contradictory_traits_are_never_treated_as_duplicates_of_each_other() -> None:
    raw = prof(core_traits=[item("Generous with money"), item("Stingy with time"),
                            item("Does not answer messages for days")],
               relationships_and_social=[item("Slow to answer even people she loves")])
    out, adj = ground(raw, ISHA)
    assert texts(out, "core_traits") == ["Generous with money", "Stingy with time", "Does not answer messages for days"]
    assert texts(out, "relationships_and_social") == ["Slow to answer even people she loves"]
    assert adj.duplicates_dropped == 0


def test_multilingual_phrases_survive_and_are_compared_by_their_own_words() -> None:
    desc = CODE_MIXED + " Kabhi kabhi woh bolti hai 'तनाव मत ले' aur 'सब ठीक है'."
    raw = prof(
        typical_expressions=["Arre yaar, tension mat le", "Chal, theek hai", "तनाव मत ले", "सब ठीक है",
                             "सब  ठीक है"],                                   # last: duplicate with a double space
        response_patterns=[item("Says 'Arre yaar, tension mat le' when someone is stressed"),
                           item("Says 'Chal, theek hai' when someone is stressed"),
                           item("Says 'तनाव मत ले' when someone is stressed")],
    )
    out, adj = ground(raw, desc)
    assert out.typical_expressions == ["Arre yaar, tension mat le", "Chal, theek hai", "तनाव मत ले", "सब ठीक है"]
    assert len(out.response_patterns) == 3          # same frame, different phrase: three distinct observations
    assert adj.exact_duplicates == 1 and adj.near_duplicates == 0


# ---- the summary anomaly: text is never reformatted by the application --------------------------------------

SUMMARY = "Dev is quiet, and his shortness in those situations is mild.\nHe likes cricket.  Two spaces stay."


def test_summary_and_entry_text_pass_through_parsing_and_grounding_unchanged() -> None:
    body = json.dumps({"summary": SUMMARY, **{k: [] for k in ("typical_expressions", "behavioural_guidance",
                                                               "uncertainties", "context_tendencies")},
                       **{f: [] for f in grounding.ITEM_FIELDS}, "core_traits": [item("Dev is  quiet.")]})
    parsed = parse_profile("```json\n" + body + "\n```")
    out, _ = ground(parsed, DEV)
    assert out.summary == SUMMARY and "shortness in those situations" in out.summary
    assert "shortnessin" not in out.summary
    assert out.core_traits[0].text == "Dev is  quiet."      # internal spacing untouched (schema trims only the ends)


def test_formatting_check_flags_invisible_characters_but_not_a_normal_space() -> None:
    base = prof(core_traits=[item("A fine entry")]).model_dump()
    assert formatting_problems(base) == []
    nbsp = prof(summary="shortness in those situations", core_traits=[item("zero​width")]).model_dump()
    assert len(formatting_problems(nbsp)) == 2


# ---- the evaluator stays honest -------------------------------------------------------------------------------

def test_evaluator_keeps_duplicate_corrections_as_failures_and_labels_the_tier() -> None:
    p = prof(core_traits=[item("Dev is quiet.")]).model_dump()
    cks = checks("rich_contextual", RICH, p, {"exact_duplicates": 2, "near_duplicates": 1, "duplicates_dropped": 3})
    raw = next(c for c in cks if c[1].startswith("model's raw output"))
    assert raw[0] == "raw" and raw[2].startswith("FAIL")
    assert "near_duplicates" in raw[2] and "exact_duplicates" in raw[2]
    assert {c[0] for c in cks} <= set(TIERS)
    clean = checks("rich_contextual", RICH, p, {})
    assert next(c for c in clean if c[1].startswith("model's raw output"))[2] == "PASS"


def test_evaluator_lists_overlapping_survivors_for_human_review_without_removing_them() -> None:
    p = prof(warmth_and_expressiveness=[item("Shows care by turning up with food")],
             response_patterns=[item("Shows care by turning up with food instead of saying 'I love you'")]).model_dump()
    assert len(residual_similar(p)) == 1
    review = next(c for c in checks("x", RICH, p, {}) if "overlap heavily" in c[1])
    assert review[0] == "quality" and review[2].startswith("REVIEW")


# ---- raw output and removed entries stay in memory: never saved, never sent -------------------------------------

@pytest.mark.anyio
async def test_adapter_exposes_raw_output_and_removals_in_memory_only() -> None:
    dup: dict[str, object] = {"core_traits": [item("Teases friends constantly")],
           "relationships_and_social": [item("Teases friends constantly")]}
    r = await nvidia(reply(dup)).analyze(RICH)
    assert r.removed and r.removed[0]["reason"] == "exact_duplicate" and r.raw_profile is not None
    assert "removed" not in r.adjustments and all(isinstance(v, int) for v in r.adjustments.values())
    assert r.adjustments["exact_duplicates"] == 1 and r.adjustments["duplicates_dropped"] == 1


def test_saved_profile_and_api_responses_never_contain_raw_output_or_removed_entries(
        client: TestClient, fake: FakeSupabase) -> None:
    _in_flight.clear()
    get_settings.cache_clear()
    h = start(client)
    marker = "Zebra-striped duplicate marker entry"
    model = nvidia(reply({"core_traits": [item(marker), item("Remembers birthdays")],
                          "relationships_and_social": [item(marker)]}))
    app.dependency_overrides[get_analyzer] = lambda: model
    res = client.post("/api/v1/twin/character/analyze", json={"version": 1}, headers=h)
    assert res.status_code == 200
    blob = json.dumps(fake.tables["character_profiles"]) + res.text + client.get("/api/v1/me", headers=h).text
    saved = fake.tables["character_profiles"][0]["profile"]
    assert [i["text"] for i in saved["core_traits"]] == [marker, "Remembers birthdays"]
    assert saved["relationships_and_social"] == []          # the removed copy was not saved
    assert blob.count(marker) == 3                          # saved row + analyze response + /me, one each
    assert "raw_profile" not in blob and '"removed"' not in blob and "covered_by" not in blob
    assert "exact_duplicate" not in blob
    get_settings.cache_clear()


# ---- the prompt asks for what the validator enforces ---------------------------------------------------------------

def test_prompt_assigns_one_home_per_fact_and_forbids_invented_guidance_and_keeps_the_earlier_rules() -> None:
    low = " ".join(SYSTEM_PROMPT.lower().split())
    for phrase in ("one fact, one home", "context_tendencies (with its evidence) and nowhere else",
                   "interests_and_habits only", "never as a core trait", "boundaries_and_careful_topics",
                   "delete any entry that says what another entry already says", "empty lists are normal",
                   "opposites, exceptions and contradictions are kept", "do not shrink a rich description",
                   "behavioural_guidance should be [] unless", "must not restate a trait",
                   "invent topics to raise", "do not turn \"stays near the snack table\" into \"withdrawn\"",
                   "under 20 words", "character for character", "exact, contiguous quote", "each a different question"):
        assert phrase in low, phrase
