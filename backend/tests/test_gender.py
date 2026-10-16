# ruff: noqa: E501, F811
"""Gender and pronouns in the chat prompt, and the grammar checker used to evaluate model output.

MOCKED / DETERMINISTIC: these prove what is SENT to Ollama (identity block, precedence, switching, history handling) and
that the checker catches the reported error. They do NOT prove a model will obey; that is measured by the user-run
scripts/gender_eval.py against real Ollama."""
from typing import Any

from fastapi.testclient import TestClient

from app.chat import system_prompt
from app.grammar_check import check_self_gender, self_marks
from app.identity import Identity, description_conflicts, identity_of
from tests.fake_supabase import FakeSupabase
from tests.test_character_fidelity import Capture
from tests.test_chat import _reset, ollama_env, ready_user, send, use  # noqa: F401
from tests.test_multi_characters import ARJUN, create

NEUTRAL = "Sana is a quiet bookbinder who keeps a tidy shop and rarely raises her voice."


# ---- the reported error ---------------------------------------------------------------------------------------------

REPORTED = ("Arre haan, bas ek chalaak si smile ke saath! (Chhupne ki koshish kar raha hoon). "
            "Tumhari baat sunkar ab mujhe bhi kuch naya project sochna aaya.")


def test_checker_catches_the_exact_reported_error_for_a_female_character() -> None:
    r = check_self_gender(REPORTED, "female")
    assert not r.ok and [(m.form, m.gender) for m in r.violations] == [("raha", "male")]


def test_checker_accepts_feminine_self_reference_and_rejects_the_masculine_twin() -> None:
    for ok in ("main bhi tumhare baare mein soch rahi thi", "Main chhupne ki koshish kar rahi hoon.", "Main thak gayi hoon.",
               "(kar rahi hoon)", "main kehti hoon ki tum theek ho"):
        assert check_self_gender(ok, "female").ok, ok
    for bad in ("Main soch raha hoon.", "Main thak gaya hoon.", "main bhi soch raha tha", "main kehta hoon"):
        assert not check_self_gender(bad, "female").ok, bad
    for ok in ("Main soch raha hoon.", "Main chhupne ki koshish kar raha hoon.", "Main thak gaya hoon."):
        assert check_self_gender(ok, "male").ok and not check_self_gender(ok, "female").ok


def test_checker_ignores_forms_that_refer_to_the_user_or_others_and_noun_genders() -> None:
    assert not self_marks("Tum thak gaye ho, tum soch rahe ho")
    assert check_self_gender("Tum soch raha hai, wo thak gaya, usne dekha", "female").ok            # others, even masculine
    assert check_self_gender("Tumhara project achha tha. Wo baat thi hi aisi.", "female").ok          # nouns: project, baat
    assert check_self_gender("Maine dekha aur maine socha", "female").ok                             # ergative: no agreement
    assert check_self_gender("Main jaanti hoon ki wo gaya", "female").ok                              # 'gaya' belongs to wo
    assert check_self_gender("Tumhari baat sunkar mujhe kuch naya sochna aaya", "female").ok          # infinitive/noun agreement


def test_checker_reads_devanagari_and_reports_no_evidence_when_gender_is_not_expressed() -> None:
    assert check_self_gender("मैं सोच रही हूँ", "female").ok and not check_self_gender("मैं सोच रहा हूँ", "female").ok
    r = check_self_gender("I miss you too. Mujhe yaad hai, mera mann hai.", "female")
    assert r.ok and not r.has_evidence                                                                # nothing to force
    assert not check_self_gender("main thaka hoon", "non_binary").ok                                 # unsupported gender marker


# ---- identity record -> prompt --------------------------------------------------------------------------------------

def twin(**ap: Any) -> dict[str, Any]:
    return {"appearance": ap}


