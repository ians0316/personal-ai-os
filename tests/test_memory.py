"""Semantic memory tests with the real local embedding model."""
import json

import pytest
from fastapi.testclient import TestClient

from app import agent, db, memory, tools
from app.server import app

if not (memory.MODEL_DIR.exists() and any(memory.MODEL_DIR.iterdir())):
    pytest.skip("embedding model not downloaded", allow_module_level=True)

client = TestClient(app)


@pytest.fixture(autouse=True, scope="module")
def real_model():
    memory.set_embedder(memory.Embedder())
    for n in db.list_notes(1000):
        db.delete_note(n["id"])
    memory.save_note("Mia birthday", "My sister Mia's birthday is 14 March. She likes books.", "family")
    memory.save_note("Wifi", "Home wifi password is written on the fridge")
    memory.save_note("Dentist", "Dr Lee at Smile Clinic, checkup every 6 months")
    memory.save_note("Coffee order", "I prefer oat milk flat white, no sugar")
    yield
    memory.set_embedder(None)


def titles(results):
    return [r["title"] for r in results]


@pytest.mark.parametrize("query, expected", [
    ("present for my sibling", "Mia birthday"),
    ("teeth", "Dentist"),
    ("internet login", "Wifi"),
    ("what drink do I like", "Coffee order"),
])
def test_finds_by_meaning(query, expected):
    res = memory.search(query, 3)
    assert res[0]["title"] == expected
    assert res[0]["match"] in ("meaning", "both")


def test_keyword_still_wins_for_exact_names():
    res = memory.search("Lee", 3)
    assert res[0]["title"] == "Dentist"
    assert res[0]["match"] in ("keyword", "both")


def test_unrelated_query_returns_little():
    assert len(memory.search("quantum chromodynamics lattice gauge", 5)) <= 1


def test_edit_reindexes_and_delete_forgets():
    n = memory.save_note("Car", "I drive a blue Honda Civic")
    assert titles(memory.search("what vehicle do I own", 1)) == ["Car"]
    memory.edit_note(n["id"], body="I sold my car and now cycle everywhere on a bike")
    assert "cycle" in memory.search("bicycle", 1)[0]["body"]
    memory.remove_note(n["id"])
    assert "Car" not in titles(memory.search("vehicle bicycle", 5))


def test_backfill_indexes_notes_added_outside():
    n = db.add_note("Allergy", "I am allergic to peanuts")  # bypasses the index
    assert "Allergy" not in titles(memory.search("foods that make me sick", 3))
    assert memory.backfill() == 1
    assert memory.search("foods that make me sick", 1)[0]["title"] == "Allergy"
    assert memory.backfill() == 0
    memory.remove_note(n["id"])


def test_long_note_is_chunked():
    body = ("Filler paragraph about nothing much. " * 40) + "\n\nThe spare house key is under the blue flowerpot."
    n = memory.save_note("House stuff", body)
    assert len(db._query("SELECT * FROM note_chunks WHERE note_id = ?", (n["id"],))) > 1
    assert memory.search("where is the spare key", 1)[0]["title"] == "House stuff"
    memory.remove_note(n["id"])


def test_search_tool_and_api():
    res = json.loads(tools.search_notes.call({"query": "teeth checkup"}))
    assert res["results"][0]["title"] == "Dentist"
    api = client.get("/api/notes", params={"q": "present for my sibling"}).json()
    assert api[0]["title"] == "Mia birthday"
    assert client.get("/api/memory/status").json()["semantic"] is True


def test_recall_adds_context_to_claude_message(monkeypatch):
    import anthropic
    import httpx2

    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": "14 March."}]})

    monkeypatch.setattr(agent, "_client", anthropic.Anthropic(
        api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler))))
    agent.chat("when should I get my sister a gift?")
    first_user = sent[0]["messages"][-1]["content"]
    assert "Mia birthday" in first_user and "Coffee order" not in first_user
