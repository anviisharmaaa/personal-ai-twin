# ruff: noqa: E501, F811
"""Character-centred conversations: each conversation is bound to one character in the database and the server, never
by what the browser says. MOCKED: real OllamaChatProvider over httpx.MockTransport (captures the request body) and
FakeSupabase's RLS approximation. Nothing here is a live check."""
import copy
from typing import Any

from fastapi.testclient import TestClient

from app.conversation_routes import get_chat_provider
from app.main import app
from tests.fake_supabase import FakeSupabase
from tests.test_character_fidelity import Capture
from tests.test_chat import DESC, _reset, new_conversation, ollama_env, parse_sse, ready_user, send, use  # noqa: F401
from tests.test_learning import TEA, ScriptedExtractor, cand, chat_with, enable_learning, extractor, review  # noqa: F401

ARJUN = "Arjun is a gruff retired sailor who speaks in short sentences and distrusts fancy words."
FORGED = "00000000-0000-0000-0000-000000000000"


def second_character(fake: FakeSupabase, user: str, name: str = "Arjun", description: str = ARJUN) -> str:
    """A second character for the same user. The shipped schema allows one per account (unique owner index), so the
    second row is written straight into the fake: this proves the binding logic, it does not create a feature."""
    first = [t for t in fake.tables["twins"] if t["owner_id"] == user][0]
    twin = copy.deepcopy(first)
    twin.update({"id": f"twin-{name.lower()}", "name": name, "character_description": description, "character_version": 1})
    fake.tables["twins"].append(twin)
    return str(twin["id"])


def first_character(fake: FakeSupabase, user: str) -> str:
    return str([t for t in fake.tables["twins"] if t["owner_id"] == user][0]["id"])


def start(client: TestClient, h: dict[str, str], character_id: str | None) -> Any:
    return client.post("/api/v1/conversations", json={"character_id": character_id} if character_id else {}, headers=h)


def test_characters_lists_only_my_characters_with_a_readable_summary(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake, "alice")
    ready_user(client, fake, "bob")
    fake.tables["twins"][1]["name"] = "Bobbie"
    rows = client.get("/api/v1/characters", headers=h).json()["characters"]
    assert [c["name"] for c in rows] == ["Meera"]
    c = rows[0]
    assert c["has_description"] is True and c["summary"].startswith(DESC[:40]) and c["profile_state"] == "current"
    assert c["conversation_count"] == 0 and "character_description" not in c
    assert client.get("/api/v1/characters").status_code == 401