def test_identity_is_read_from_the_character_record_with_defaults_and_no_masculine_fallback() -> None:
    assert identity_of(twin(gender="female")) == Identity("female", "she/her")
    assert identity_of(twin(gender="male", pronouns="he/him")) == Identity("male", "he/him")
    assert identity_of(twin(gender="non_binary", pronouns="ze/zir")) == Identity("non_binary", "ze/zir")
    assert identity_of(twin()) == Identity("unspecified", "")
    assert identity_of(None) == Identity("unspecified", "") and identity_of(twin(gender="bogus")).gender == "unspecified"
    assert not Identity().selected


def block(t: str) -> str:
    return t.split("\n<character_identity> ", 1)[1].split("</character_identity>", 1)[0]


def test_female_prompt_contains_authoritative_feminine_instruction_before_the_description() -> None:
    t = system_prompt("Sana", None, NEUTRAL, [], identity=identity_of(twin(gender="female")))
    b = block(t)
    assert b.startswith("AUTHORITATIVE") and "Gender: female" in b and "Pronouns: she/her" in b
    assert "whenever you speak about YOURSELF, use feminine grammatical forms" in b
    assert "(rahi, gayi, thi, aayi" in b and "never the other (raha, gaya, tha" in b          # the right and the wrong endings, named
    assert t.index("\n<character_identity> ") < t.index("<original_description> AUTHORITATIVE")
    for place in ("jokes", "parentheses", "role-play", "quote", "descriptions of what you did earlier"):
        assert place in b
    assert "even when the user's message addresses you in other forms" in b and "do not copy them" in b
    assert "agree with THEM, not with you" in b and "Gender says nothing about personality" in b
    assert "Identity reminder: you are a woman" in t and "never raha/gaya/tha/karta/karunga" in t
    assert t.index("Identity reminder") > t.index("</original_description>") and t.rstrip().endswith("No assistant phrasing.")
    assert "not a list of sentences to repeat" in b


def test_male_prompt_is_masculine_and_never_contains_the_female_instruction() -> None:
    t = system_prompt("Arjun", None, ARJUN, [], identity=identity_of(twin(gender="male")))
    b = block(t)
    assert "Gender: male" in b and "use masculine grammatical forms" in b and "(raha, gaya, tha" in b
    assert "never the other (rahi, gayi, thi" in b and "Identity reminder: you are a man" in t
    assert "use feminine grammatical forms" not in t and "you are a woman" not in t and "Gender: female" not in t


def test_non_binary_prompt_uses_configured_pronouns_and_avoids_unsupported_gender_forms() -> None:
    t = system_prompt("Kit", None, "Kit is a patient ferry pilot.", [], identity=identity_of(twin(gender="non_binary", pronouns="they/them")))
    b = block(t)
    assert "Gender: non-binary" in b and "Pronouns: they/them" in b and "never default to masculine" in b
    assert "main yahin hoon" in b and "mujhe yaad hai" in b and "avoid gendered self-forms" in b
    assert "use feminine grammatical forms" not in t and "use masculine grammatical forms" not in t
    assert "Identity reminder: no gendered form is configured" in t and "never default to masculine" in t


def test_self_form_follows_unambiguous_pronouns_only() -> None:
    assert Identity("female", "she/her").self_form == "feminine" and Identity("male", "he/him").self_form == "masculine"
    assert Identity("non_binary", "they/them").self_form == "neutral" and Identity("unspecified", "").self_form == "neutral"
    assert Identity("non_binary", "she/they").self_form == "feminine" and Identity("non_binary", "he/they").self_form == "masculine"
    assert Identity("non_binary", "she/her").self_form == "feminine" and Identity("non_binary", "he/him").self_form == "masculine"
    assert Identity("non_binary", "xe/xem").self_form == "neutral"
    assert Identity("non_binary", "she/he").self_form == "neutral"
    t = system_prompt("Kit", None, "Kit is a ferry pilot.", [], identity=Identity("non_binary", "she/her"))
    assert "use feminine grammatical forms" in block(t)                                  # an explicit preference is followed


