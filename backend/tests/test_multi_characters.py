# ruff: noqa: E501, F811
"""Several characters per account. MOCKED: Supabase is FakeSupabase (which mirrors the new constraints: kind check,
one self-twin per owner, per-owner cap, immutable kind/owner, RLS-style ownership) and the model is a scripted fake.
The migration's real behaviour in Postgres is NOT proven by these tests."""
from typing import Any

from fastapi.testclient import TestClient

from app.character_routes import _in_flight, get_analyzer
from app.main import app
from tests.conftest import auth
from tests.fake_supabase import FakeSupabase
from tests.test_character import FakeAnalyzer
from tests.test_character_conversations import ARJUN, FORGED
from tests.test_character_fidelity import Capture
from tests.test_chat import DESC, PROFILE, _reset, new_conversation, ollama_env, ready_user, send, use  # noqa: F401

ARJUN_LONG = ARJUN + " He never says more than he must, and he hums sea shanties when he is content."
ISHA = "Isha is an exuberant street-food vendor who laughs loudly, teases customers and calls everyone 'boss'."


def create(client: TestClient, h: dict[str, str], name: str, description: str = "", **extra: Any) -> Any:
    return client.post("/api/v1/characters", json={"name": name, "description": description, **extra}, headers=h)


def test_a_user_can_create_several_characters_and_keep_the_self_twin(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)                    # the personal self-twin "Meera"
    a = create(client, h, "Arjun", ARJUN)
    b = create(client, h, "Isha", ISHA)
    assert a.status_code == 201 and b.status_code == 201
    ta, tb = a.json()["twin"], b.json()["twin"]
    assert ta["id"] != tb["id"] and ta["character_description"] == ARJUN and ta["character_version"] == 1
    assert a.json()["character"]["status"] == "not_analysed"
    kinds = {t["name"]: t["kind"] for t in fake.tables["twins"]}
    assert kinds == {"Meera": "self", "Arjun": "character", "Isha": "character"}
    listed = client.get("/api/v1/characters", headers=h).json()["characters"]
    assert [(c["name"], c["is_self"]) for c in listed] == [("Meera", True), ("Arjun", False), ("Isha", False)]
    me = client.get("/api/v1/me", headers=h).json()
    assert me["twin"]["name"] == "Meera" and me["character"]["description_version"] == 1     # /me is still the self-twin
    assert client.put("/api/v1/twin", json={"name": "Meera R"}, headers=h).json()["name"] == "Meera R"   # still one self-twin
    assert sum(1 for t in fake.tables["twins"] if t["kind"] == "self") == 1