def test_a_conversation_is_started_with_the_chosen_character_and_remembers_it(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    mine = first_character(fake, "alice")
    r = start(client, h, mine)
    assert r.status_code == 201 and r.json()["character_id"] == mine
    assert fake.tables["conversations"][0]["twin_id"] == mine                      # stored in the database row
    listed = client.get("/api/v1/conversations", headers=h).json()["conversations"]
    assert listed[0]["character_id"] == mine
    assert client.get("/api/v1/characters", headers=h).json()["characters"][0]["conversation_count"] == 1
    assert start(client, h, None).json()["character_id"] == mine                    # one character: no choice needed


def test_forged_unknown_foreign_or_malformed_character_ids_are_rejected(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    ha = ready_user(client, fake, "alice")
    ready_user(client, fake, "bob")
    bobs = first_character(fake, "bob")
    for bad in (FORGED, bobs, "not an id!", "x" * 64, "1;drop table twins"):
        r = start(client, ha, bad)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "character_not_found", bad
    assert fake.tables["conversations"] == []                                       # nothing was created
    assert client.get("/api/v1/chat/status", params={"character_id": bobs}, headers=ha).status_code == 404
    assert client.get("/api/v1/conversations", params={"character_id": bobs}, headers=ha).status_code == 404


def test_with_two_characters_a_new_conversation_must_say_which(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    arjun = second_character(fake, "alice")
    r = start(client, h, None)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "character_required"
    assert start(client, h, arjun).json()["character_id"] == arjun
    names = [c["name"] for c in client.get("/api/v1/characters", headers=h).json()["characters"]]
    assert names == ["Meera", "Arjun"]


def test_two_characters_of_one_user_never_share_a_description_a_history_or_memories(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    meera, arjun = first_character(fake, "alice"), second_character(fake, "alice")
    cap = Capture()
    use(cap.provider)
    base = {"owner_id": "alice", "category": "preference", "scope": "", "supporting": [], "evidence_type": "explicit_statement", "fingerprint": "f", "status": "active"}
    fake.tables["memories"].append({"id": "m-meera", "twin_id": meera, "statement": "Meera takes chai without sugar", **base})
    fake.tables["memories"].append({"id": "m-arjun", "twin_id": arjun, "statement": "Arjun takes chai with ginger", **base})
    cm = start(client, h, meera).json()["id"]
    ca = start(client, h, arjun).json()["id"]

    assert send(client, h, cm, "chai tell me about chai", "key-meera-0001").status_code == 200
    assert DESC in cap.system and ARJUN not in cap.system
    assert "without sugar" in cap.system and "with ginger" not in cap.system

    assert send(client, h, ca, "chai tell me about chai", "key-arjun-0001").status_code == 200
    assert ARJUN in cap.system and DESC not in cap.system and "Warm with friends" not in cap.system   # Meera's profile too
    assert "with ginger" in cap.system and "without sugar" not in cap.system
    assert [m["content"] for m in cap.bodies[-1]["messages"][1:]] == ["chai tell me about chai"]      # Meera's chat is absent

    assert send(client, h, cm, "and again", "key-meera-0002").status_code == 200                      # back to Meera: still hers
    assert DESC in cap.system and ARJUN not in cap.system
    assert [m["content"] for m in cap.bodies[-1]["messages"][1:]][-1] == "and again"
    assert "Arjun" not in " ".join(m["content"] for m in cap.bodies[-1]["messages"][1:])


def test_each_character_has_its_own_profile_state_and_status(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)                       # Meera has a current profile
    arjun = second_character(fake, "alice")            # Arjun has none
    cap = Capture()
    use(cap.provider)
    st = client.get("/api/v1/chat/status", params={"character_id": arjun}, headers=h).json()
    assert st["character_id"] == arjun and st["profile_state"] == "missing"
    states = {c["name"]: c["profile_state"] for c in client.get("/api/v1/characters", headers=h).json()["characters"]}
    assert states == {"Meera": "current", "Arjun": "missing"}
    ev = parse_sse(send(client, h, start(client, h, arjun).json()["id"], "hello").text)
    assert ev[0][1]["character"] == {"id": arjun, "name": "Arjun"} and ev[0][1]["profile_state"] == "missing"
    assert "NOT AVAILABLE" in cap.system and ARJUN in cap.system                      # no borrowed traits from Meera's profile


def test_the_conversation_decides_the_character_not_the_request_or_the_account_default(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    arjun = second_character(fake, "alice")
    cap = Capture()
    use(cap.provider)
    cid = start(client, h, arjun).json()["id"]
    r = client.post(f"/api/v1/conversations/{cid}/messages/stream",
                    json={"content": "hi", "client_message_id": "key-x-00001", "character_id": first_character(fake, "alice")}, headers=h)
    assert r.status_code == 200 and ARJUN in cap.system and DESC not in cap.system   # an injected character_id is ignored


def test_a_conversation_pointing_at_someone_elses_character_cannot_be_used(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    ha = ready_user(client, fake, "alice")
    ready_user(client, fake, "bob")
    cap = Capture()
    use(cap.provider)
    cid = new_conversation(client, ha)
    fake.tables["conversations"][0]["twin_id"] = first_character(fake, "bob")       # simulated corruption / tampering
    r = send(client, ha, cid, "hi")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "character_not_found"
    assert cap.bodies == [] and fake.tables["messages"] == []


def test_another_users_conversation_is_still_invisible(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    ha = ready_user(client, fake, "alice")
    hb = ready_user(client, fake, "bob")
    cap = Capture()
    use(cap.provider)
    cid = new_conversation(client, ha)
    assert send(client, hb, cid, "hi").status_code == 404 and cap.bodies == []
    assert client.get(f"/api/v1/conversations/{cid}/messages", headers=hb).status_code == 404


def test_conversations_can_be_listed_per_character_and_a_second_one_keeps_the_first(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    meera, arjun = first_character(fake, "alice"), second_character(fake, "alice")
    cap = Capture()
    use(cap.provider)
    c1 = start(client, h, meera).json()["id"]
    c2 = start(client, h, meera).json()["id"]
    c3 = start(client, h, arjun).json()["id"]
    assert len({c1, c2, c3}) == 3
    send(client, h, c1, "first chat", "key-c1-00001")
    def only(cid: str) -> set[str]:
        rows = client.get("/api/v1/conversations", params={"character_id": cid}, headers=h).json()["conversations"]
        return {c["id"] for c in rows}

    assert only(meera) == {c1, c2} and only(arjun) == {c3}
    msgs = client.get(f"/api/v1/conversations/{c1}/messages", headers=h).json()["messages"]
    assert [m["content"] for m in msgs] == ["first chat", "Sure."]                      # history intact after other chats exist
    assert client.get(f"/api/v1/conversations/{c2}/messages", headers=h).json()["messages"] == []


def test_a_learning_review_belongs_to_the_conversations_own_character(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    arjun = second_character(fake, "alice")
    enable_learning(client, h)
    cid = start(client, h, arjun).json()["id"]
    from tests.test_chat import ScriptedChat
    use(ScriptedChat(["Noted."]))
    send(client, h, cid, TEA, "key-learn-0001")
    extractor(ScriptedExtractor([cand("She likes masala chai in the mornings", "like masala chai in the mornings")]))
    assert review(client, h, cid).status_code == 202
    assert [c["twin_id"] for c in fake.tables["memory_candidates"]] == [arjun]          # not the account's first character
    app.dependency_overrides.pop(get_chat_provider, None)