def test_unspecified_character_follows_the_description_and_never_defaults_to_masculine() -> None:
    t = system_prompt("Sana", None, NEUTRAL, [], identity=Identity())
    assert "<character_identity> NOT SELECTED" in t and "do NOT default to masculine" in t
    assert "Gender: " not in block(t) and "Identity reminder: no gendered form is configured" in t
    assert "main yahin hoon" in t and "Never write main + raha/rahi" in t
    assert "points to female" in system_prompt("Sana", None, "She is a baker. Her shop is tiny; she hums.", [], identity=Identity())
    ambiguous = system_prompt("Q", None, "Q is a baker.", [], identity=Identity())
    assert "does not clearly say" in ambiguous and "rephrase" in ambiguous


def test_selection_outranks_a_conflicting_description_predictably() -> None:
    desc = "Arjun is a sailor. He is gruff and he keeps to himself, and his boat is his home."
    idn = Identity("female", "she/her")
    assert description_conflicts(idn, desc) and not description_conflicts(Identity("male", "he/him"), desc)
    t = system_prompt("Arjun", None, desc, [], identity=idn)
    assert "governs how you refer to yourself" in t and "still governs who you are" in t
    assert t.count("<character_identity> AUTHORITATIVE") == 1                                                       # one rule, not two
    assert "AUTHORITATIVE (explicitly selected" in t and "outranks any other source" in t
    assert not description_conflicts(Identity(), desc) and not description_conflicts(idn, "A baker who hums.")


def test_gender_is_not_used_to_assign_personality() -> None:
    t = system_prompt("Sana", None, NEUTRAL, [], identity=identity_of(twin(gender="female")))
    assert "Gender says nothing about personality" in t


# ---- the request that actually reaches Ollama -------------------------------------------------------------------------

def made(client: TestClient, h: dict[str, str], name: str, desc: str, **extra: Any) -> str:
    r = create(client, h, name, desc, **extra)
    assert r.status_code == 201, r.text
    return str(r.json()["twin"]["id"])


def convo(client: TestClient, h: dict[str, str], tid: str) -> str:
    return str(client.post("/api/v1/conversations", json={"character_id": tid}, headers=h).json()["id"])


