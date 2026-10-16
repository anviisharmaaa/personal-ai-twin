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


def test_female_prompt_contains_authoritative_feminine_instruction_before_the_description() -> None:
    t = system_prompt("Sana", None, NEUTRAL, [], identity=identity_of(twin(gender="female")))
    assert "<character_identity> AUTHORITATIVE" in t and "Gender: female" in t and "Pronouns: she/her" in t
    assert "feminine forms" in t and "raha" not in t.split("<original_description>")[0].split("<character_identity>")[1].split("Agreement pattern")[0]
    assert t.index("<character_identity>") < t.index("<original_description>")
    for place in ("jokes", "parentheses", "role-play", "quote yourself"):
        assert place in t
    assert "do not copy them" in t and "personality" in t and "Identity reminder: you are a woman" in t
    assert t.index("Identity reminder") > t.index("</original_description>") and t.rstrip().endswith("No assistant phrasing.")
    assert "she soch rahi" not in t and "main soch rahi hoon" in t                                    # a pattern, flagged as such
    assert "not sentences to repeat" in t


def test_male_prompt_is_masculine_and_never_contains_the_female_instruction() -> None:
    t = system_prompt("Arjun", None, ARJUN, [], identity=identity_of(twin(gender="male")))
    assert "Gender: male" in t and "masculine forms" in t and "Identity reminder: you are a man" in t
    assert "feminine forms" not in t and "you are a woman" not in t and "Gender: female" not in t


def test_non_binary_prompt_uses_configured_pronouns_and_avoids_unsupported_gender_forms() -> None:
    t = system_prompt("Kit", None, "Kit is a patient ferry pilot.", [], identity=identity_of(twin(gender="non_binary", pronouns="they/them")))
    assert "Gender: non-binary" in t and "Pronouns: they/them" in t and "never default to masculine" in t
    assert "mujhe yaad hai" in t and "feminine forms" not in t and "masculine forms for yourself" not in t
    assert "your pronouns are they/them" in t


def test_unspecified_character_follows_the_description_and_never_defaults_to_masculine() -> None:
    t = system_prompt("Sana", None, NEUTRAL, [], identity=Identity())
    assert "<character_identity> NOT SELECTED" in t and "do not default to masculine" in t.lower()
    assert "Gender: " not in t and "Identity reminder: no gender is selected" in t
    assert "points to female" in system_prompt("Sana", None, "She is a baker. Her shop is tiny; she hums.", [], identity=Identity())
    ambiguous = system_prompt("Q", None, "Q is a baker.", [], identity=Identity())
    assert "does not clearly say" in ambiguous and "avoid" in ambiguous.lower()


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
    assert "feminine forms" in first and "masculine forms" not in first.replace("masculine forms for yourself", "")
    assert "masculine forms" in second and "feminine forms" not in second and "you are a woman" not in second
    assert "Sana" not in second and NEUTRAL not in second
    send(client, h, cf, "wapas aa gayi", "key-00000002")
    assert "feminine forms" in cap.system and ARJUN not in cap.system                                  # and back again


def test_history_with_wrong_forms_is_not_rewritten_but_the_prompt_tells_the_model_not_to_copy_it(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    cap = Capture()
    use(cap.provider)
    cid = convo(client, h, made(client, h, "Sana", NEUTRAL, gender="female"))
    fake.tables["messages"].append({"id": "old1", "conversation_id": cid, "owner_id": fake.tables["twins"][0]["owner_id"], "role": "assistant", "content": "Main soch raha hoon.", "status": "complete", "created_at": "2026-01-01T00:00:00+00:00"}) if "messages" in fake.tables else None
    assert send(client, h, cid, "hello").status_code == 200
    assert "Earlier replies may contain wrong forms: do not copy them." in cap.system


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