def test_creating_a_character_with_only_a_name_is_allowed_and_chat_waits_for_a_description(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    r = create(client, h, "Blank")
    assert r.status_code == 201 and r.json()["twin"]["character_description"] == "" and r.json()["character"]["status"] == "empty"
    cap = Capture()
    use(cap.provider)
    cid = client.post("/api/v1/conversations", json={"character_id": r.json()["twin"]["id"]}, headers=h).json()["id"]
    resp = send(client, h, cid, "hi")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "no_character" and cap.bodies == []


def test_creation_input_is_validated(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    assert create(client, h, "").status_code == 422
    assert create(client, h, "   ").status_code == 422
    assert create(client, h, "x" * 81).status_code == 422
    assert create(client, h, "Okay", "d" * 8001).status_code == 422
    assert client.post("/api/v1/characters", json={"name": "A", "kind": "self"}, headers=h).status_code == 422   # kind not client-settable
    assert client.post("/api/v1/characters", json={"name": "A", "owner_id": "bob"}, headers=h).status_code == 422
    assert client.post("/api/v1/characters", json={"name": "A"}).status_code == 401
    assert len(fake.tables["twins"]) == 1


def test_an_account_is_capped_at_25_characters(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    for i in range(24):
        assert create(client, h, f"C{i}").status_code == 201
    r = create(client, h, "one too many")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "character_limit"
    assert len(fake.tables["twins"]) == 25


def test_a_database_without_the_migration_says_so_instead_of_failing_blindly(client: TestClient, fake: FakeSupabase, ollama_env: None, caplog: Any) -> None:
    h = ready_user(client, fake)
    fake.legacy_schema = True                       # the old rules: kind must be 'self', one twin per owner
    with caplog.at_level("WARNING"):
        r = create(client, h, "Arjun", ARJUN)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "migration_required"
    assert "migration" in r.json()["detail"]["message"].lower()
    assert any("character_insert_rejected" in rec.message for rec in caplog.records)          # detail kept in the server log
    assert ARJUN not in caplog.text                                                          # never the description itself
    assert len(fake.tables["twins"]) == 1


def test_each_character_is_viewed_and_edited_on_its_own(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    arjun = create(client, h, "Arjun", ARJUN).json()["twin"]["id"]
    isha = create(client, h, "Isha", ISHA).json()["twin"]["id"]
    got = client.get(f"/api/v1/characters/{arjun}", headers=h).json()
    assert got["twin"]["name"] == "Arjun" and got["twin"]["character_description"] == ARJUN
    r = client.put("/api/v1/twin/character", params={"character_id": arjun}, json={"description": ARJUN_LONG, "base_version": 1}, headers=h)
    assert r.status_code == 200 and r.json()["twin"]["character_version"] == 2
    stale = client.put("/api/v1/twin/character", params={"character_id": arjun}, json={"description": "x" * 50, "base_version": 1}, headers=h)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "changed_elsewhere"
    assert client.put("/api/v1/twin", params={"character_id": isha}, json={"name": "Isha K", "about": "Sells chaat"}, headers=h).json()["name"] == "Isha K"
    by_name = {t["name"]: t for t in fake.tables["twins"]}
    assert by_name["Arjun"]["character_description"] == ARJUN_LONG and by_name["Isha K"]["character_description"] == ISHA
    assert by_name["Meera"]["character_description"] == DESC and by_name["Meera"]["character_version"] == 1     # untouched


def test_forged_foreign_and_malformed_ids_are_refused_on_every_character_endpoint(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    ha = ready_user(client, fake, "alice")
    hb = ready_user(client, fake, "bob")
    bobs = create(client, hb, "Bob's secret character", "private description of bob " * 3).json()["twin"]["id"]
    for bad in (bobs, FORGED, "not an id!", "x" * 65, "1;drop table twins"):
        for method, path, kw in (
            ("get", f"/api/v1/characters/{bad}", {}),
            ("put", "/api/v1/twin", {"json": {"name": "hijack"}, "params": {"character_id": bad}}),
            ("put", "/api/v1/twin/character", {"json": {"description": "hijack", "base_version": 1}, "params": {"character_id": bad}}),
            ("post", "/api/v1/twin/character/analyze", {"json": {"version": 1}, "params": {"character_id": bad}}),
            ("delete", "/api/v1/twin/portrait", {"params": {"character_id": bad}}),
            ("post", "/api/v1/conversations", {"json": {"character_id": bad}}),
        ):
            r = getattr(client, method)(path, headers=ha, **kw)
            assert r.status_code in (404, 422), (bad, path, r.status_code)
            if r.status_code == 404:
                assert r.json()["detail"]["code"] == "character_not_found", (bad, path)
    bob_row = [t for t in fake.tables["twins"] if t["id"] == bobs][0]
    assert bob_row["name"] == "Bob's secret character" and "hijack" not in bob_row["character_description"]
    assert "Bob's secret" not in str(client.get("/api/v1/characters", headers=ha).json())


def test_a_characters_portrait_belongs_to_that_character_only(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    arjun = create(client, h, "Arjun", ARJUN).json()["twin"]["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = client.post("/api/v1/twin/portrait", params={"character_id": arjun}, files={"file": ("p.png", png, "image/png")}, headers=h)
    assert r.status_code == 200 and r.json()["id"] == arjun and r.json()["portrait_url"]
    rows = {t["name"]: t for t in fake.tables["twins"]}
    assert rows["Arjun"]["portrait_path"] and rows["Meera"]["portrait_path"] is None
    listed = {c["name"]: c["portrait_url"] for c in client.get("/api/v1/characters", headers=h).json()["characters"]}
    assert listed["Arjun"] and listed["Meera"] is None
    assert client.delete("/api/v1/twin/portrait", params={"character_id": arjun}, headers=h).status_code == 204
    assert [t for t in fake.tables["twins"] if t["name"] == "Arjun"][0]["portrait_path"] is None


def test_each_character_is_analysed_and_gets_its_own_profile_state(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)                  # Meera has a profile
    arjun = create(client, h, "Arjun", ARJUN).json()["twin"]["id"]
    a = FakeAnalyzer()
    app.dependency_overrides[get_analyzer] = lambda: a
    _in_flight.clear()
    try:
        r = client.post("/api/v1/twin/character/analyze", params={"character_id": arjun}, json={"version": 1}, headers=h)
        assert r.status_code in (200, 202), r.text
    finally:
        app.dependency_overrides.pop(get_analyzer, None)
    assert a.seen == [ARJUN]                                                         # the model saw Arjun's description only
    st = {c["name"]: c["profile_state"] for c in client.get("/api/v1/characters", headers=h).json()["characters"]}
    assert st == {"Meera": "current", "Arjun": "current"}
    rows = {r["twin_id"]: r for r in fake.tables["character_profiles"]}
    assert len(rows) == 2 and rows[arjun]["profile"] != PROFILE                      # separate rows, separate profiles


def test_chatting_with_each_of_several_created_characters_uses_that_characters_own_description_history_and_memories(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    meera = [t for t in fake.tables["twins"]][0]["id"]
    arjun = create(client, h, "Arjun", ARJUN).json()["twin"]["id"]
    isha = create(client, h, "Isha", ISHA).json()["twin"]["id"]
    base = {"owner_id": "alice", "category": "preference", "scope": "", "supporting": [], "evidence_type": "explicit_statement", "fingerprint": "f", "status": "active"}
    for tid, text in ((meera, "Meera takes chai without sugar"), (arjun, "Arjun takes chai with ginger"), (isha, "Isha takes chai extra sweet")):
        fake.tables["memories"].append({"id": f"m-{tid}", "twin_id": tid, "statement": text, **base})
    cap = Capture()
    use(cap.provider)
    conv = {n: client.post("/api/v1/conversations", json={"character_id": c}, headers=h).json()["id"] for n, c in (("meera", meera), ("arjun", arjun), ("isha", isha))}
    # a second, separate conversation with the same character
    conv2 = client.post("/api/v1/conversations", json={"character_id": arjun}, headers=h).json()["id"]
    assert conv2 != conv["arjun"]

    expect = {"meera": (DESC, ["Arjun", "Isha"], "without sugar"), "arjun": (ARJUN, ["Meera", "street-food"], "with ginger"), "isha": (ISHA, ["gruff retired", "Warm with friends"], "extra sweet")}
    for i, name in enumerate(("meera", "arjun", "isha", "meera", "arjun")):
        own, others, mem = expect[name]
        assert send(client, h, conv[name], f"chai please {name} {i}", f"key-mc-{i:06d}").status_code == 200
        assert own in cap.system and mem in cap.system, name
        assert not any(o in cap.system for o in others), (name, others)
        history = [m["content"] for m in cap.bodies[-1]["messages"][1:]]
        assert all(name in m for m in history[::2]), history                       # only this character's conversation
    assert send(client, h, conv2, "fresh start", "key-mc-fresh01").status_code == 200
    assert [m["content"] for m in cap.bodies[-1]["messages"][1:]] == ["fresh start"]   # a separate chat starts empty
    # reopening a conversation later returns exactly its own messages
    msgs = client.get(f"/api/v1/conversations/{conv['arjun']}/messages", headers=h).json()["messages"]
    assert [m["content"] for m in msgs if m["role"] == "user"] == ["chai please arjun 1", "chai please arjun 4"]
    listed = {c["id"]: c["character_id"] for c in client.get("/api/v1/conversations", headers=h).json()["conversations"]}
    assert listed[conv["arjun"]] == arjun and listed[conv2] == arjun and listed[conv["isha"]] == isha


def test_memories_and_proposals_are_labelled_with_their_character(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    h = ready_user(client, fake)
    arjun = create(client, h, "Arjun", ARJUN).json()["twin"]["id"]
    meera = fake.tables["twins"][0]["id"]
    base = {"owner_id": "alice", "category": "preference", "scope": "", "supporting": [], "evidence_type": "explicit_statement", "fingerprint": "f", "status": "active"}
    fake.tables["memories"].append({"id": "m1", "twin_id": meera, "statement": "Meera fact", **base})
    fake.tables["memories"].append({"id": "m2", "twin_id": arjun, "statement": "Arjun fact", **base})
    got = {m["statement"]: m["character_id"] for m in client.get("/api/v1/memories", headers=h).json()["memories"]}
    assert got == {"Meera fact": meera, "Arjun fact": arjun}


def test_deleting_nothing_changes_one_users_characters_cannot_be_seen_by_another(client: TestClient, fake: FakeSupabase, ollama_env: None) -> None:
    ha = ready_user(client, fake, "alice")
    hb = ready_user(client, fake, "bob")
    create(client, ha, "Arjun", ARJUN)
    assert [c["name"] for c in client.get("/api/v1/characters", headers=hb).json()["characters"]] == ["Meera"]
    assert len(client.get("/api/v1/characters", headers=ha).json()["characters"]) == 2
    assert auth("alice") != auth("bob")