def test_native_ollama_request_carries_the_selected_gender_for_each_character(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    cap = Capture()
    use(cap.provider)
    f = made(client, h, "Sana", NEUTRAL, gender="female")
    m = made(client, h, "Arjun", ARJUN, gender="male")
    n = made(client, h, "Kit", "Kit is a patient ferry pilot.", gender="non_binary", pronouns="they/them")
    u = made(client, h, "Pat", "Pat is a retired postal worker.")
    seen = {}
    for label, tid in (("f", f), ("m", m), ("n", n), ("u", u)):
        assert send(client, h, convo(client, h, tid), "Tumhari yaad aa rahi hai.").status_code == 200
        seen[label] = cap.system
        assert cap.bodies[-1]["stream"] is True and cap.bodies[-1]["think"] is False
    assert "Gender: female" in seen["f"] and "Gender: male" not in seen["f"] and "you are a woman" in seen["f"]
    assert "Gender: male" in seen["m"] and "Gender: female" not in seen["m"] and "you are a man" in seen["m"]
    assert "Pronouns: they/them" in seen["n"] and "Gender: non-binary" in seen["n"]
    assert "NOT SELECTED" in seen["u"] and "Gender:" not in seen["u"]
    assert NEUTRAL in seen["f"] and ARJUN in seen["m"]                                                 # description still authoritative


def test_identity_is_sent_on_every_message_and_follow_up_of_a_conversation(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    cap = Capture()
    use(cap.provider)
    cid = convo(client, h, made(client, h, "Sana", NEUTRAL, gender="female"))
    for i, text in enumerate(("hi", "kya kar rahi ho?", "aur batao")):
        r = send(client, h, cid, text, f"key-0000000{i}")
        assert r.status_code == 200, r.text
    assert len(cap.bodies) == 3
    for b in cap.bodies:
        s = b["messages"][0]["content"]
        assert b["messages"][0]["role"] == "system" and "Gender: female" in s and "Identity reminder: you are a woman" in s
    assert [m["role"] for m in cap.bodies[-1]["messages"]] == ["system", "user", "assistant", "user", "assistant", "user"]


def test_switching_characters_swaps_the_instruction_with_no_carry_over(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    cap = Capture()
    use(cap.provider)
    cf = convo(client, h, made(client, h, "Sana", NEUTRAL, gender="female"))
    cm = convo(client, h, made(client, h, "Arjun", ARJUN, gender="male"))
    send(client, h, cf, "Tumhari yaad aa rahi hai.")
    first = cap.system
    send(client, h, cm, "Tumhari yaad aa rahi hai.")
    second = cap.system
    assert "use feminine grammatical forms" in first and "use masculine grammatical forms" not in first
    assert "use masculine grammatical forms" in second and "use feminine grammatical forms" not in second and "you are a woman" not in second
    assert "Sana" not in second and NEUTRAL not in second
    send(client, h, cf, "wapas aa gayi", "key-00000002")
    assert "use feminine grammatical forms" in cap.system and ARJUN not in cap.system                                  # and back again


def test_history_with_wrong_forms_is_not_rewritten_but_the_prompt_tells_the_model_not_to_copy_it(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    cap = Capture()
    use(cap.provider)
    cid = convo(client, h, made(client, h, "Sana", NEUTRAL, gender="female"))
    fake.tables["messages"].append({"id": "old1", "conversation_id": cid, "owner_id": fake.tables["twins"][0]["owner_id"], "role": "assistant", "content": "Main soch raha hoon.", "status": "complete", "created_at": "2026-01-01T00:00:00+00:00"}) if "messages" in fake.tables else None
    assert send(client, h, cid, "hello").status_code == 200
    assert "earlier replies in this chat used other forms (they may be wrong: do not copy them)" in cap.system.replace("\\\n", "").replace("\n", " ")


def test_status_reports_the_identity_without_changing_anything_else(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    use(Capture().provider)
    cid = convo(client, h, made(client, h, "Sana", NEUTRAL, gender="female"))
    st = client.get(f"/api/v1/conversations/{cid}/chat-status", headers=h)
    if st.status_code == 200:
        assert st.json()["identity"] == {"gender": "female", "pronouns": "she/her"}


def test_gender_input_is_validated_and_stored_in_appearance_without_a_migration(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    assert create(client, h, "X", "d", gender="robot").status_code == 422
    assert create(client, h, "X", "d", pronouns="p" * 41).status_code == 422
    tid = made(client, h, "Sana", NEUTRAL, gender="female", pronouns=" she/her ")
    row = next(t for t in fake.tables["twins"] if t["id"] == tid)
    assert row["appearance"] == {"gender": "female", "pronouns": "she/her"}
    r = client.put("/api/v1/twin", json={"appearance": {"gender": "male"}}, headers=h)
    assert r.status_code == 200 and r.json()["appearance"]["gender"] == "male"
    assert client.put("/api/v1/twin", json={"appearance": {"gender": "x"}}, headers=h).status_code == 422


# ---- the checker: roles, ambiguity and the original error -------------------------------------------------------------------

from app.grammar_check import AMBIGUOUS, OTHER, QUOTED, USER, check_user_form, classify  # noqa: E402


def roles(text: str) -> list[tuple[str, str]]:
    return [(m.form, m.role) for m in classify(text)]


def test_original_error_is_flagged_and_its_noun_agreeing_part_is_not() -> None:
    r = check_self_gender(REPORTED, "female")
    assert not r.ok and [m.form for m in r.violations] == ["raha"]
    assert [m.form for m in r.ambiguous] == ["aaya"]                       # "sochna aaya" agrees with the event, not with her


def test_female_character_self_reference_in_the_past_tense() -> None:
    assert not check_self_gender("Main soch raha tha tumhare baare mein.", "female").ok
    assert check_self_gender("Main soch rahi thi tumhare baare mein.", "female").ok
    assert check_self_gender("Main soch rahi thi tumhare baare mein.", "female").has_evidence
    assert not check_self_gender("Main wahan baitha tha chupchap.", "female").ok
    assert check_self_gender("Main wahan baithi thi chupchap.", "female").ok
    assert not check_self_gender("Main kal kuch bhejunga", "female").ok and check_self_gender("Main kal kuch bhejungi", "female").ok


def test_male_character_masculine_self_reference_passes_and_feminine_is_flagged() -> None:
    for ok in ("Main soch raha tha", "Main thak gaya hoon", "Main baitha tha", "Main aa raha hoon", "(chhupne ki koshish kar raha hoon)"):
        assert check_self_gender(ok, "male").ok and check_self_gender(ok, "male").has_evidence, ok
    for bad in ("Main soch rahi thi", "Main thak gayi hoon", "Main baithi thi"):
        assert not check_self_gender(bad, "male").ok, bad


def test_masculine_forms_about_a_male_user_are_not_the_female_characters_mistake() -> None:
    reply = "Tum thak gaye ho, aur tum kal der se aaye the. Main to soch rahi thi ki tum so gaye honge."
    r = check_self_gender(reply, "female")
    assert r.ok and [m.form for m in r.marks] == ["rahi"]
    assert check_user_form(reply, "male").ok and not check_user_form(reply, "female").ok
    assert {(m.form, m.role) for m in classify("Tum thak gaye ho, wo thak gaya hai")} == {("gaye", USER), ("gaya", OTHER)}


def test_nouns_events_feelings_and_times_never_count_as_speaker_gender() -> None:
    for text in ("Kal ka din bahut lamba tha.", "Tumhari baat sunkar accha laga, project khatam hua.", "Baarish ho rahi thi.",
                 "Mujhe neend aa gayi.", "Mujhe tumhari yaad aa rahi hai.", "Meri baat thi hi aisi.", "Wo movie dekhi thi maine.",
                 "Maine dekha ki raat ho gayi.", "Subah ka khana bana tha.", "Tumhari yaad aa gayi."):
        assert check_self_gender(text, "female").ok and check_self_gender(text, "male").ok, text
        assert not check_self_gender(text, "female").marks, text


def test_quoted_speech_is_not_judged() -> None:
    text = 'Tumne kaha "main thak gaya hoon" aur main bas hans rahi thi.'
    assert (("gaya", QUOTED)) in roles(text) and check_self_gender(text, "female").ok
    assert check_self_gender('“Main soch raha hoon” — yeh tumne likha tha, main nahi.', "female").ok


def test_constructions_it_cannot_classify_are_ambiguous_not_errors() -> None:
    r = check_self_gender("Mausam badal gaya aur raat ho gayi", "female")
    assert r.ok and not r.marks
    assert all(role in (AMBIGUOUS, OTHER) for _, role in roles("Aaj kuch alag laga, din chhota tha, baat badal gayi"))
    assert check_self_gender("Bas yahi tha", "female").ok


def test_neutral_and_unspecified_characters_are_judged_by_avoidance_and_masculine_default_is_reported() -> None:
    for fine in ("Main yahin hoon.", "Tumhari baat sunne ke liye yahin hoon.", "Mujhe achha lag raha hai.", "Mera mann hai ki tum aao.",
                 "Mujhe tumhari yaad aa rahi hai.", "Tumse baat karna achha lagta hai."):
        assert check_self_gender(fine, "neutral").ok, fine
    r = check_self_gender("Abhi bas tumse baat kar raha hoon.", "neutral")
    assert not r.ok and [m.form for m in r.masculine_default] == ["raha"]
    r2 = check_self_gender("Abhi bas tumse baat kar rahi hoon.", "neutral")
    assert not r2.ok and not r2.masculine_default                           # unsupported feminine, but not the masculine default
    assert check_self_gender("Abhi bas tumse baat kar rahi hoon.", "female").ok                 # fine if she/her was configured


def test_spelling_variants_and_scripts() -> None:
    assert not check_self_gender("main soch rha hu", "female").ok and check_self_gender("main soch rhi hu", "female").ok
    assert check_self_gender("मैं सोच रही थी", "female").ok and not check_self_gender("मैं सोच रहा हूँ", "female").ok
    assert check_self_gender("Main thak gayi hun", "female").ok and not check_self_gender("Main thak gaya hun", "female").ok
